# AAA Lookup Service — Load Test Plan

## Overview

This plan covers performance validation of `aaa-lookup-service` (C++/Drogon, port 8081).
The service must sustain RADIUS hot-path lookups within its SLA under realistic telecom traffic conditions.

**SLA target:** p99 < 15 ms end-to-end latency at sustained load.

---

## Endpoint Under Test

```
GET /v1/lookup?imsi={15-digit-imsi}&apn={apn}
Authorization: Bearer {token}          # skipped when JWT_SKIP_VERIFY=true
```

Expected responses:

| Code | Meaning |
|------|---------|
| 200 | IP resolved — `{"static_ip":"100.64.x.y"}` |
| 400 | Bad IMSI / missing param |
| 401 | Missing/invalid JWT |
| 403 | Subscriber suspended |
| 404 | IMSI not found or APN not matched |
| 503 | DB error |

---

## Test Data — Seed 10,000 Subscribers

Before running any k6 HTTP test, populate the database with test subscribers.
All use `ip_resolution = 'imsi_apn'` so every lookup against APNs `internet`, `mms`, or `ims` returns HTTP 200.

```bash
# Requires DB port-forward active:
#   make port-forward-db  (in a separate terminal)
make load-test-seed
```

Test IMSI range: `001010000000001` – `001010000010000`
Test IP range: `100.64.0.1` – `100.64.39.94` (CGNAT /10)

---

## Traffic Generator

