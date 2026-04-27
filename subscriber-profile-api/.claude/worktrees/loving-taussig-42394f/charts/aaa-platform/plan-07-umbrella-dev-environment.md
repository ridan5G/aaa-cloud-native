# Plan 7 — Umbrella Helm Chart & Local Dev Environment (k3d / WSL2)

## Overview

The entire AAA platform is packaged as a single **umbrella Helm chart** (`aaa-platform`)
that declares every sub-chart as a versioned dependency. A single `helm upgrade --install`
command with the right values file brings up the complete stack.

| Target | Values file | Notes |
|---|---|---|
| **Local dev** | `values-dev.yaml` | k3d on WSL2; single replicas; no TLS; local registry |
| **Staging / CI** | `values-staging.yaml` | k3d or kind; mirrors prod sizing |
| **Production (k8s)** | `values.yaml` | Generic CNCF-conformant cluster |
| **Production (OCI/OKE)** | `values-oci.yaml` | OCI-specific storage classes, load balancer annotations |

---

## Monorepo Layout

```
aaa-cloud-native/
├── charts/
│   ├── aaa-platform/                  ← umbrella chart
│   │   ├── Chart.yaml
│   │   ├── Chart.lock
│   │   ├── values.yaml                ← production defaults (all components)
│   │   ├── values-dev.yaml            ← k3d / WSL2 overrides
│   │   ├── values-oci.yaml            ← OCI / OKE overrides
│   │   └── templates/
│   │       ├── namespace.yaml         ← creates aaa-platform namespace
│   │       └── _helpers.tpl
│   ├── aaa-database/                  ← sub-chart (Plan 2)
│   ├── aaa-lookup-service/            ← sub-chart (Plan 3)
│   ├── subscriber-profile-api/        ← sub-chart (Plan 4)
│   ├── aaa-management-ui/             ← sub-chart (Plan 5)
│   ├── aaa-migration/                 ← sub-chart (Plan 6)
│   └── aaa-regression-tester/         ← sub-chart (Plan 1)
├── Makefile
└── scripts/
    ├── k3d-up.sh                      ← cluster bootstrap
    ├── hosts-update.sh                ← /etc/hosts helper
    └── image-push.sh                  ← build & push to k3d registry
```

---

## Umbrella Chart

### Chart.yaml

```yaml
apiVersion: v2
name: aaa-platform
description: AAA Cloud-Native Platform — umbrella chart
type: application
version: 1.0.0
appVersion: "1.0.0"

dependencies:
  # ── Core infrastructure ──────────────────────────────────────
  - name: aaa-database
    version: "1.0.0"
    repository: "file://../aaa-database"
    condition: aaa-database.enabled

  # ── Application services ─────────────────────────────────────
  - name: aaa-lookup-service
    version: "1.0.0"
    repository: "file://../aaa-lookup-service"
    condition: aaa-lookup-service.enabled

  - name: subscriber-profile-api
    version: "1.0.0"
    repository: "file://../subscriber-profile-api"
    condition: subscriber-profile-api.enabled

  - name: aaa-management-ui
    version: "1.0.0"
    repository: "file://../aaa-management-ui"
    condition: aaa-management-ui.enabled

  # ── Observability stack ──────────────────────────────────────
  - name: kube-prometheus-stack
    version: "55.x.x"
    repository: "https://prometheus-community.github.io/helm-charts"
    condition: kube-prometheus-stack.enabled

  - name: prometheus-pushgateway
    version: "2.x.x"
    repository: "https://prometheus-community.github.io/helm-charts"
    condition: prometheus-pushgateway.enabled

  # ── One-time jobs (disabled by default — run manually) ───────
  - name: aaa-migration
    version: "1.0.0"
    repository: "file://../aaa-migration"
    condition: aaa-migration.enabled

  - name: aaa-regression-tester
    version: "1.0.0"
    repository: "file://../aaa-regression-tester"
    condition: aaa-regression-tester.enabled
```

---

### values.yaml (production stub — structure only)

```yaml
# Production defaults — override per environment with values-{env}.yaml

"aaa-database":
  enabled: true

"aaa-lookup-service":
  enabled: true

"subscriber-profile-api":
  enabled: true

"aaa-management-ui":
  enabled: true

"kube-prometheus-stack":
  enabled: true

"prometheus-pushgateway":
  enabled: true

"aaa-migration":
  enabled: false   # triggered manually at migration time

"aaa-regression-tester":
  enabled: false   # triggered by CI
```

