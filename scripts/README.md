# scripts/

Developer and operations scripts for the AAA cloud-native platform.

---

## Shell scripts

### `k3d-up.sh`
Creates the local k3d development cluster (`aaa-dev`) with a local registry.

- Creates the `k3d-aaa-registry.localhost:5111` image registry
- Spins up a 2-agent k3d cluster with port mappings for HTTP (80), HTTPS (443), RADIUS UDP (1812), and Prometheus (9090/9091)
- Installs nginx-ingress (replaces k3s default Traefik)
- Installs the CloudNativePG operator

```bash
bash scripts/k3d-up.sh
```

---

### `image-push.sh`
Builds and pushes all service images to the k3d local registry.

**Services pushed:** `aaa-lookup-service`, `subscriber-profile-api`, `aaa-management-ui`, `aaa-radius-server`, `aaa-regression-tester`

```bash
bash scripts/image-push.sh          # tag: dev (default)
bash scripts/image-push.sh v1.2.3   # custom tag
```

---

### `db-init.sh`
Applies the AAA database schema and grants to the CloudNativePG primary pod.

- Called automatically by `make setup` and `make bootstrap`
- Idempotent — safe to re-run on any existing cluster
- Runs incremental schema migrations (Gen-1 through Gen-6) covering table renames, column additions, FK changes, and constraint updates
- Applies the full schema SQL from the `aaa-postgres-initdb-sql` ConfigMap
- Sets default privileges for the `aaa_app` database user

```bash
bash scripts/db-init.sh

# Override defaults:
NAMESPACE=my-ns CONFIGMAP=my-cm DB_NAME=mydb bash scripts/db-init.sh
```

---

### `hosts-update.sh`
Adds the AAA platform local DNS entries to WSL2 `/etc/hosts`.

Adds entries for:
- `lookup.aaa.localhost`
- `provisioning.aaa.localhost`
- `ui.aaa.localhost`
- `grafana.aaa.localhost`
- `prometheus.aaa.localhost`

Also prints the equivalent lines to add to `C:\Windows\System32\drivers\etc\hosts` on the Windows host.

```bash
bash scripts/hosts-update.sh
```

---

### `audit-cluster-vs-charts.sh`
Compares the live Kubernetes cluster state against the Helm chart sources and reports drift.

Checks:
1. RADIUS Deployment — env vars, container ports, pod annotations
2. RADIUS Service — metrics port
3. RADIUS ServiceMonitor — labels, endpoint config, Helm ownership
4. Management UI ConfigMap — `pushgatewayUrl` in `config.js`
5. Pushgateway Ingress — host and ingress class
6. Subchart `.tgz` freshness — detects stale packaged charts vs source
7. Grafana Dashboard ConfigMap — version and section order match source JSON

```bash
bash scripts/audit-cluster-vs-charts.sh              # full audit
bash scripts/audit-cluster-vs-charts.sh --fix        # also print kubectl remediation commands
bash scripts/audit-cluster-vs-charts.sh --section radius  # single section only
```

Exits with code 1 if any check fails, 0 on pass (warnings are non-fatal).

---

### `pcap-get.sh`
Copies a pcap capture file from a Kubernetes PVC to a local file.

Spins up a temporary `alpine` pod that mounts the PVC, runs `kubectl cp`, then cleans up. Works even after the source Job/pod has exited.

```bash
# Basic usage (copies test.pcap from PVC):
bash scripts/pcap-get.sh <namespace> <pvc-name>

# Full usage:
bash scripts/pcap-get.sh <namespace> <pvc-name> [output-file] [source-filename]

# Examples:
bash scripts/pcap-get.sh aaa-platform aaa-regression-tester-pcap ./test.pcap test.pcap
bash scripts/pcap-get.sh aaa-platform aaa-radius-pcap ./radius.pcap radius.pcap
```

Requires the test to have been run with `make test PCAP=true`.

---

## Python scripts

### `push-dashboard-cm.py`
Pushes the Grafana dashboard JSON to the live Kubernetes ConfigMap.

Reads `charts/aaa-platform/files/aaa-platform-dashboard.json` and applies it to the `aaa-platform-grafana-aaa-dashboard` ConfigMap. Called by `audit-cluster-vs-charts.sh --fix` when dashboard drift is detected.

```bash
python3 scripts/push-dashboard-cm.py

# Override namespace:
NAMESPACE=my-ns python3 scripts/push-dashboard-cm.py
```

---

### `update_dashboard.py`
One-time script that was used to extend `aaa-platform-dashboard.json` with additional Grafana panels (lookup KPI stats, suspended subscriber time-series, PostgreSQL/PgBouncer section). Not intended for regular use — kept for reference.