Built on **[Grafana k6](https://k6.io/)** (v0.55+). The container image contains all five test scripts.

### Build locally

```bash
make build-load-tester
```

### Scripts

| Script | Scenario | VU model | Duration | Target RPS |
|--------|----------|----------|----------|-----------|
| `smoke.js` | Basic sanity check | 1 VU | 1 min | ~10 |
| `load.js` | Sustained normal load | Ramping arrival-rate | 14 min | 500 |
| `stress.js` | Find breaking point | Ramping arrival-rate | 25 min | 0 → 2 000 |
| `spike.js` | Sudden traffic burst | Ramping arrival-rate | 5 min 30 s | 50 → 2 000 → 50 → 1 500 → 0 |
| `soak.js` | Memory/leak detection | Constant arrival-rate | 45 min | 300 |

---

## Pass / Fail Criteria

### Smoke
| Metric | Threshold |
|--------|-----------|
| `http_req_failed rate` | < 1 % |
| `server_errors rate` | < 1 % |

> No latency threshold on smoke — `kubectl port-forward` adds 15–60 ms jitter that would always fail the SLA gate. Run `load.js` / `soak.js` in-cluster for latency assertions.

### Load (normal operations gate)
| Metric | Threshold |
|--------|-----------|
| `http_req_duration p(95)` | < 10 ms |
| `http_req_duration p(99)` | < 15 ms |
| `http_req_failed rate` | < 0.5 % |
| `server_errors rate` | < 0.1 % |

### Stress
Relaxed thresholds (goal: observe where degradation occurs, not gate the run):

| Metric | Threshold |
|--------|-----------|
| `http_req_duration p(99)` | < 100 ms |
| `http_req_failed rate` | < 15 % |
| `server_errors rate` | < 5 % |

### Spike
| Metric | Threshold |
|--------|-----------|
| `http_req_failed rate` | < 20 % |
| `server_errors rate` | < 10 % |

### Soak
Same as Load, plus no monotonic growth in Prometheus `aaa_in_flight_requests`.

---

## Running Tests

### Option A — Local (Docker, against port-forwarded service)

```bash
# 1. Forward the service
make port-forward-lookup     # terminal 1

# 2. Build image (first time only)
make build-load-tester

# 3. Seed data (first time only, requires port-forward-db in another terminal)
make load-test-seed

# 4. Run a scenario
make load-test-smoke          # quick sanity
make load-test-load           # full load test
make load-test-stress         # stress / capacity
make load-test-spike          # spike
make load-test-soak           # 45-min soak
```

### Option B — In-cluster Kubernetes Job

```bash
# Create the seed ConfigMap (once)
kubectl create configmap aaa-load-test-seed-sql \
  --from-file=seed_load_test.sql=load-testing/seed/seed_load_test.sql \
  -n aaa-platform

# Apply seed job (runs once, completes)
kubectl apply -f load-testing/k8s/seed-job.yaml -n aaa-platform
kubectl wait --for=condition=complete job/aaa-load-test-seed -n aaa-platform --timeout=120s

# Apply load test job (edit SCRIPT env var to choose scenario)
kubectl apply -f load-testing/k8s/load-test-job.yaml -n aaa-platform
make load-test-logs-k8s
```

### Option C — Makefile shortcut

```bash
make load-test-k8s SCRIPT=load.js
```

---

## Configurable Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TARGET_URL` | `http://localhost:8081` | Base URL of lookup service |
| `BEARER_TOKEN` | `dev-load-test` | JWT (irrelevant when `JWT_SKIP_VERIFY=true`) |
| `IMSI_COUNT` | `10000` | Number of test IMSIs in pool |
| `SCRIPT` | `load.js` | Which k6 script to run (K8s Job) |

---

## Key Prometheus Metrics to Watch

```promql
# Request rate by outcome
rate(aaa_lookup_requests_total[1m])

# p99 latency
histogram_quantile(0.99, rate(aaa_lookup_duration_seconds_bucket[1m]))

# Error rate
rate(aaa_lookup_requests_total{result="db_error"}[1m])

# In-flight requests (saturation)
aaa_in_flight_requests
```

Scrape endpoint: `http://<pod>:9090/metrics`

---

---

## RADIUS Load Test

Tests the full RADIUS hot-path (UDP/1812) at realistic telecom traffic levels,
combining a stepped fast-path load with a constant first-connection background.

### Two concurrent senders

| Sender | Protocol | Rate | IMSI pool | Expected response |
|--------|----------|------|-----------|-------------------|
| Fast-path | RADIUS UDP/1812 | 100 → 200 → 300 RPS (stepped) | 10 K known IMSIs (in `imsi2sim`) | Access-Accept (IP from `imsi_apn_ips`) |
| First-connect | RADIUS UDP/1812 | 2 RPS constant | Sequential new IMSIs (in range, not in `imsi2sim`) | Access-Accept (triggers subscriber-profile-api `/first-connection`) |

### Load tiers (fast-path)

| Tier | Target RPS | Duration | Purpose |
|------|-----------|----------|---------|
| tier-100 | 100 | 5 min | Low baseline |
| tier-200 | 200 | 5 min | Mid baseline |
| tier-300 | 300 | 5 min | Normal ops ceiling |

Total duration: **~15 minutes** (plus first-connect runs throughout).

### Pass criteria

| Path | p99 latency | Error rate |
|------|------------|------------|
| Fast-path | < 20 ms | < 1 % |
| First-connect | < 500 ms | < 2 % |

### Test data

Fast-path seed: provisioned at runtime by `radius_load.py` setup phase via subscriber-profile-api.
IMSI range: `001010000001001` – `001010000011000`, pool `100.64.0.0/16` (`load-test-fastpath`).
The script warms up all 10K subscribers via RADIUS before starting the timed tiers — no manual SQL seed step required.

First-connect provisioning (also done automatically by `radius_load.py` setup):
- New `ip_pools` entry: `100.65.0.0/20` (`load-test-firstconn`) — ~4 094 free IPs
- New `imsi_range_configs` entry covering `001010000011001` – `001010000013600`
- These IMSIs are **not** in `imsi2sim` — each hit triggers a real first-connection

### Prometheus pod metrics

Queried from Prometheus after each tier (`/api/v1/query_range`, step=15s):

```promql
# CPU utilisation per pod (cores)
avg by (pod) (
  rate(container_cpu_usage_seconds_total
    {namespace="aaa-platform",container!="POD",container!=""}[1m])
)

# RAM working-set per pod (bytes → convert to MB in output)
avg by (pod) (
  container_memory_working_set_bytes
    {namespace="aaa-platform",container!="POD",container!=""}
)
```

Pods tracked: `aaa-radius-server-*`, `aaa-lookup-service-*`,
`subscriber-profile-api-*`, `aaa-db-*` (PostgreSQL), `aaa-db-*-pooler-*` (PgBouncer).

### Running the RADIUS load test

The script is self-contained: on first run it creates the pools and range configs via
subscriber-profile-api, then warms up all 10K fast-path subscribers via RADIUS before
starting the timed tiers.  No separate seed step required.

#### Option A — In-cluster Kubernetes Job (recommended)

Note: `kubectl port-forward` does not support UDP, so the RADIUS load test always
runs as an in-cluster K8s Job.

```bash
# Build image (once)
make build-radius-load-tester

# Quick smoke — 30 s per tier (~1.5 min total)
make radius-load-test-smoke

# Full run — 5 min per tier (~15 min total)
make radius-load-test

# Stream logs while running
make radius-load-test-logs-k8s

# Fetch results (before the Job's 10-min TTL expires)
kubectl cp -n aaa-platform \
  $(kubectl get pod -n aaa-platform -l job-name=aaa-radius-load-test \
    -o jsonpath='{.items[0].metadata.name}'):/app/results \
  ./load-test-results
```

### Configurable environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RADIUS_HOST` | `aaa-radius-server` | RADIUS server hostname |
| `RADIUS_PORT` | `1812` | UDP port |
| `RADIUS_SECRET` | `testing123` | Shared secret |
| `API_URL` | `http://aaa-platform-subscriber-profile-api:8080` | subscriber-profile-api base URL (for setup phase) |
| `PROMETHEUS_URL` | `http://aaa-platform-kube-promethe-prometheus.aaa-platform.svc:9090` | Prometheus base URL |
| `IMSI_COUNT` | `10000` | Fast-path IMSI pool size |
| `FIRSTCONN_RPS` | `2` | First-connect rate (RPS) |
| `FIRSTCONN_IMSI_START` | `1010000011001` | First-connect IMSI base (integer) |
| `TIER_DURATION_S` | `300` | Seconds per tier (set to 30 for quick smoke) |

### Output files

| File | Contents |
|------|---------|
| `results/summary.json` | Per-tier latency percentiles + error counts |
| `results/pod-metrics.json` | CPU/RAM avg+max per pod per tier |
| `results/report.md` | Human-readable Markdown tables |

---

## Expected Capacity Estimates

| Replicas | Expected Sustainable RPS | p99 Latency |
|----------|--------------------------|-------------|
| 1 | ~500–800 | < 5 ms |
| 3 (default) | ~1 500–2 400 | < 10 ms |
| 6 (HPA max) | ~3 000–4 800 | < 15 ms |

Breaking point is expected around 2 000–3 000 RPS for a single replica (Drogon async event loop + PgBouncer read-only pool).