---

## values-dev.yaml — k3d / WSL2 Overrides

```yaml
# ═══════════════════════════════════════════════════════════════
# values-dev.yaml  —  k3d / WSL2 local development
#
# Deploy with:
#   helm upgrade --install aaa-platform ./charts/aaa-platform \
#     -f ./charts/aaa-platform/values-dev.yaml \
#     -n aaa-platform --create-namespace
# ═══════════════════════════════════════════════════════════════

# ── Database ─────────────────────────────────────────────────
"aaa-database":
  enabled: true

  postgresql:
    instances: 1                        # single pod — no HA / standbys in dev
    imageName: ghcr.io/cloudnative-pg/postgresql:15.6
    storage:
      size: 5Gi
      storageClass: local-path          # k3s built-in provisioner
    resources:
      requests:
        cpu: "250m"
        memory: "512Mi"
      limits:
        cpu: "1"
        memory: "1Gi"
    postgresql:
      max_connections: "50"
      shared_buffers: "128MB"
      work_mem: "4MB"
      maintenance_work_mem: "64MB"
      effective_cache_size: "256MB"
      wal_level: logical
    monitoring:
      enabled: true

  pgbouncer:
    replicas: 1
    poolMode: transaction
    maxClientConn: 100
    defaultPoolSize: 10
    resources:
      requests:
        cpu: "50m"
        memory: "32Mi"
      limits:
        cpu: "200m"
        memory: "64Mi"

# ── AAA Lookup Service ────────────────────────────────────────
"aaa-lookup-service":
  enabled: true
  replicaCount: 1

  image:
    repository: k3d-aaa-registry.localhost:5111/aaa-lookup-service
    tag: dev
    pullPolicy: Always

  service:
    type: ClusterIP
    port: 8081
    metricsPort: 9090

  ingress:
    enabled: true
    className: nginx
    host: lookup.aaa.localhost
    tls:
      enabled: false                    # HTTP only in dev

  db:
    secretName: aaa-db-credentials-dev

  resources:
    requests:
      cpu: "100m"
      memory: "128Mi"
    limits:
      cpu: "500m"
      memory: "256Mi"

  autoscaling:
    enabled: false                      # fixed 1 replica in dev

  podDisruptionBudget:
    minAvailable: 0                     # allow full eviction in single-replica dev

  affinity: {}                          # no zone spreading in single-node dev cluster

# ── Provisioning API ─────────────────────────────────────────
"subscriber-profile-api":
  enabled: true
  replicaCount: 1

  image:
    repository: k3d-aaa-registry.localhost:5111/subscriber-profile-api
    tag: dev
    pullPolicy: Always

  ingress:
    enabled: true
    className: nginx
    host: provisioning.aaa.localhost
    tls:
      enabled: false

  db:
    secretName: aaa-db-credentials-dev

  bulkJob:
    workerThreads: 2
    batchSize: 500

  resources:
    requests:
      cpu: "250m"
      memory: "256Mi"
    limits:
      cpu: "1"
      memory: "512Mi"

  autoscaling:
    enabled: false

  podDisruptionBudget:
    minAvailable: 0

  affinity: {}

# ── Management UI ─────────────────────────────────────────────
"aaa-management-ui":
  enabled: true
  replicaCount: 1

  image:
    repository: k3d-aaa-registry.localhost:5111/aaa-management-ui
    tag: dev
    pullPolicy: Always

  ingress:
    enabled: true
    className: nginx
    host: ui.aaa.localhost
    tls:
      enabled: false

  appConfig:
    apiBaseUrl: "http://provisioning.aaa.localhost/v1"
    oidcAuthority: "http://auth.aaa.localhost/realms/aaa"
    oidcClientId: "aaa-management-ui"

  resources:
    requests:
      cpu: "50m"
      memory: "64Mi"
    limits:
      cpu: "200m"
      memory: "128Mi"

# ── Prometheus + Grafana (kube-prometheus-stack) ──────────────
"kube-prometheus-stack":
  enabled: true

  grafana:
    enabled: true
    adminPassword: "dev-grafana"        # dev only — no secrets management needed
    ingress:
      enabled: true
      ingressClassName: nginx
      hosts:
        - grafana.aaa.localhost
      tls: []                           # no TLS in dev
    resources:
      requests:
        cpu: "50m"
        memory: "128Mi"
      limits:
        cpu: "200m"
        memory: "256Mi"
    persistence:
      enabled: false                    # ephemeral — provision dashboards via ConfigMaps

    # Auto-provision all AAA dashboards from ConfigMaps in aaa-platform namespace
    sidecar:
      dashboards:
        enabled: true
        searchNamespace: aaa-platform

    # Auto-provision Prometheus datasource
    additionalDataSources:
      - name: Prometheus
        type: prometheus
        url: http://aaa-platform-kube-prometheus-prometheus:9090
        access: proxy
        isDefault: true

  prometheus:
    prometheusSpec:
      retention: 6h                     # short retention — dev only
      scrapeInterval: 15s
      resources:
        requests:
          cpu: "100m"
          memory: "512Mi"
        limits:
          cpu: "500m"
          memory: "1Gi"
      storageSpec:
        volumeClaimTemplate:
          spec:
            storageClassName: local-path
            resources:
              requests:
                storage: 5Gi
      # Scrape all pods with prometheus.io/scrape annotation in all namespaces
      podMonitorSelectorNilUsesHelmValues: false
      serviceMonitorSelectorNilUsesHelmValues: false

  alertmanager:
    enabled: false                      # skip alertmanager in dev

  nodeExporter:
    enabled: true

  kubeStateMetrics:
    enabled: true

  # Expose Prometheus UI via ingress
  prometheus:
    ingress:
      enabled: true
      ingressClassName: nginx
      hosts:
        - prometheus.aaa.localhost
      tls: []
    prometheusSpec:
      retention: 6h
      resources:
        requests:
          cpu: "100m"
          memory: "512Mi"
        limits:
          cpu: "500m"
          memory: "1Gi"
      storageSpec:
        volumeClaimTemplate:
          spec:
            storageClassName: local-path
            resources:
              requests:
                storage: 5Gi
      podMonitorSelectorNilUsesHelmValues: false
      serviceMonitorSelectorNilUsesHelmValues: false

# ── Prometheus Pushgateway ─────────────────────────────────────
"prometheus-pushgateway":
  enabled: true
  resources:
    requests:
      cpu: "10m"
      memory: "32Mi"
    limits:
      cpu: "100m"
      memory: "64Mi"

# ── Migration — disabled; run manually with helm install --set aaa-migration.enabled=true
"aaa-migration":
  enabled: false
  staging:
    storageClass: local-path
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "1"
      memory: "2Gi"

# ── Regression tester — disabled; triggered by CI or make test
"aaa-regression-tester":
  enabled: false
  env:
    PROVISION_URL: "http://subscriber-profile-api:8080/v1"
    LOOKUP_URL: "http://aaa-lookup-service:8081/v1"
    PUSHGATEWAY_URL: "http://aaa-platform-prometheus-pushgateway:9091"
```

