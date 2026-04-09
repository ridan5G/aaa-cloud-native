# Helm Charts

This directory contains all Helm charts for the AAA Cloud-Native platform.

## Structure

```
charts/
├── aaa-platform/           # Umbrella chart — deploys the full stack
├── aaa-database/           # PostgreSQL 15 cluster (CloudNativePG + PgBouncer)
├── aaa-lookup-service/     # C++ hot-path RADIUS lookup service
├── aaa-radius-server/      # C++ RADIUS authentication server (UDP/1812)
├── subscriber-profile-api/ # Python/FastAPI provisioning REST API
├── aaa-management-ui/      # Web UI for subscriber management
├── aaa-regression-tester/  # Regression test Job (run manually or via CI)
└── aaa-radius-load-test/   # RADIUS load test Job
```

## Quick Start

Build all service images, then deploy the full stack locally:

```bash
# 1. Build C++ vcpkg base images (once, or when vcpkg.json changes)
make build-cpp-bases REGISTRY=aaa

# 2. Build all service images
make build-all REGISTRY=aaa TAG=dev

# 3. Deploy to Kubernetes
make deploy
# equivalent to:
helm upgrade --install aaa-platform ./charts/aaa-platform \
  -f ./charts/aaa-platform/values-dev.yaml \
  -n aaa-platform --create-namespace
```

> **Note:** `REGISTRY` and `TAG` default to `aaa` and `dev` respectively.
> The `build-cpp-bases` step only needs to be re-run when `vcpkg.json` changes.

To tear down the full stack:

```bash
make uninstall   # Helm uninstall + delete CNPG cluster and PVCs (full DB wipe)
make clean       # uninstall + delete the k3d cluster entirely
```

## Charts

### `aaa-platform` — Umbrella Chart

Declares all sub-charts as local dependencies. A single `helm upgrade --install`
with the right values file brings up the complete stack.

**Value files:**

| File             | Purpose                                      |
|------------------|----------------------------------------------|
| `values.yaml`    | Production defaults (all services enabled)   |
| `values-dev.yaml`| Local dev overrides (single replicas, no TLS, `hostpath` storage) |
| `values-ha.yaml` | HA production overrides                      |

**External chart dependencies** (fetched from Artifact Hub):
- `kube-prometheus-stack` — Prometheus + Grafana + Alertmanager
- `prometheus-pushgateway` — metrics push endpoint for batch jobs

### `aaa-database`

CloudNativePG-managed PostgreSQL 15 cluster with PgBouncer connection pooling.
Bootstraps the full AAA schema on first startup via `postInitApplicationSQLRefs`.

- Prod: 3 PostgreSQL instances + 2 RW + 2 RO PgBouncer poolers
- Dev: 1 instance, RO pooler disabled, `hostpath` storage class

### `aaa-lookup-service`

High-performance C++/Drogon AAA lookup. Serves `GET /v1/lookup?imsi=&apn=`.
Connects to the read-only PgBouncer pooler only. Target SLA: p99 < 15 ms.

### `aaa-radius-server`

C++ RADIUS authentication server on UDP/1812. Two-stage AAA flow:
1. `GET /lookup?imsi=&apn=` → `aaa-lookup-service`
2. `POST /v1/first-connection` → `subscriber-profile-api` (on 404)

Returns `Access-Accept` with `Framed-IP-Address` or `Access-Reject`.

### `subscriber-profile-api`

Python/FastAPI provisioning API on port 8080. Manages subscribers, IP pools,
range configs, and bulk import jobs. Exposes Prometheus metrics on port 9091.

Dev ingress: `http://provisioning.aaa.localhost`

### `aaa-management-ui`

React web UI for subscriber management. Proxies API calls to `subscriber-profile-api`.

Dev ingress: `http://ui.aaa.localhost`

### `aaa-regression-tester`

Kubernetes Job that runs the pytest regression suite against a live cluster.
Disabled by default — enabled transiently by `make test`.

### `aaa-radius-load-test`

Kubernetes Job for RADIUS load testing. Run manually.

## Key Values

| Key | Description | Dev default |
|-----|-------------|-------------|
| `aaa-database.postgresql.appPassword` | DB password (**required** in prod) | `devpassword` |
| `aaa-lookup-service.jwt.skipVerify` | Bypass JWT auth | `"true"` |
| `subscriber-profile-api.jwt.skipVerify` | Bypass JWT auth | `"true"` |
| `kube-prometheus-stack.grafana.adminPassword` | Grafana admin password | `"dev-grafana"` |
| `aaa-regression-tester.enabled` | Enable regression test Job | `false` |

## Dev Ingress Hosts

Add to `/etc/hosts` (or Windows `hosts` file):

```
127.0.0.1  provisioning.aaa.localhost
127.0.0.1  ui.aaa.localhost
127.0.0.1  grafana.aaa.localhost
127.0.0.1  prometheus.aaa.localhost
127.0.0.1  pushgateway.aaa.localhost
```

## Prerequisites

- Kubernetes cluster (Docker Desktop recommended for local dev)
- [CloudNativePG operator](https://cloudnative-pg.io/) installed
- [NGINX Ingress Controller](https://kubernetes.github.io/ingress-nginx/) installed
- Helm 3.x

See [DEPLOY.md](../DEPLOY.md) for full setup instructions.
