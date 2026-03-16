# AAA Platform — Installation Guide

> **Environment:** Docker Desktop + WSL2 (Windows)
> **Last verified:** March 2026

---

## Prerequisites

Install the following tools before proceeding. All commands run inside **WSL2**.

| Tool | Minimum Version | Install |
|---|---|---|
| Docker Desktop | 24+ | [docs.docker.com](https://docs.docker.com/desktop/install/windows-install/) — enable Kubernetes in Settings |
| kubectl | 1.28+ | Bundled with Docker Desktop |
| helm | 3.12+ | `curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 \| bash` |

> **Important:** All `make` commands must be run from **WSL**, not PowerShell.
> Use `wsl make <target>` from PowerShell, or open a WSL terminal and `cd` to the repo root.

---

## Repository Layout

```
aaa-cloud-native/
├── charts/aaa-platform/          # Umbrella Helm chart
│   ├── Chart.yaml                # Sub-chart dependencies
│   └── values-dev.yaml           # Docker Desktop dev overrides
├── scripts/
│   ├── k3d-up.sh                 # k3d cluster bootstrap (k3d only)
│   ├── image-push.sh             # Build + push to k3d registry (k3d only)
│   └── hosts-update.sh           # Add *.aaa.localhost to /etc/hosts
├── aaa-lookup-service/           # C++/Drogon AAA hot-path (port 8081)
├── subscriber-profile-api/       # Python/FastAPI provisioning API (port 8080)
├── aaa-management-ui/            # React management console
├── aaa-radius-server/            # RADIUS authentication server (UDP 1812)
└── aaa-regression-tester/        # pytest regression suite
```

---

## First-Time Setup — Docker Desktop

### Step 1 — Enable Kubernetes in Docker Desktop

Open Docker Desktop → Settings → Kubernetes → **Enable Kubernetes** → Apply & Restart.

Verify:
```bash
kubectl get nodes
# NAME             STATUS   ROLES           AGE
# docker-desktop   Ready    control-plane   ...
```

### Step 2 — Run the full setup

From the repo root in WSL:

```bash
wsl make setup
```

This single command runs the full chain:

| Step | What it does |
|---|---|
| `cnpg-install` | Installs CloudNativePG operator (manages PostgreSQL) |
| `nginx-install` | Installs nginx-ingress controller (routes `*.aaa.localhost`) |
| `hosts` | Adds `*.aaa.localhost` entries to WSL2 `/etc/hosts` |
| `build-all` | Builds all 5 service Docker images locally (`aaa/*:dev`) |
| `dep-update` | Downloads and vendors Helm sub-chart dependencies |
| `prom-crds` | Installs Prometheus Operator CRDs from the cached chart tarball |
| `deploy` | `helm upgrade --install` the umbrella chart with `values-dev.yaml` |

> **Note:** `setup` takes ~10–15 minutes on first run (Prometheus/Grafana images are large).
> Watch progress in a second terminal: `kubectl get pods -n aaa-platform -w`

### Step 3 — Configure Windows hosts file (one-time)

The `hosts` target updates WSL2 `/etc/hosts` automatically.
For the browser on Windows, you must also add these lines to
`C:\Windows\System32\drivers\etc\hosts` (run Notepad as Administrator):

```
127.0.0.1  lookup.aaa.localhost
127.0.0.1  provisioning.aaa.localhost
127.0.0.1  ui.aaa.localhost
127.0.0.1  grafana.aaa.localhost
127.0.0.1  prometheus.aaa.localhost
```

---

## Service URLs (after deploy)

| Service | URL | Notes |
|---|---|---|
| Management UI | http://ui.aaa.localhost | React dashboard |
| Provisioning API | http://provisioning.aaa.localhost/v1 | REST API |
| AAA Lookup | http://lookup.aaa.localhost/health | Health check |
| Grafana | http://grafana.aaa.localhost | admin / `dev-grafana` |
| Prometheus | http://prometheus.aaa.localhost | Metrics explorer |
| RADIUS | `localhost:1812` (UDP) | Secret: `testing123` |
| Pushgateway | `localhost:9091` | Test metrics sink |

> Services are also accessible without ingress via port-forward (see below).

---

## Day-to-Day Commands

All commands must be run from the **repo root** in WSL.

### Build & deploy after code changes

```bash
# Rebuild all images and redeploy
wsl make build-all
wsl make deploy

# Rebuild a single service (example: UI)
docker build -t aaa/aaa-management-ui:dev ./aaa-management-ui/
wsl make deploy
```

### Check status

```bash
wsl make status
# Shows pods, services, ingresses, PVCs, CNPG cluster health, and jobs
```

### Tail logs

```bash
wsl make logs              # all app pods
wsl make logs-api          # subscriber-profile-api only
wsl make logs-lookup       # aaa-lookup-service only
wsl make logs-ui           # aaa-management-ui only
```

### Port-forwarding (bypass ingress)

```bash
wsl make port-forward-api          # localhost:8080
wsl make port-forward-lookup       # localhost:8081
wsl make port-forward-db           # localhost:5432  (PgBouncer RW)
wsl make port-forward-ui           # localhost:8090
wsl make port-forward-grafana      # localhost:3000
wsl make port-forward-prometheus   # localhost:9090
```

Connect to the database directly:
```bash
wsl make port-forward-db &
psql "postgres://aaa_app:devpassword@localhost:5432/aaa"
```

### Run regression tests

The regression tester is a **Kubernetes Job** (not a long-running service). It is kept `enabled: false` in `values-dev.yaml` and activated transiently by `make test`, which re-enables it, waits for completion, prints results, and leaves it to auto-delete after 1 hour.

#### Prerequisites

All platform services must be running before starting tests:

```bash
wsl make status
# All pods in aaa-platform namespace should show Running/Completed
```

If coming from a fresh deploy, create secrets and deploy first:

```bash
wsl make deploy          # apply any pending config changes
wsl make radius-secret   # create aaa-radius-secret (idempotent, safe to re-run)
```

#### Run

```bash
wsl make test
```

`make test` performs the full sequence automatically:

| Step | What it does |
|---|---|
| `test-secret` | Creates `aaa-test-jwt` K8s Secret with `token=dev-skip-verify` |
| `radius-secret` | Creates `aaa-radius-secret` K8s Secret with `radius-secret=testing123` |
| `helm upgrade` | Enables `aaa-regression-tester` Job via `--set aaa-regression-tester.enabled=true` |
| `kubectl wait pod` | Waits up to 2 min for the tester Pod to reach `Ready` state |
| `kubectl wait job` | Blocks until the Job completes or fails (max 15 min) |
| `kubectl logs` | Prints the full pytest output to your terminal |

#### Watch progress in real time

Open a second terminal while `make test` is running:

```bash
# Watch the pod appear and transition to Running → Completed
kubectl get pods -n aaa-platform -w -l app.kubernetes.io/name=aaa-regression-tester

# Stream live pytest output
kubectl logs -n aaa-platform -l app.kubernetes.io/name=aaa-regression-tester -f
```

#### Inspect the pod's environment

To verify which URLs and secrets the tester received:

```bash
# Get the pod name
kubectl get pods -n aaa-platform -l app.kubernetes.io/name=aaa-regression-tester

# Print all env vars injected into the pod
kubectl exec -n aaa-platform <pod-name> -- env | sort

# Or as a one-liner
kubectl exec -n aaa-platform \
  $(kubectl get pod -n aaa-platform -l app.kubernetes.io/name=aaa-regression-tester \
    -o jsonpath='{.items[0].metadata.name}') \
  -- env | grep -E 'URL|JWT|RADIUS|PUSH'
```

Expected output:
```
LOOKUP_URL=http://aaa-platform-aaa-lookup-service:8081/v1
PROVISION_URL=http://aaa-platform-subscriber-profile-api:8080/v1
PUSHGATEWAY_URL=http://aaa-platform-prometheus-pushgateway:9091
RADIUS_HOST=aaa-platform-aaa-radius-server
RADIUS_PORT=1812
RADIUS_SECRET=testing123
TEST_JWT=dev-skip-verify
```

#### In-cluster service names (important)

The tester pod runs **inside** the cluster, so it must reach services via their in-cluster DNS names — not `localhost`:

| Variable | In-cluster value |
|---|---|
| `PROVISION_URL` | `http://aaa-platform-subscriber-profile-api:8080/v1` |
| `LOOKUP_URL` | `http://aaa-platform-aaa-lookup-service:8081/v1` |
| `PUSHGATEWAY_URL` | `http://aaa-platform-prometheus-pushgateway:9091` |
| `RADIUS_HOST` | `aaa-platform-aaa-radius-server` |

#### After the run

The Job and Pod auto-delete 1 hour after completion (`ttlSecondsAfterFinished: 3600`).
To retrieve logs before that:

```bash
kubectl logs -n aaa-platform \
  $(kubectl get pod -n aaa-platform -l app.kubernetes.io/name=aaa-regression-tester \
    -o jsonpath='{.items[0].metadata.name}')
```

To re-run tests, call `wsl make test` again — it creates a fresh Job each time.

> Both secrets are idempotent (`--dry-run=client | kubectl apply`) — safe to run multiple times.

---

## Troubleshooting

### `make` not found in PowerShell

`make` only exists inside WSL. Always prefix with `wsl`:
```powershell
wsl make deploy
```

### `another operation (install/upgrade/rollback) is in progress`

A previous `helm upgrade` was interrupted (e.g. Ctrl+C). Clear the lock:
```bash
wsl make helm-unlock
wsl make deploy
```

### `ErrImageNeverPull`

The Docker image for that service hasn't been built yet.
`pullPolicy: Never` means Kubernetes will only use locally built images.

```bash
# Rebuild all images
wsl make build-all

# Or rebuild just the failing service (example: management UI)
docker build -t aaa/aaa-management-ui:dev ./aaa-management-ui/
```

### `no matches for kind "Prometheus" in version "monitoring.coreos.com/v1"`

Prometheus Operator CRDs are not installed. Run:
```bash
wsl make dep-update     # fetches chart tarballs (if not already done)
wsl make prom-crds      # extracts and installs CRDs
wsl make deploy
```

### TypeScript build error in `aaa-management-ui`

Run the build locally to see the error:
```bash
cd aaa-management-ui && npm ci && npm run build
```
Fix the TypeScript error, then rebuild the Docker image.

### Grafana `CrashLoopBackOff` — duplicate default datasource

Caused by having `isDefault: true` in `additionalDataSources` while
`kube-prometheus-stack` already auto-configures a default Prometheus datasource.
Remove any `additionalDataSources` block from `values-dev.yaml` and redeploy.

### Prometheus node-exporter `CrashLoopBackOff`

Docker Desktop restricts access to `/proc` and `/sys` host paths.
Keep `nodeExporter.enabled: false` in `values-dev.yaml` (already set).

### Ingresses have no ADDRESS

nginx-ingress controller is not installed. Run:
```bash
wsl make nginx-install
```

### Regression tester pod never starts (`Pending` or `ErrImageNeverPull`)

The `aaa/aaa-regression-tester:dev` image hasn't been built locally:
```bash
docker build -t aaa/aaa-regression-tester:dev ./aaa-regression-tester/
wsl make test
```

### Regression tester Job fails immediately (`BackoffLimitExceeded`)

The Job has `backoffLimit: 0` — one failure = done. Check what went wrong:
```bash
# Get the pod name (even completed/failed pods are listed)
kubectl get pods -n aaa-platform -l app.kubernetes.io/name=aaa-regression-tester

# Read the full output
kubectl logs -n aaa-platform <pod-name>
```

Common causes:
- A service is not reachable — verify `wsl make status` shows all pods `Running`
- Wrong secret value — delete and recreate: `kubectl delete secret aaa-radius-secret -n aaa-platform && wsl make radius-secret`

### Regression tester can't reach RADIUS (`Connection refused` in test_12)

Verify the RADIUS server pod is running and the secret matches:
```bash
kubectl get pod -n aaa-platform -l app.kubernetes.io/name=aaa-radius-server
kubectl get secret aaa-radius-secret -n aaa-platform -o jsonpath='{.data.radius-secret}' | base64 -d
# Should print: testing123
```

The secret value must match `radiusSecret.value` in `values-dev.yaml` (default: `testing123`).

---

## Teardown

```bash
# Remove Helm release only (keeps namespace and Postgres PVCs)
wsl make uninstall

# Full teardown including cluster (k3d only — Docker Desktop cluster is managed by Docker Desktop)
wsl make clean
```

To fully reset on Docker Desktop:
1. `wsl make uninstall` — removes the Helm release
2. Docker Desktop → Settings → Kubernetes → **Reset Kubernetes Cluster**

---

## k3d Alternative (CI / Linux)

If running on Linux or in CI without Docker Desktop, use k3d instead:

```bash
# Install k3d
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash

# Full bootstrap (creates cluster, pushes images to local registry, deploys)
make bootstrap REGISTRY=k3d-aaa-registry.localhost:5111
```

The `bootstrap` target calls `scripts/k3d-up.sh` which:
- Creates a local k3d registry on port 5111
- Creates a 2-agent k3d cluster with ports 80/443/9090/9091 and 1812/udp
- Installs nginx-ingress and CloudNativePG operator
- Merges the kubeconfig

---

## Environment Variables Reference

Key variables in `values-dev.yaml` and `.env.example`:

| Variable | Default | Description |
|---|---|---|
| `REGISTRY` | `aaa` | Image registry prefix (`make build-all REGISTRY=...`) |
| `TAG` | `dev` | Image tag (`make build-all TAG=v1.2`) |
| `DB_PASSWORD` | `devpassword` | PostgreSQL app password |
| `JWT_SKIP_VERIFY` | `true` | Bypass JWT auth in dev |
| `RADIUS_SECRET` | `testing123` | RADIUS shared secret |
| `BULK_WORKER_THREADS` | `2` | Bulk job parallelism |
| `BULK_BATCH_SIZE` | `500` | Bulk job batch size |