---

## values-oci.yaml — OCI / OKE Production Overrides

```yaml
# ═══════════════════════════════════════════════════════════════
# values-oci.yaml  —  Oracle Cloud Infrastructure (OKE) overrides
# Applied on top of values.yaml:
#   helm upgrade --install aaa-platform ./charts/aaa-platform \
#     -f values.yaml -f values-oci.yaml -n aaa-platform
# ═══════════════════════════════════════════════════════════════

"aaa-database":
  postgresql:
    storage:
      storageClass: oci-bv              # OCI Block Volume (balanced)
      size: 100Gi

"aaa-lookup-service":
  ingress:
    annotations:
      kubernetes.io/ingress.class: "nginx"
      # OCI Load Balancer shape
      service.beta.kubernetes.io/oci-load-balancer-shape: "flexible"
      service.beta.kubernetes.io/oci-load-balancer-shape-flex-min: "10"
      service.beta.kubernetes.io/oci-load-balancer-shape-flex-max: "100"
  image:
    repository: <region>.ocir.io/<tenancy-namespace>/aaa-lookup-service

"subscriber-profile-api":
  image:
    repository: <region>.ocir.io/<tenancy-namespace>/subscriber-profile-api

"aaa-management-ui":
  image:
    repository: <region>.ocir.io/<tenancy-namespace>/aaa-management-ui

"kube-prometheus-stack":
  prometheus:
    prometheusSpec:
      storageSpec:
        volumeClaimTemplate:
          spec:
            storageClassName: oci-bv
            resources:
              requests:
                storage: 50Gi
  grafana:
    persistence:
      enabled: true
      storageClassName: oci-bv
      size: 10Gi
```

