# ══════════════════════════════════════════════════════════════════
# AAA Platform — developer automation
# ══════════════════════════════════════════════════════════════════

CLUSTER     := aaa-dev
NAMESPACE   := aaa-platform
CHART_DIR   := ./charts/aaa-platform
RELEASE     := aaa-platform
# REGISTRY: Docker Desktop = aaa (local images, pullPolicy: Never)
#           k3d            = k3d-aaa-registry.localhost:5111
#           Remote         = your registry prefix
REGISTRY    ?= aaa
TAG         ?= dev
# Tag for C++ vcpkg base images — change when vcpkg.json changes to force a rebuild
BASE_TAG    ?= latest

# Database connection — override for non-local environments
DB_USER     ?= aaa_app
DB_PASSWORD ?= devpassword
DB_HOST     ?= localhost
DB_PORT     ?= 5432
DB_NAME     ?= aaa
DB_URL      ?= postgres://$(DB_USER):$(DB_PASSWORD)@$(DB_HOST):$(DB_PORT)/$(DB_NAME)

# RADIUS shared secret — single source of truth.
# aaa-radius-server and aaa-regression-tester both read from the same
# K8s secret (aaa-radius-secret). Override at the CLI if rotating:
#   make deploy RADIUS_SECRET=new-value
RADIUS_SECRET ?= testing123

SCRIPT      ?= load.js   # override: make load-test-k8s SCRIPT=stress.js
PCAP        ?= false     # set to true to attach a tcpdump sidecar: make test PCAP=true
radiusPCAP  ?= false     # set to true to attach a tcpdump sidecar to radius-server: make deploy radiusPCAP=true

.PHONY: help \
        cluster-up cluster-down cluster-status cnpg-install nginx-install dep-update prom-crds \
        build-cpp-bases build-lookup-base build-radius-base push-cpp-bases push-lookup-base push-radius-base \
        build-all build-api build-lookup build-radius-server build-tester push-all build-push build-ui \
        hosts bootstrap setup helm-unlock \
        deploy deploy-dry-run deploy-migration db-init db-flush-stale \
        test test-secret radius-secret pcap-get pcap-get-radius \
        port-forward-lookup port-forward-api port-forward-db port-forward-ui \
        port-forward-grafana port-forward-prometheus port-forward-pgbouncer \
        grafana-dashboard-reload grafana-open \
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

# ── Full dev bootstrap — k3d (first time) ─────────────────────
bootstrap: cluster-up hosts build-cpp-bases build-all push-all dep-update prom-crds deploy db-init ## k3d: create cluster, push images, deploy everything
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║  AAA Platform is running!                               ║"
	@echo "║  UI:          http://ui.aaa.localhost                   ║"
	@echo "║  API:         http://provisioning.aaa.localhost/v1      ║"
	@echo "║  Lookup:      http://lookup.aaa.localhost/health        ║"
	@echo "║  Grafana:     http://grafana.aaa.localhost (dev-grafana)║"
	@echo "║  Prometheus:  http://prometheus.aaa.localhost           ║"
	@echo "╚══════════════════════════════════════════════════════════╝"

# ── Docker Desktop setup (first time, no k3d needed) ──────────
setup: cnpg-install nginx-install hosts build-cpp-bases build-all dep-update prom-crds deploy db-init ## Docker Desktop: install operators, build images, deploy everything (secrets created automatically by deploy)
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║  AAA Platform is running on Docker Desktop!             ║"
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

nginx-install:                  ## Install nginx-ingress controller (once per cluster, Docker Desktop)
	helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx --force-update
	helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
	  --namespace ingress-nginx --create-namespace \
	  --set controller.service.type=LoadBalancer \
	  --wait
	@echo "nginx-ingress controller ready."

# ── Helm dependency management ────────────────────────────────
dep-update:                     ## Resolve and vendor all sub-chart dependencies
	helm dependency update $(CHART_DIR)

prom-crds:                      ## Install Prometheus Operator CRDs from cached chart (run once after dep-update)
	@tar -xzf $(CHART_DIR)/charts/kube-prometheus-stack-*.tgz \
	  -C /tmp kube-prometheus-stack/charts/crds/crds/
	kubectl apply --server-side -f /tmp/kube-prometheus-stack/charts/crds/crds/
	@rm -rf /tmp/kube-prometheus-stack
	@echo "Prometheus Operator CRDs installed."

# ── C++ vcpkg base images (build once; rebuild only when vcpkg.json changes) ──
build-lookup-base:              ## Build vcpkg base for aaa-lookup-service (run once or when vcpkg.json changes)
	docker build -t $(REGISTRY)/aaa-lookup-build-base:$(BASE_TAG) \
	  -f ./aaa-lookup-service/Dockerfile.base \
	  ./aaa-lookup-service/

build-radius-base:              ## Build vcpkg base for aaa-radius-server (run once or when vcpkg.json changes)
	docker build -t $(REGISTRY)/aaa-radius-build-base:$(BASE_TAG) \
	  -f ./aaa-radius-server/Dockerfile.base \
	  ./aaa-radius-server/

