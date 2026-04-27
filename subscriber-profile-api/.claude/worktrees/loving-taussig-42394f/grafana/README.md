# AAA Platform — Grafana Dashboard

## Overview

`aaa-platform-dashboard.json` is the single Grafana dashboard for the AAA cloud-native platform. It provides end-to-end observability across all four services:

| Service | Protocol | Port |
|---|---|---|
| `aaa-radius-server` | UDP | 1812 |
| `aaa-lookup-service` | HTTP | 8081 |
| `subscriber-profile-api` | HTTP | 8080 |
| PostgreSQL / PgBouncer | — | 5432 / 5433 |

**Dashboard UID:** `aaa-platform-v1`  
**Auto-refresh:** 30 s  
**Default time range:** last 1 hour

---

## Dashboard Sections

### Top-of-page KPI strip (always visible)

Four stat panels give an at-a-glance health check:

| Panel | Metric | Green threshold |
|---|---|---|
| RADIUS RPS | `radius_access_requests_total` rate | any |
| Fast Path % | resolved lookups / total lookups | ≥ 99% |
| First Connect % | first-conn triggers / total lookups | < 10% |
| Accept / Request % | accepts / access-requests | ≥ 95% |

Each KPI has a matching **time-series graph** directly below it for trend analysis.

---

### Row 1 — AAA Lookup Service (port 8081)

Monitors the C++/Drogon hot-path lookup service.

| Panel | What it shows |
|---|---|
| Lookup Hit Rate | Stage-1 DB-hit fraction (target ≥ 99%) |
| Lookup p99 Latency | SLA target < 15 ms; alert at 15 ms |
| First-Connection Rate | Stage-2 allocations per second (should be near 0 at steady state) |
| Pool Exhaustion Events | `pool_exhausted_total` over 1 h — any value > 0 is critical |
| Lookup Throughput | `aaa_lookup_requests_total` rate by outcome |
| Lookup Request Rate by Outcome | Breakdown: resolved / not_found / suspended / error |
| Lookup Latency Percentiles | p50 / p95 / p99 histogram from `aaa_lookup_duration_seconds_bucket` |
| Lookup DB Errors (1h) | DB error counter increase |
| Suspended Lookups (1h) | Suspended-subscriber hit rate |
| Pool Exhaustion Events by Pool | Per-pool exhaustion breakdown |

---

### Row 2 — RADIUS Server (UDP 1812)

Monitors `aaa-radius-server`. The architecture note panel explains the single-call flow:

```
Access-Request (IMSI + APN)
  │
  └─▶ GET aaa-lookup-service/lookup?imsi=…&apn=…
        ├─ 200 → Access-Accept (DB hit)              ✅
        ├─ 200 → Access-Accept (first-conn triggered) ✅
        ├─ 404 → Access-Reject (not found)            🚫
        ├─ 403 → Access-Reject (suspended)            🚫
        └─ 503 → Access-Reject (pool exhausted)       🔴
```

| Panel | What it shows |
|---|---|
| RADIUS Accept Rate | Accepts / total requests (target ≥ 95%) |
| RADIUS p99 Latency | End-to-end; alert at 500 ms |
| First-Conn Trigger Rate | FC triggers / RADIUS requests (target < 25%, steady-state ≈ 0%) |
| RADIUS Upstream Errors | Errors from the lookup-service HTTP call (1 h) |
| RADIUS Request Rate by Result | accept / reject / error breakdown |
| RADIUS Request Latency Percentiles | p50 / p95 / p99 |
| First-Connection Outcomes | success / pool_exhausted / not_found breakdown |
| Multi-IMSI Siblings Provisioned Rate | Rate of sibling-slot allocations |
| Suspended vs Not-Found Lookup Rate | Comparison of reject causes |
| Not-Found Ratio (Stage-2 Trigger Rate) | 404 fraction over time |
| RADIUS Upstream Errors (1h) | Counter increase for upstream errors |

---

### Row 3 — Subscriber Profile API (port 8080)

Monitors the Python/FastAPI provisioning API.

