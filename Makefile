# ══════════════════════════════════════════════════════════════════
# AAA Platform — developer automation
# ══════════════════════════════════════════════════════════════════

CLUSTER     := aaa-dev
NAMESPACE   := aaa-platform
CHART_DIR   := ./charts/aaa-platform
RELEASE     := aaa-platform
REGISTRY    ?= k3d-aaa-registry.localhost:5111
TAG         ?= dev

SCRIPT      ?= load.js   # override: make load-test-k8s SCRIPT=stress.js

.PHONY: help \
        cluster-up cluster-down cluster-status cnpg-install dep-update \
        build-all build-radius-server push-all build-push build-ui \
        hosts bootstrap \
        deploy deploy-dry-run deploy-migration \
        test test-secret \
        port-forward-lookup port-forward-api port-forward-db port-forward-ui \
        port-forward-grafana port-forward-prometheus port-forward-pgbouncer \
        logs logs-lookup logs-api logs-ui \
        status uninstall clean \
        build-load-tester load-test-seed \
        load-test-smoke load-test-load load-test-stress load-test-spike load-test-soak \
        load-test-k8s load-test-logs-k8s

help:                           ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | \
	  awk 'BEGIN {FS=":.*## "}; {printf "  %-28s %s\n", $$1, $$2}'

# ── Cluster lifecycle ──────────────────────────────────────────
cluster-up:                     ## Create k3d cluster + nginx-ingress + cnpg operator
	@bash scripts/k3d-up.sh

cluster-down:                   ## Destroy k3d cluster (data lost)
	k3d cluster delete $(CLUSTER)

cluster-status:                 ## Show cluster node and pod status
	kubectl get nodes && kubectl get pods -A

# ── Hosts file ────────────────────────────────────────────────
hosts:                          ## Update WSL2 /etc/hosts with .aaa.localhost entries
	@bash scripts/hosts-update.sh

# ── Full dev bootstrap (first time) ───────────────────────────
bootstrap: cluster-up hosts build-all push-all dep-update deploy ## Create cluster, push images, deploy everything
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║  AAA Platform is running on k3d!                        ║"
	@echo "║  UI:          http://ui.aaa.localhost                   ║"
	@echo "║  API:         http://provisioning.aaa.localhost/v1      ║"
	@echo "║  Lookup:      http://lookup.aaa.localhost/health        ║"
	@echo "║  Grafana:     http://grafana.aaa.localhost (dev-grafana)║"
	@echo "║  Prometheus:  http://prometheus.aaa.localhost           ║"
	@echo "╚══════════════════════════════════════════════════════════╝"

# ── Prerequisites ─────────────────────────────────────────────
cnpg-install:                   ## Install CloudNativePG operator (once per cluster)
	helm repo add cnpg https://cloudnative-pg.github.io/charts --force-update
	helm upgrade --install cnpg cnpg/cloudnative-pg \
	  --namespace cnpg-system --create-namespace \
	  --wait
	@echo "CloudNativePG operator ready."

# ── Helm dependency management ────────────────────────────────
dep-update:                     ## Resolve and vendor all sub-chart dependencies
	helm dependency update $(CHART_DIR)

# ── Image management ──────────────────────────────────────────
build-all:                      ## Build all service images (TAG=dev, REGISTRY=k3d by default)
	@for svc in aaa-lookup-service aaa-radius-server subscriber-profile-api aaa-management-ui aaa-regression-tester aaa-migration; do \
	  [ -d "./$$svc" ] || continue; \
	  echo "── Building $$svc ──────────────────────────────────"; \
	  docker build -t $(REGISTRY)/$$svc:$(TAG) ./$$svc/; \
	done

build-radius-server:            ## Build just the aaa-radius-server image
	docker build -t $(REGISTRY)/aaa-radius-server:$(TAG) ./aaa-radius-server/

push-all:                       ## Push all service images to the registry
	@for svc in aaa-lookup-service aaa-radius-server subscriber-profile-api aaa-management-ui aaa-regression-tester aaa-migration; do \
	  [ -d "./$$svc" ] || continue; \
	  echo "── Pushing $$svc ───────────────────────────────────"; \
	  docker push $(REGISTRY)/$$svc:$(TAG); \
	done

