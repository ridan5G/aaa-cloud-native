# AAA Platform — Deployment Guide

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| `kubectl` | 1.28+ | Configured for your target cluster |
| `helm` | 3.12+ | |
| `docker` | 24+ | For building images |

Your cluster needs:
- A working **StorageClass** for PostgreSQL PVCs (e.g. `standard`, `local-path`, `gp3`)
- A **container registry** reachable from cluster nodes

---

## Step 1 — Install CloudNativePG operator

Run **once** per cluster. Manages PostgreSQL and PgBouncer CRDs.

```bash
make cnpg-install
```

Verify:
```bash
kubectl get pods -n cnpg-system
# cnpg-cloudnative-pg-xxx   1/1   Running
```

---

## Step 2 — Build and push your images

```bash
make build-push REGISTRY=your.registry.io/aaa TAG=dev
```

Or per-service:
```bash
docker build -t your.registry.io/aaa/aaa-lookup-service:dev     ./aaa-lookup-service/
docker build -t your.registry.io/aaa/subscriber-profile-api:dev ./subscriber-profile-api/
docker build -t your.registry.io/aaa/aaa-regression-tester:dev  ./aaa-regression-tester/

docker push your.registry.io/aaa/aaa-lookup-service:dev
docker push your.registry.io/aaa/subscriber-profile-api:dev
docker push your.registry.io/aaa/aaa-regression-tester:dev
```

---

## Step 3 — Configure values-dev.yaml

Edit `charts/aaa-platform/values-dev.yaml`. Set the image repositories:

```yaml
aaa-lookup-service:
  image:
    repository: your.registry.io/aaa/aaa-lookup-service

subscriber-profile-api:
  image:
    repository: your.registry.io/aaa/subscriber-profile-api

aaa-regression-tester:
  image:
    repository: your.registry.io/aaa/aaa-regression-tester
```

If your cluster's default StorageClass is not `standard`, update:
```yaml
aaa-database:
  postgresql:
    storage:
      storageClass: your-storage-class   # local-path (k3d), gp3 (EKS), oci-bv (OCI)
```

---

## Step 4 — Resolve Helm sub-chart dependencies

```bash
make dep-update
```

Generates `charts/aaa-platform/Chart.lock`. Re-run whenever `Chart.yaml` dependencies change.

---

## Step 5 — Deploy

```bash
make deploy
```

This runs:
```bash
helm upgrade --install aaa-platform ./charts/aaa-platform \
  --namespace aaa-platform --create-namespace \
  -f ./charts/aaa-platform/values-dev.yaml \
  --wait --timeout 10m
```

### Verify deployment

```bash
make status
```

Expected pods (dev — single replicas):
```
NAME                                  READY   STATUS
aaa-postgres-1                        1/1     Running   ← PostgreSQL primary
aaa-postgres-pooler-rw-xxx            1/1     Running   ← PgBouncer RW (writes)
aaa-postgres-pooler-ro-xxx            1/1     Running   ← PgBouncer RO (reads)
aaa-lookup-service-xxx                1/1     Running
subscriber-profile-api-xxx            1/1     Running
```

CNPG cluster should show:
```
NAME           INSTANCES   READY   STATUS
aaa-postgres   1           1       Cluster in healthy state
```

---

## Step 6 — Smoke test

```bash
# Port-forward the provisioning API
make port-forward-api   # → http://localhost:8080

# Create a test pool
curl -X POST http://localhost:8080/v1/pools \
  -H "Content-Type: application/json" \
  -d '{"pool_name":"test-pool","account_name":"test","subnet":"100.65.120.0/24","start_ip":"100.65.120.1","end_ip":"100.65.120.254"}'

# Port-forward the lookup service
make port-forward-lookup  # → http://localhost:8081

# Health check
curl http://localhost:8081/health
curl http://localhost:8081/health/db
```

---

## Run the full regression suite

```bash
make test
```

This:
1. Creates the `aaa-test-jwt` secret (`token=dev-skip-verify`)
2. Enables `aaa-regression-tester` Job via `--set`
3. Waits up to 15 minutes for completion
4. Streams pytest output to terminal

Retrieve JUnit XML results after the Job completes:
```bash
POD=$(kubectl get pods -n aaa-platform \
  -l app.kubernetes.io/name=aaa-regression-tester \
  -o jsonpath='{.items[0].metadata.name}')
kubectl cp aaa-platform/$POD:/app/results ./results
```

---

## Day-2 operations

### Redeploy a single service after a code change

```bash
docker build -t your.registry.io/aaa/aaa-lookup-service:dev ./aaa-lookup-service/
docker push your.registry.io/aaa/aaa-lookup-service:dev
kubectl rollout restart deployment/aaa-lookup-service -n aaa-platform
```

### Re-deploy everything (images already pushed)

```bash
make deploy
```

### Validate chart rendering without deploying

```bash
make deploy-dry-run
```

### Port-forward for local access

```bash
make port-forward-lookup   # lookup API   → localhost:8081
make port-forward-api      # provision API → localhost:8080
make port-forward-db       # PostgreSQL    → localhost:5432 (psql / DBeaver)
```

Connect to DB directly:
```bash
psql "postgres://aaa_app:devpassword@localhost:5432/aaa"
```

### View logs

```bash
make logs-lookup    # tail aaa-lookup-service
make logs-api       # tail subscriber-profile-api
```

### Uninstall

```bash
make uninstall
# PostgreSQL PVCs are retained. Delete if you want a clean slate:
kubectl delete pvc -n aaa-platform --all
```

---

## Secrets reference

| Secret | Created by | Keys | Consumed by |
|---|---|---|---|
| `aaa-db-credentials` | `aaa-database` chart | `username`, `password`, `database`, `host-rw`, `host-ro`, `port`, `uri-rw`, `uri-ro` | `aaa-lookup-service`, `subscriber-profile-api` |
| `aaa-test-jwt` | `make test-secret` | `token` | `aaa-regression-tester` |
| `aaa-postgres-app` | CloudNativePG (auto-generated) | `uri`, `host`, `port`, `user`, `password` | internal |

---

## Environment differences

| Setting | Dev (`values-dev.yaml`) | Prod (`values.yaml`) |
|---|---|---|
| PostgreSQL instances | 1 | 3 (1 primary + 2 sync standbys) |
| PgBouncer replicas | 1 per pool | 2 per pool |
| App replicas | 1 | 2–3 |
| HPA | disabled | enabled |
| PDB `minAvailable` | 0 | 1–2 |
| JWT verify | skipped (`JWT_SKIP_VERIFY=true`) | enforced |
| DB password | `devpassword` (plaintext in values) | external secret / Vault |
| StorageClass | `standard` | cluster-specific |
| Sync replication | none (single instance) | 1 sync standby |