---

## Prerequisites

Install the following tools on WSL2 (Ubuntu 22.04):

```bash
# Docker (via Docker Desktop WSL2 backend, or install in WSL2)
# Verify Docker is available in WSL2:
docker info

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/

# k3d v5.x
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
k3d version

# Helm v3.x
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version

# (Optional) k9s — TUI for Kubernetes
curl -sS https://webinstall.dev/k9s | bash

# (Optional) mkcert — local TLS certificates
sudo apt install libnss3-tools
curl -JLO https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-linux-amd64
chmod +x mkcert-v1.4.4-linux-amd64 && sudo mv mkcert-v1.4.4-linux-amd64 /usr/local/bin/mkcert
mkcert -install
```

---

## k3d Cluster Setup

### `scripts/k3d-up.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="aaa-dev"
REGISTRY_NAME="k3d-aaa-registry.localhost"
REGISTRY_PORT="5111"

echo "── Creating k3d local registry ─────────────────────────────"
k3d registry create aaa-registry.localhost --port ${REGISTRY_PORT} 2>/dev/null || true

echo "── Creating k3d cluster: ${CLUSTER_NAME} ───────────────────"
k3d cluster create ${CLUSTER_NAME} \
  --api-port 6550 \
  --port "80:80@loadbalancer" \
  --port "443:443@loadbalancer" \
  --port "9090:9090@loadbalancer" \
  --registry-use k3d-aaa-registry.localhost:${REGISTRY_PORT} \
  --agents 2 \
  --k3s-arg "--disable=traefik@server:*" \
  --k3s-arg "--disable=servicelb@server:*" \
  --wait

echo "── Merging kubeconfig ──────────────────────────────────────"
k3d kubeconfig merge ${CLUSTER_NAME} --kubeconfig-switch-context

echo "── Verifying cluster ───────────────────────────────────────"
kubectl get nodes

echo "── Installing nginx-ingress (replaces k3s Traefik) ────────"
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx --force-update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.service.type=NodePort \
  --set controller.hostPort.enabled=true \
  --set controller.hostPort.ports.http=80 \
  --set controller.hostPort.ports.https=443 \
  --wait

echo "── Installing CloudNativePG operator ──────────────────────"
helm repo add cnpg https://cloudnative-pg.github.io/charts --force-update
helm upgrade --install cnpg cnpg/cloudnative-pg \
  --namespace cnpg-system --create-namespace \
  --wait

echo "── Cluster ready! ──────────────────────────────────────────"
kubectl get pods -A
```

---

## `/etc/hosts` — Local DNS

Add the following to:
- **WSL2**: `/etc/hosts`
- **Windows host**: `C:\Windows\System32\drivers\etc\hosts`

```
# AAA Platform — k3d dev environment
127.0.0.1  lookup.aaa.localhost
127.0.0.1  provisioning.aaa.localhost
127.0.0.1  ui.aaa.localhost
127.0.0.1  grafana.aaa.localhost
127.0.0.1  prometheus.aaa.localhost
```

Helper script to apply (WSL2 side only):

```bash
# scripts/hosts-update.sh
HOSTS=(
  "lookup.aaa.localhost"
  "provisioning.aaa.localhost"
  "ui.aaa.localhost"
  "grafana.aaa.localhost"
  "prometheus.aaa.localhost"
)
for h in "${HOSTS[@]}"; do
  grep -q "$h" /etc/hosts || echo "127.0.0.1  $h" | sudo tee -a /etc/hosts
done
echo "WSL2 /etc/hosts updated."
echo "NOTE: also add these entries to C:\\Windows\\System32\\drivers\\etc\\hosts on Windows."
```

---

## Image Build & Push Workflow

```bash
# scripts/image-push.sh — build and push all service images to k3d registry
REGISTRY="k3d-aaa-registry.localhost:5111"
TAG="dev"