build-push:                     ## Build and push all images in one step
	$(MAKE) build-all REGISTRY=$(REGISTRY) TAG=$(TAG)
	$(MAKE) push-all  REGISTRY=$(REGISTRY) TAG=$(TAG)

build-ui:                       ## Build just the aaa-management-ui image (dev, no registry needed)
	docker build -t aaa/aaa-management-ui:dev ./aaa-management-ui/

# ── Deploy ────────────────────────────────────────────────────
deploy:                         ## Deploy/upgrade umbrella chart with values-dev.yaml
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
	  --namespace $(NAMESPACE) --create-namespace \
	  -f $(CHART_DIR)/values-dev.yaml \
	  --wait --timeout 10m

deploy-dry-run:                 ## Render templates without applying (validates chart)
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
	  --namespace $(NAMESPACE) --create-namespace \
	  -f $(CHART_DIR)/values-dev.yaml \
	  --dry-run --debug 2>&1 | head -300

deploy-migration:               ## Run migration Jobs (Steps 1–3)
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
	  --namespace $(NAMESPACE) \
	  -f $(CHART_DIR)/values-dev.yaml \
	  --set "aaa-migration.enabled=true" \
	  --wait

# ── Regression tests ──────────────────────────────────────────
test-secret:                    ## Create the JWT secret for regression tester
	kubectl create secret generic aaa-test-jwt \
	  --from-literal=token="dev-skip-verify" \
	  -n $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -

test:                           ## Run full regression suite as a Kubernetes Job
	$(MAKE) test-secret
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
	  --namespace $(NAMESPACE) \
	  -f $(CHART_DIR)/values-dev.yaml \
	  --set "aaa-regression-tester.enabled=true" \
	  --wait --timeout 15m
	@echo "Waiting for test Job to complete (max 15m)..."
	kubectl wait --for=condition=complete \
	  job/$$(kubectl get jobs -n $(NAMESPACE) \
	    -l app.kubernetes.io/name=aaa-regression-tester \
	    -o jsonpath='{.items[0].metadata.name}') \
	  -n $(NAMESPACE) --timeout=900s
	kubectl logs -n $(NAMESPACE) \
	  $$(kubectl get pods -n $(NAMESPACE) \
	    -l app.kubernetes.io/name=aaa-regression-tester \
	    -o jsonpath='{.items[0].metadata.name}')

# ── Port-forwarding ───────────────────────────────────────────
port-forward-lookup:            ## Forward aaa-lookup-service to localhost:8081
	kubectl port-forward -n $(NAMESPACE) svc/$(RELEASE)-aaa-lookup-service 8081:8081

port-forward-api:               ## Forward subscriber-profile-api to localhost:8080
	kubectl port-forward -n $(NAMESPACE) svc/$(RELEASE)-subscriber-profile-api 8080:8080

port-forward-db:                ## Forward PgBouncer RW to localhost:5432
	kubectl port-forward -n $(NAMESPACE) svc/aaa-postgres-pooler-rw 5432:5432

port-forward-ui:                ## Forward aaa-management-ui to localhost:8090
	kubectl port-forward -n $(NAMESPACE) svc/$(RELEASE)-aaa-management-ui 8090:80

port-forward-grafana:           ## Forward Grafana to localhost:3000 (bypass ingress)
	kubectl port-forward -n $(NAMESPACE) svc/$(RELEASE)-grafana 3000:80

port-forward-prometheus:        ## Forward Prometheus to localhost:9090 (bypass ingress)
	kubectl port-forward -n $(NAMESPACE) svc/$(RELEASE)-kube-prometheus-prometheus 9090:9090

port-forward-pgbouncer:         ## Forward PgBouncer RW to localhost:5432 (alias for port-forward-db)
	kubectl port-forward -n $(NAMESPACE) svc/aaa-postgres-pooler-rw 5432:5432

# ── Logs ──────────────────────────────────────────────────────
logs:                           ## Tail logs from all app pods
	kubectl logs -n $(NAMESPACE) \
	  -l 'app.kubernetes.io/component in (aaa-hotpath,provisioning-api,management-ui)' \
	  --all-containers --prefix --follow

logs-lookup:                    ## Tail aaa-lookup-service logs
	kubectl logs -n $(NAMESPACE) \
	  -l app.kubernetes.io/name=aaa-lookup-service \
	  --all-containers --prefix --follow

