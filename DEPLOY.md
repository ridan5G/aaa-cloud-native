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

## Alerting → Zabbix

Production deployments forward all Prometheus alerts to an **external Zabbix
server** via an in-cluster bridge. The 26 PrometheusRule alerts in
[`charts/aaa-platform/templates/prometheus-rules.yaml`](charts/aaa-platform/templates/prometheus-rules.yaml)
remain the source of truth; Zabbix handles notification, dedup, and
escalation downstream.

### Flow

```
PrometheusRule  ──►  Alertmanager  ──►  aaa-zabbix-bridge (Deployment)
                       (in-cluster)        │  zabbix_sender protocol
                                           ▼  TCP/10051
                                       External Zabbix server
                                           │  trapper item
                                           ▼  prometheus.alert[<AlertName>]
                                       Zabbix triggers / actions
```

The bridge is a small webhook receiver
(`gmauleon/alertmanager-zabbix-webhook`) that translates Alertmanager JSON
payloads into Zabbix trapper protocol packets.

### Step 1 — Create the credentials Secret

Connection coordinates are passed via a Secret (not committed). Set the
hostname and target Zabbix host appropriately:

```bash
kubectl create secret generic aaa-zabbix-bridge-credentials \
  --from-literal=ZABBIX_SERVER_HOST=zabbix.ops.example.com \
  --from-literal=ZABBIX_SERVER_PORT=10051 \
  --from-literal=ZABBIX_TARGET_HOST=aaa-cloud-native-prod \
  -n aaa-platform
```

`ZABBIX_TARGET_HOST` must match the hostname of an existing host entity in
the Zabbix UI — the bridge does not create hosts.

### Step 2 — Create trapper items in Zabbix

For each alertname expected to fire, create a trapper item on the target
host:

| Field | Value |
|---|---|
| Type | Zabbix trapper |
| Key | `prometheus.alert[<AlertName>]` (e.g. `prometheus.alert[PoolExhausted]`) |
| Type of information | Text |
| History storage period | as per site policy (e.g. 31d) |

Define triggers/actions in Zabbix using these items. The 26 alertnames
shipped with this chart are listed in `prometheus-rules.yaml` (groups
`aaa.pool`, `aaa.first_connection`, `aaa.lookup`, `aaa.radius`, `aaa.ui`,
`aaa.postgres`).

### Step 3 — Enable in production

Already enabled by default in [`values.yaml`](charts/aaa-platform/values.yaml):

```yaml
alertmanagerZabbixWebhook:
  enabled: true
```

`make deploy` (with the prod values file) will roll out the bridge
Deployment, Service, and ConfigMap into the release namespace.

### Step 4 — Verify

```bash
# 1. Bridge pod up and reachable
kubectl get deploy aaa-zabbix-bridge -n aaa-platform
kubectl logs -n aaa-platform deploy/aaa-zabbix-bridge -f
#   expect: listening on :10052 ; zabbix server reachable

# 2. Alertmanager has the receiver wired
kubectl port-forward -n aaa-platform svc/alertmanager-operated 9093:9093
#   browse http://localhost:9093 → Status → check the `zabbix` receiver

# 3. Force an alert (easy: scale lookup-service to 0, wait 10m for
#    LookupServiceNoTraffic). Watch the bridge logs and confirm the
#    matching trapper item updates in Zabbix → Latest data.

# 4. Resolve path: scale back up → Alertmanager sends a `resolved`
#    payload (send_resolved: true) → bridge writes the resolved value
#    to the same Zabbix item.
```

### Per-alert host override

To route a specific alert to a non-default Zabbix host, add a
`zabbix_host` annotation to the rule:

```yaml
- alert: PostgresPrimaryDown
  expr: ...
  labels:
    severity: critical
  annotations:
    summary: ...
    zabbix_host: aaa-postgres-prod   # overrides ZABBIX_TARGET_HOST
```

### Disabling

Per-environment override — already disabled in dev/HA. To disable in prod:

```yaml
# values.yaml
alertmanagerZabbixWebhook:
  enabled: false
```

The bridge resources are entirely removed; alerts continue to fire inside
Prometheus but are not forwarded.

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| Bridge pod CrashLoop on start | Config schema mismatch with image revision — drop `--config` arg and rely on `ZABBIX_SERVER`/`HOST_DEFAULT` env vars (both set by the Deployment) |
| Alerts visible in Alertmanager UI but never reach Zabbix | Trapper item not created in Zabbix (key mismatch), or NetworkPolicy blocking egress on TCP/10051 |
| `host_default` errors in bridge logs | Target host string in Secret does not match a host entity in Zabbix — host names are case-sensitive |
| Alerts fire but never resolve in Zabbix | `send_resolved: true` missing on receiver, or trapper item value type can't represent both states — use Text |

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
| `aaa-zabbix-bridge-credentials` | manual `kubectl create secret` (prod only) | `ZABBIX_SERVER_HOST`, `ZABBIX_SERVER_PORT`, `ZABBIX_TARGET_HOST` | `aaa-zabbix-bridge` (Alertmanager → Zabbix forwarder) |

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