SERVICES=(
  "aaa-lookup-service"
  "subscriber-profile-api"
  "aaa-management-ui"
  "aaa-regression-tester"
  "aaa-migration"
)

for svc in "${SERVICES[@]}"; do
  echo "── Building $svc ──────────────────────────────────────────"
  docker build -t ${REGISTRY}/${svc}:${TAG} ./${svc}/
  docker push ${REGISTRY}/${svc}:${TAG}
done
echo "All images pushed to k3d registry."
```

---

## Makefile

```makefile
# Makefile — AAA Platform dev automation

CLUSTER     := aaa-dev
NAMESPACE   := aaa-platform
CHART_DIR   := ./charts/aaa-platform
RELEASE     := aaa-platform
REGISTRY    := k3d-aaa-registry.localhost:5111
TAG         := dev

.PHONY: help cluster-up cluster-down registry-up build-all push-all \
        infra bootstrap deploy deploy-migration test port-forward \
        logs status clean

help:                ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS=":.*## "}; {printf "  %-22s %s\n", $$1, $$2}'

# ── Cluster lifecycle ──────────────────────────────────────────
cluster-up:          ## Create k3d cluster + nginx-ingress + cnpg operator
	@bash scripts/k3d-up.sh

cluster-down:        ## Destroy k3d cluster (data lost)
	k3d cluster delete $(CLUSTER)

cluster-status:      ## Show cluster node and pod status
	kubectl get nodes && kubectl get pods -A

# ── Image management ───────────────────────────────────────────
build-all:           ## Build all service Docker images (tag=dev)
	@for svc in aaa-lookup-service subscriber-profile-api aaa-management-ui aaa-regression-tester aaa-migration; do \
	  echo "Building $$svc..."; \
	  docker build -t $(REGISTRY)/$$svc:$(TAG) ./$$svc/; \
	done

push-all:            ## Push all dev images to k3d registry
	@for svc in aaa-lookup-service subscriber-profile-api aaa-management-ui aaa-regression-tester aaa-migration; do \
	  echo "Pushing $$svc..."; \
	  docker push $(REGISTRY)/$$svc:$(TAG); \
	done

# ── Hosts file ─────────────────────────────────────────────────
hosts:               ## Update WSL2 /etc/hosts with .aaa.localhost entries
	@bash scripts/hosts-update.sh

# ── Helm dependency management ─────────────────────────────────
dep-update:          ## Resolve and vendor all sub-chart dependencies
	helm dependency update $(CHART_DIR)

# ── Full dev bootstrap (first time) ───────────────────────────
bootstrap: cluster-up hosts build-all push-all dep-update deploy
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════╗"
	@echo "║  AAA Platform is running on k3d!                        ║"
	@echo "║  UI:          http://ui.aaa.localhost                   ║"
	@echo "║  API:         http://provisioning.aaa.localhost/v1      ║"
	@echo "║  Lookup:      http://lookup.aaa.localhost/health        ║"
	@echo "║  Grafana:     http://grafana.aaa.localhost (dev-grafana)║"
	@echo "║  Prometheus:  http://prometheus.aaa.localhost           ║"
	@echo "╚══════════════════════════════════════════════════════════╝"

# ── Helm deploy ────────────────────────────────────────────────
deploy:              ## Deploy/upgrade umbrella chart with values-dev.yaml
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
	  --namespace $(NAMESPACE) --create-namespace \
	  -f $(CHART_DIR)/values-dev.yaml \
	  --wait --timeout 5m

deploy-dry-run:      ## Dry-run deploy (template rendering + server validation)
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
	  --namespace $(NAMESPACE) --create-namespace \
	  -f $(CHART_DIR)/values-dev.yaml \
	  --dry-run --debug 2>&1 | head -200

# ── One-time jobs ──────────────────────────────────────────────
deploy-migration:    ## Run migration Jobs (Steps 1–3)
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
	  --namespace $(NAMESPACE) \
	  -f $(CHART_DIR)/values-dev.yaml \
	  --set "aaa-migration.enabled=true" \
	  --wait