logs-api:                       ## Tail subscriber-profile-api logs
	kubectl logs -n $(NAMESPACE) \
	  -l app.kubernetes.io/name=subscriber-profile-api \
	  --all-containers --prefix --follow

logs-ui:                        ## Tail aaa-management-ui logs
	kubectl logs -n $(NAMESPACE) \
	  -l app.kubernetes.io/name=aaa-management-ui \
	  --all-containers --prefix --follow

# ── Status ────────────────────────────────────────────────────
status:                         ## Show all pods, services, ingress, and CNPG cluster health
	@echo "═══ Pods ════════════════════════════════════════════"
	kubectl get pods -n $(NAMESPACE) -o wide
	@echo "═══ Services ════════════════════════════════════════"
	kubectl get svc -n $(NAMESPACE)
	@echo "═══ Ingress ═════════════════════════════════════════"
	kubectl get ingress -n $(NAMESPACE)
	@echo "═══ PVCs ════════════════════════════════════════════"
	kubectl get pvc -n $(NAMESPACE)
	@echo "═══ CNPG Cluster ════════════════════════════════════"
	kubectl get cluster -n $(NAMESPACE)
	@echo "═══ Jobs ════════════════════════════════════════════"
	kubectl get jobs -n $(NAMESPACE)

# ── Load testing ──────────────────────────────────────────────
build-load-tester:              ## Build k6 load-test image (aaa/aaa-load-tester:dev)
	docker build -t aaa/aaa-load-tester:dev ./load-testing/

load-test-seed:                 ## Seed 10k test subscribers (requires: make port-forward-db)
	psql "postgres://aaa_app:devpassword@localhost:5432/aaa" \
	  -f ./load-testing/seed/seed_load_test.sql

load-test-smoke:                ## Smoke test — 1 VU, 1 min (requires: make port-forward-lookup)
	docker run --rm \
	  -e TARGET_URL=http://host.docker.internal:8081 \
	  aaa/aaa-load-tester:dev run /scripts/smoke.js

load-test-load:                 ## Load test — ramp to 500 RPS, 14 min (requires: make port-forward-lookup)
	docker run --rm \
	  -e TARGET_URL=http://host.docker.internal:8081 \
	  aaa/aaa-load-tester:dev run /scripts/load.js

load-test-stress:               ## Stress test — find breaking point up to 2000 RPS
	docker run --rm \
	  -e TARGET_URL=http://host.docker.internal:8081 \
	  aaa/aaa-load-tester:dev run /scripts/stress.js

load-test-spike:                ## Spike test — instant burst 50→2000→50 RPS
	docker run --rm \
	  -e TARGET_URL=http://host.docker.internal:8081 \
	  aaa/aaa-load-tester:dev run /scripts/spike.js

load-test-soak:                 ## Soak test — 300 RPS for 45 min (memory / leak detection)
	docker run --rm \
	  -e TARGET_URL=http://host.docker.internal:8081 \
	  aaa/aaa-load-tester:dev run /scripts/soak.js

load-test-k8s:                  ## Run load test as K8s Job (SCRIPT=load.js)
	kubectl delete job aaa-load-test -n $(NAMESPACE) --ignore-not-found
	kubectl create job aaa-load-test \
	  --image=aaa/aaa-load-tester:dev \
	  -n $(NAMESPACE) \
	  -- k6 run --env TARGET_URL=http://$(RELEASE)-aaa-lookup-service:8081 \
	            --env SCRIPT=$(SCRIPT) \
	     /scripts/$(SCRIPT)
	@echo "Waiting for load test Job to complete..."
	kubectl wait --for=condition=complete \
	  job/aaa-load-test -n $(NAMESPACE) --timeout=3600s
	$(MAKE) load-test-logs-k8s

load-test-logs-k8s:             ## Print logs from the last load test K8s Job
	kubectl logs -n $(NAMESPACE) \
	  $$(kubectl get pods -n $(NAMESPACE) -l job-name=aaa-load-test \
	    -o jsonpath='{.items[0].metadata.name}')

# ── Teardown ──────────────────────────────────────────────────
uninstall:                      ## Uninstall Helm release (keeps namespace and PVCs)
	helm uninstall $(RELEASE) -n $(NAMESPACE)

clean: uninstall cluster-down   ## Full teardown: uninstall Helm release + delete k3d cluster