build-cpp-bases: build-lookup-base build-radius-base  ## Build both C++ vcpkg base images

push-lookup-base:               ## Push aaa-lookup-build-base to registry
	docker push $(REGISTRY)/aaa-lookup-build-base:$(BASE_TAG)

push-radius-base:               ## Push aaa-radius-build-base to registry
	docker push $(REGISTRY)/aaa-radius-build-base:$(BASE_TAG)

push-cpp-bases: push-lookup-base push-radius-base  ## Push both C++ vcpkg base images

# ── Image management ──────────────────────────────────────────
build-all:                      ## Build all service images (REGISTRY=aaa TAG=dev); run build-cpp-bases first if bases don't exist
	docker build -t $(REGISTRY)/aaa-lookup-service:$(TAG) \
	  --build-arg BUILD_BASE=$(REGISTRY)/aaa-lookup-build-base:$(BASE_TAG) \
	  ./aaa-lookup-service/
	docker build -t $(REGISTRY)/aaa-radius-server:$(TAG) \
	  --build-arg BUILD_BASE=$(REGISTRY)/aaa-radius-build-base:$(BASE_TAG) \
	  ./aaa-radius-server/
	@for svc in subscriber-profile-api aaa-management-ui aaa-regression-tester; do \
	  [ -d "./$$svc" ] || continue; \
	  echo "── Building $$svc ──────────────────────────────────"; \
	  docker build -t $(REGISTRY)/$$svc:$(TAG) ./$$svc/; \
	done

build-radius-server:            ## Build just the aaa-radius-server image
	docker build -t $(REGISTRY)/aaa-radius-server:$(TAG) \
	  --build-arg BUILD_BASE=$(REGISTRY)/aaa-radius-build-base:$(BASE_TAG) \
	  ./aaa-radius-server/

build-api:                      ## Rebuild subscriber-profile-api and restart its pod (picks up code changes with pullPolicy:Never)
	docker build -t $(REGISTRY)/subscriber-profile-api:$(TAG) ./subscriber-profile-api/
	kubectl rollout restart deployment/$(RELEASE)-subscriber-profile-api -n $(NAMESPACE)
	kubectl rollout status deployment/$(RELEASE)-subscriber-profile-api -n $(NAMESPACE)

build-lookup:                   ## Rebuild aaa-lookup-service and restart its pod
	docker build -t $(REGISTRY)/aaa-lookup-service:$(TAG) \
	  --build-arg BUILD_BASE=$(REGISTRY)/aaa-lookup-build-base:$(BASE_TAG) \
	  ./aaa-lookup-service/
	kubectl rollout restart deployment/$(RELEASE)-aaa-lookup-service -n $(NAMESPACE)
	kubectl rollout status deployment/$(RELEASE)-aaa-lookup-service -n $(NAMESPACE)

build-tester:                   ## Rebuild aaa-regression-tester image and repackage its Helm chart
	docker build -t $(REGISTRY)/aaa-regression-tester:$(TAG) ./aaa-regression-tester/
	helm package ./charts/aaa-regression-tester -d ./charts/aaa-platform/charts/

push-all:                       ## Push all service images to the registry (k3d / remote only)
	@for svc in $(SERVICES); do \
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
deploy: radius-secret test-secret ## Deploy/upgrade umbrella chart (creates required secrets first, then applies chart); radiusPCAP=true adds tcpdump sidecar to radius-server
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
	  --namespace $(NAMESPACE) --create-namespace \
	  -f $(CHART_DIR)/values-dev.yaml \
	  --set "aaa-radius-server.pcap.enabled=$(radiusPCAP)" \
	  --timeout 10m

helm-unlock:                    ## Clear a stuck Helm lock (run if deploy fails with 'another operation in progress')
	@echo "Rolling back to last successful release to clear lock..."
	helm rollback $(RELEASE) -n $(NAMESPACE) 2>/dev/null || \
	  kubectl delete secret -n $(NAMESPACE) \
	    -l 'status in (pending-install,pending-upgrade,pending-rollback),owner=helm'
	@echo "Lock cleared. Re-run: wsl make deploy"

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

db-init:                        ## Apply DB schema + grants idempotently (auto-called by setup/bootstrap; run manually on existing clusters)
	@NAMESPACE=$(NAMESPACE) bash scripts/db-init.sh

db-flush-stale:                 ## Full profile cleanup: truncates all device/IMSI/IP data (dev only; run before make test when tests fail with stale-data errors)
	@POD=$$(kubectl get pod -n $(NAMESPACE) -l cnpg.io/instanceRole=primary \
	  -o jsonpath='{.items[0].metadata.name}'); \
	kubectl exec -i "$$POD" -n $(NAMESPACE) -- \
	  psql -U postgres -d $(DB_NAME) -v ON_ERROR_STOP=1 \
	  -c "TRUNCATE imsi_apn_ips, sim_apn_ips, imsi2sim, sim_profiles CASCADE"
	@echo "All profile data removed. Pools and range configs preserved."

# ── Regression tests ──────────────────────────────────────────
test-secret:                    ## Create the JWT secret for regression tester
	kubectl create secret generic aaa-test-jwt \
	  --from-literal=token="dev-skip-verify" \
	  -n $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -

radius-secret:                  ## Create/update aaa-radius-secret from RADIUS_SECRET var (used by radius-server AND regression tester)
	kubectl create secret generic aaa-radius-secret \
	  --from-literal=radius-secret="$(RADIUS_SECRET)" \
	  -n $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -

test:                           ## Run regression suite (append PCAP=true to capture traffic)
	$(MAKE) test-secret
	$(MAKE) radius-secret
	@echo "Repackaging aaa-regression-tester sub-chart..."
	helm package ./charts/aaa-regression-tester -d ./charts/aaa-platform/charts/
	@echo "Removing any previous regression-tester Job and pods..."
	kubectl delete jobs -n $(NAMESPACE) \
	  -l app.kubernetes.io/name=aaa-regression-tester \
	  --ignore-not-found --wait=true
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
	  --namespace $(NAMESPACE) \
	  -f $(CHART_DIR)/values-dev.yaml \
	  --set "aaa-regression-tester.enabled=true" \
	  --set "aaa-regression-tester.pcap.enabled=$(PCAP)" \
	  --timeout 10m
	@echo "Waiting for regression-tester Job to start..."
	kubectl wait pod \
	  -l app.kubernetes.io/name=aaa-regression-tester \
	  -n $(NAMESPACE) --for=condition=Ready --timeout=120s || true
	@echo "Waiting for test Job to complete (max 15m)..."
	kubectl wait --for=condition=complete \
	  job/$$(kubectl get jobs -n $(NAMESPACE) \
	    -l app.kubernetes.io/name=aaa-regression-tester \
	    -o jsonpath='{.items[0].metadata.name}') \
	  -n $(NAMESPACE) --timeout=900s
	kubectl logs -n $(NAMESPACE) \
	  $$(kubectl get pods -n $(NAMESPACE) \
	    -l app.kubernetes.io/name=aaa-regression-tester \
	    -o jsonpath='{.items[0].metadata.name}') \
	  -c regression-tester
	@if [ "$(PCAP)" = "true" ]; then \
	  echo ""; \
	  echo "══════════════════════════════════════════════════════════════"; \
	  echo " Packet capture complete."; \
	  echo " Stored in PVC: $(RELEASE)-aaa-regression-tester-pcap"; \
	  echo " Fetch:  make pcap-get          → saves ./test.pcap"; \
	  echo " Open :  wireshark ./test.pcap"; \
	  echo "══════════════════════════════════════════════════════════════"; \
	fi

pcap-get:                       ## Copy test.pcap from the PCAP=true PVC to ./test.pcap (works after pod exits)
	bash scripts/pcap-get.sh $(NAMESPACE) $(RELEASE)-aaa-regression-tester-pcap ./test.pcap

pcap-get-radius:                ## Copy radius.pcap from the radiusPCAP=true PVC to ./radius.pcap (live or after pod exits)
	bash scripts/pcap-get.sh $(NAMESPACE) $(RELEASE)-aaa-radius-server-pcap ./radius.pcap

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
	kubectl port-forward -n $(NAMESPACE) svc/prometheus-operated 9090:9090

grafana-dashboard-reload:       ## Push updated dashboard JSON to the cluster ConfigMap (no full redeploy)
	@echo "Syncing dashboard JSON to Helm files directory..."
	cp grafana/aaa-platform-dashboard.json \
	   $(CHART_DIR)/files/aaa-platform-dashboard.json
	@echo "Applying updated ConfigMap to cluster..."
	kubectl create configmap $(RELEASE)-grafana-aaa-dashboard \
	  --from-file=aaa-platform-dashboard.json=$(CHART_DIR)/files/aaa-platform-dashboard.json \
	  --namespace $(NAMESPACE) \
	  --dry-run=client -o yaml | \
	kubectl annotate --overwrite -f - \
	  grafana_folder="AAA Platform" 2>/dev/null || \
	kubectl create configmap $(RELEASE)-grafana-aaa-dashboard \
	  --from-file=aaa-platform-dashboard.json=$(CHART_DIR)/files/aaa-platform-dashboard.json \
	  --namespace $(NAMESPACE) \
	  --dry-run=client -o yaml | kubectl apply -f -
	kubectl label configmap $(RELEASE)-grafana-aaa-dashboard \
	  grafana_dashboard=1 \
	  -n $(NAMESPACE) --overwrite
	@echo "Dashboard reloaded. Grafana sidecar will pick it up within ~30 s."

grafana-open:                   ## Open Grafana in the browser via port-forward (background)
	@echo "Starting port-forward on localhost:3000 — press Ctrl+C to stop"
	@kubectl port-forward -n $(NAMESPACE) svc/$(RELEASE)-grafana 3000:80 &
	@sleep 2 && open http://localhost:3000 || \
	  xdg-open http://localhost:3000 2>/dev/null || \
	  start http://localhost:3000 2>/dev/null || \
	  echo "Open http://localhost:3000 in your browser (admin / dev-grafana)"

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
	psql "$(DB_URL)" \
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