test:                ## Run regression test suite as a Kubernetes Job
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
	  --namespace $(NAMESPACE) \
	  -f $(CHART_DIR)/values-dev.yaml \
	  --set "aaa-regression-tester.enabled=true" \
	  --wait --timeout 15m
	@echo "Waiting for test Job to complete..."
	kubectl wait --for=condition=complete job/aaa-regression-tester \
	  -n $(NAMESPACE) --timeout=900s
	kubectl logs -n $(NAMESPACE) \
	  $$(kubectl get pods -n $(NAMESPACE) -l app.kubernetes.io/name=aaa-regression-tester \
	     -o jsonpath='{.items[0].metadata.name}')

# ── Observability shortcuts ────────────────────────────────────
port-forward-grafana:   ## Forward Grafana to localhost:3000 (bypass ingress)
	kubectl port-forward -n $(NAMESPACE) \
	  svc/aaa-platform-grafana 3000:80

port-forward-prometheus: ## Forward Prometheus to localhost:9090 (bypass ingress)
	kubectl port-forward -n $(NAMESPACE) \
	  svc/aaa-platform-kube-prometheus-prometheus 9090:9090

port-forward-pgbouncer: ## Forward PgBouncer to localhost:5432 (direct DB access)
	kubectl port-forward -n $(NAMESPACE) \
	  svc/aaa-pgbouncer 5432:5432

# ── Debugging ──────────────────────────────────────────────────
logs:                ## Tail logs from all app pods
	kubectl logs -n $(NAMESPACE) \
	  -l 'app.kubernetes.io/component in (aaa-hotpath,provisioning-api,management-ui)' \
	  --all-containers --prefix --follow

status:              ## Show all pods + services + ingress
	@echo "═══ Pods ═══════════════════════════════════════════════════"
	kubectl get pods -n $(NAMESPACE) -o wide
	@echo "═══ Services ════════════════════════════════════════════════"
	kubectl get svc -n $(NAMESPACE)
	@echo "═══ Ingress ═════════════════════════════════════════════════"
	kubectl get ingress -n $(NAMESPACE)
	@echo "═══ PVCs ════════════════════════════════════════════════════"
	kubectl get pvc -n $(NAMESPACE)

# ── Teardown ───────────────────────────────────────────────────
uninstall:           ## Uninstall Helm release (keeps namespace + PVCs)
	helm uninstall $(RELEASE) -n $(NAMESPACE)

clean: uninstall cluster-down   ## Full teardown: uninstall + delete k3d cluster
```

---

## Bootstrap Sequence — First Time Setup

Run these commands in order in your WSL2 terminal:

```bash
# 0. Clone repo and enter root
git clone https://github.com/example/aaa-cloud-native.git
cd aaa-cloud-native

# 1. Build the cluster, images, and deploy everything
make bootstrap
# ↑ This runs: cluster-up → hosts → build-all → push-all → dep-update → deploy

# 2. Verify all pods are Running
make status

# 3. Open Grafana in browser (Windows)
# Navigate to: http://grafana.aaa.localhost
# Username: admin   Password: dev-grafana

# 4. Run the regression suite
make test
# ↑ Deploys the test Job, waits for completion, streams logs

# 5. Access the Management UI
# Navigate to: http://ui.aaa.localhost
```

**Expected pod list after bootstrap:**
```
NAMESPACE      NAME                                              READY   STATUS
aaa-platform   aaa-postgres-1                                    1/1     Running   ← PostgreSQL primary
aaa-platform   aaa-pgbouncer-xxxxxxx                             2/2     Running   ← PgBouncer + exporter
aaa-platform   aaa-lookup-service-xxxxxxx                        1/1     Running
aaa-platform   subscriber-profile-api-xxxxxxx                    1/1     Running
aaa-platform   aaa-management-ui-xxxxxxx                         2/2     Running   ← Nginx + exporter
aaa-platform   aaa-platform-grafana-xxxxxxx                      3/3     Running
aaa-platform   aaa-platform-kube-prometheus-prometheus-0         2/2     Running
aaa-platform   aaa-platform-kube-state-metrics-xxxxxxx           1/1     Running
aaa-platform   aaa-platform-prometheus-node-exporter-xxxxxxx     1/1     Running
aaa-platform   aaa-platform-prometheus-pushgateway-xxxxxxx       1/1     Running
cnpg-system    cnpg-cloudnative-pg-xxxxxxx                       1/1     Running
ingress-nginx  ingress-nginx-controller-xxxxxxx                  1/1     Running
```

---

## Day-2 Developer Workflow

```bash
# Rebuild + redeploy a single service after code change:
docker build -t k3d-aaa-registry.localhost:5111/aaa-lookup-service:dev ./aaa-lookup-service/
docker push k3d-aaa-registry.localhost:5111/aaa-lookup-service:dev
kubectl rollout restart deployment/aaa-lookup-service -n aaa-platform