| Panel | What it shows |
|---|---|
| In-Flight Requests | Active HTTP connections |
| API Throughput by Method + Path | RPS split by HTTP method and endpoint |
| API Request Latency Percentiles | p50 / p95 / p99 per endpoint |
| Bulk Job Duration Percentiles | Processing time for bulk provisioning jobs |
| Bulk Job Profile Throughput | Profiles written per second during bulk runs |

---

### Row 4 — PostgreSQL / PgBouncer (CloudNativePG)

Monitors the database layer via the built-in CloudNativePG metrics exporter (port 9187).

| Panel | What it shows |
|---|---|
| DB Primary Up | `pg_up` boolean — red if primary is unreachable |
| Active DB Connections | Live connection count via PgBouncer |
| DB Block Cache Hit Ratio | Buffer cache hit %; alert below 95% |
| Transaction Rate | Commits + rollbacks per second |
| Database Size | Growth trend in bytes |
| DB Connection States | `pg_stat_activity` breakdown: idle / active / idle-in-transaction |
| Replication Lag Over Time | Replica lag in seconds |
| Replica Lag (s) | Current lag stat |
| DB Read Replica Error Rate | Errors on replica queries |
| DB Deadlocks & Conflicts | Deadlock and conflict counters |

---

### Row 5 — Management UI (RUM via Pushgateway)

Real-user metrics for `aaa-management-ui` pushed through Prometheus Pushgateway.

| Panel | What it shows |
|---|---|
| UI API Call Rate | Calls per second from the browser |
| UI Avg API Latency | Average round-trip for UI API calls |
| UI API Error Rate (1h) | Client-observed error count |
| UI API Throughput by Endpoint | Per-endpoint call breakdown |
| UI API Avg Latency by Endpoint | Per-endpoint average latency |
| UI API Error Rate by Endpoint | Per-endpoint error rate |

---

## Variables

| Variable | Type | Description |
|---|---|---|
| `datasource` | Data source | Prometheus instance to query |
| `namespace` | Query | K8s namespace filter; populated from `aaa_lookup_requests_total` label |

---

## Importing the Dashboard

### Via Grafana UI

1. Open Grafana → **Dashboards → Import**.
2. Click **Upload JSON file** and select `aaa-platform-dashboard.json`.
3. Select your Prometheus data source when prompted.
4. Click **Import**.

### Via Helm (recommended for production)

The umbrella chart at `charts/aaa-platform` can provision the dashboard as a ConfigMap that Grafana's sidecar picks up automatically. See `charts/aaa-platform/values.yaml` for the `grafana.dashboards` key.

### Via kubectl (quick dev import)

```bash
kubectl create configmap aaa-grafana-dashboard \
  --from-file=aaa-platform-dashboard.json \
  -n monitoring \
  --dry-run=client -o yaml | kubectl apply -f -
```

The ConfigMap must carry the label `grafana_dashboard: "1"` (or whatever label your Grafana sidecar watches).

---

## SLA Targets

| Signal | Target | Alert |
|---|---|---|
| Lookup p99 latency | < 10 ms | ≥ 15 ms |
| RADIUS p99 latency | < 250 ms | ≥ 500 ms |
| Lookup fast-path hit rate | ≥ 99% | < 90% |
| RADIUS accept rate | ≥ 95% | < 90% |
| First-connect trigger rate | < 10% (steady state ≈ 0%) | ≥ 25% |
| Pool exhaustion events | 0 | any (critical) |

---

## Key Prometheus Metrics

| Metric | Source | Description |
|---|---|---|
| `aaa_lookup_requests_total` | lookup service | Total lookups, labelled by `result` |
| `aaa_lookup_duration_seconds_bucket` | lookup service | Lookup latency histogram |
| `first_connection_requests_total` | lookup service | Stage-2 allocation triggers |
| `first_connection_total` | lookup service | Alias counter for first-connection events |
| `pool_exhausted_total` | lookup service | IP pool exhaustion events |
| `radius_access_requests_total` | radius server | Incoming Access-Requests |
| `radius_responses_total` | radius server | Responses labelled by `result` |
| `radius_requests_total` | radius server | All RADIUS requests |
| `radius_request_duration_ms_bucket` | radius server | End-to-end RADIUS latency histogram |
| `pg_up` | CloudNativePG exporter | Primary availability (0/1) |