# Or redeploy everything (images already pushed):
make deploy

# Check what's running:
make status

# Tail logs for lookup service only:
kubectl logs -n aaa-platform -l app.kubernetes.io/name=aaa-lookup-service -f

# Run just the regression tests:
make test

# Access Grafana without ingress (if DNS not working on Windows):
make port-forward-grafana
# → open http://localhost:3000

# Direct DB access (psql, DBeaver):
make port-forward-pgbouncer
# → connect to localhost:5432 with credentials from aaa-db-credentials-dev secret
```

---

## Grafana Dashboard Provisioning (ConfigMap-based)

In dev, Grafana persistence is disabled but dashboards are provisioned automatically
via ConfigMaps. Each sub-chart's Helm templates include a dashboard ConfigMap:

```yaml
# Example: charts/aaa-lookup-service/templates/grafana-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: aaa-lookup-service-dashboard
  namespace: aaa-platform
  labels:
    grafana_dashboard: "1"    # sidecar label — auto-imported by Grafana
data:
  aaa-lookup-service.json: |
    { ... Grafana dashboard JSON ... }
```

Grafana's sidecar (`sidecar.dashboards.enabled: true`) watches for ConfigMaps with
label `grafana_dashboard: "1"` in the `aaa-platform` namespace and imports them automatically.
Dashboards survive pod restarts but reset on full `make clean` + `make bootstrap`.

---

## Resource Budget Summary (k3d dev — 2 agent nodes)

| Component | CPU req | RAM req | Replicas | Storage |
|---|---|---|---|---|
| PostgreSQL (primary) | 250m | 512Mi | 1 | 5Gi local-path |
| PgBouncer + exporter | 100m | 64Mi | 1 | — |
| aaa-lookup-service | 100m | 128Mi | 1 | — |
| subscriber-profile-api | 250m | 256Mi | 1 | — |
| aaa-management-ui + exporter | 60m | 80Mi | 1 | — |
| Prometheus | 100m | 512Mi | 1 | 5Gi local-path |
| Grafana | 50m | 128Mi | 1 | — (ephemeral) |
| Pushgateway | 10m | 32Mi | 1 | — |
| kube-state-metrics | 10m | 64Mi | 1 | — |
| node-exporter (per node) | 10m | 32Mi | 2 | — |
| ingress-nginx | 100m | 90Mi | 1 | — |
| cnpg-operator | 100m | 256Mi | 1 | — |
| **Total approx** | **~1.1 CPU** | **~2.2 GB** | — | **~10 Gi** |

A WSL2 Docker Desktop instance with **4 CPU / 6 GB RAM** allocated is sufficient.

---

## Differences: dev vs production

| Aspect | k3d (values-dev.yaml) | k8s / OCI (values.yaml / values-oci.yaml) |
|---|---|---|
| PostgreSQL HA | 1 instance (no standby) | 3 instances (1 primary + 2 sync standbys) |
| Replicas | 1 per service | 2–6 per service |
| TLS | Disabled (HTTP) | Enabled (cert-manager + Let's Encrypt or OCI certs) |
| Autoscaling (HPA) | Disabled | Enabled |
| PDB | minAvailable: 0 | minAvailable: 1–2 |
| Storage class | `local-path` | `gp3-encrypted` (k8s) / `oci-bv` (OCI) |
| Image registry | `k3d-aaa-registry.localhost:5111` | ECR / OCIR / private registry |
| Alertmanager | Disabled | Enabled |
| Prometheus retention | 6h | 30d |
| Grafana persistence | Ephemeral (ConfigMap only) | PVC-backed |
| Pod affinity | None | Anti-affinity across AZs |
| DNS | `/etc/hosts` | External DNS or OCI DNS |
