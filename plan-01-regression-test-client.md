# Plan 1 — Regression Test Client

## Overview

A standalone test suite (`aaa-regression-tester`) that exercises every REST API endpoint
across both services and verifies correct behaviour for all three production profiles,
dynamic first-connection allocation, bulk operations, and failure scenarios.

**Technology:** Python 3.11+ with `pytest` + `httpx` (async-capable, no requests)
**Target environments:**
- Local: Docker Compose (PostgreSQL 15 + both app containers)
- CI: GitHub Actions / GitLab CI — runs against staging before every merge
**Output:** JUnit XML report + console pass/fail summary + timing CSV for p99 assertions

---

## Repository Layout

```
aaa-regression-tester/
├── conftest.py               # base URLs, JWT token fixture, shared helpers
├── fixtures/
│   ├── pools.py              # create/teardown ip_pools
│   ├── range_configs.py      # create/teardown imsi_range_configs
│   └── profiles.py           # create/teardown sim_profiles
├── test_01_pools.py          # IP pool CRUD + stats
├── test_02_range_configs.py  # IMSI range config CRUD
├── test_03_profiles_a.py     # Profile A (ip_resolution=iccid) CRUD + lookup
├── test_04_profiles_b.py     # Profile B (ip_resolution=imsi) CRUD + lookup
├── test_05_profiles_c.py     # Profile C (ip_resolution=imsi_apn) CRUD + lookup
├── test_06_imsi_ops.py       # Add / remove IMSI, per-IMSI suspend
├── test_07_dynamic_alloc.py  # First-connection inline allocation via GET /lookup
├── test_08_bulk.py           # Bulk upsert via POST /profiles/bulk + job polling
├── test_09_migration.py      # Validate migration script output via API
├── test_10_errors.py         # Validation, 404, 409, 503, auth errors
├── test_11_performance.py    # Latency assertions under concurrent load
├── docker-compose.test.yml   # PostgreSQL 15 + subscriber-profile-api + aaa-lookup-service
├── run_all.sh                # execute full suite, emit JUnit XML
└── requirements.txt          # pytest, httpx, pytest-asyncio, pytest-xdist
```

---

## Environment & Configuration

```python
# conftest.py — key fixtures

PROVISION_BASE = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
LOOKUP_BASE    = os.getenv("LOOKUP_URL",    "http://localhost:8081/v1")
JWT_TOKEN      = os.getenv("TEST_JWT",      "<test-token>")

@pytest.fixture(scope="session")
def http():
    return httpx.Client(base_url=PROVISION_BASE,
                        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                        timeout=5.0)

@pytest.fixture(scope="session")
def lookup_http():
    return httpx.Client(base_url=LOOKUP_BASE,
                        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                        timeout=5.0)
```

**Run order is sequential** (test_01 → test_11). Each module is self-contained: it creates
its own fixtures, runs its cases, then tears down. No shared mutable state between modules.

---

## Test Cases by Module

### test_01_pools.py — IP Pool CRUD + Stats

| # | Test | Expected |
|---|---|---|
| 1.1 | POST /pools with valid subnet (100.65.120.0/24) | 201, `pool_id` UUID returned |
| 1.2 | GET /pools/{pool_id} | 200, subnet / start_ip / end_ip correct |
| 1.3 | GET /pools/{pool_id}/stats immediately after creation | `available = 253` (usable /24), `allocated = 0` |
| 1.4 | PATCH /pools/{pool_id} — rename pool | 200, GET confirms new name |
| 1.5 | GET /pools?account_name=Melita | 200, list includes created pool |
| 1.6 | DELETE /pools/{pool_id} with 0 allocations | 204 |
| 1.7 | DELETE /pools/{pool_id} with active allocations | 409 (pool in use) |
| 1.8 | POST /pools with invalid subnet (bad CIDR) | 400 validation_failed |

---

### test_02_range_configs.py — IMSI Range Config CRUD

| # | Test | Expected |
|---|---|---|
| 2.1 | POST /range-configs with valid f_imsi / t_imsi / pool_id | 201, `id` returned |
| 2.2 | GET /range-configs/{id} | 200, fields correct |
| 2.3 | GET /range-configs?account_name=Melita | 200, list includes created config |
| 2.4 | PATCH /range-configs/{id} — change pool_id and ip_resolution | 200, GET confirms update |
| 2.5 | PATCH /range-configs/{id} — set status=suspended | 200 |
| 2.6 | DELETE /range-configs/{id} | 204 |
| 2.7 | POST /range-configs with f_imsi > t_imsi (inverted range) | 400 validation_failed |
| 2.8 | POST /range-configs with non-15-digit IMSI boundary | 400 validation_failed |

---

### test_03_profiles_a.py — Profile A: `ip_resolution = "iccid"`

All GET /lookup calls use **IMSI + APN as input** and expect `{"static_ip": "..."}`.

| # | Test | Expected |
|---|---|---|
| 3.1 | POST /profiles — iccid mode, 2 IMSIs, 1 iccid_ip (no apn field) | 201, `sim_id` returned |
| 3.2 | GET /profiles/{sim_id} | 200, `iccid_ips[0].static_ip` = 100.65.120.5 |
| 3.3 | GET /lookup?imsi={imsi1}&apn=internet.operator.com | 200, `{"static_ip":"100.65.120.5"}` |
| 3.4 | GET /lookup?imsi={imsi2}&apn=ims.operator.com | 200, same IP (different IMSI, APN ignored) |
| 3.5 | GET /lookup?imsi={imsi1}&apn=any.garbage.apn | 200, same IP (APN irrelevant in iccid mode) |
| 3.6 | PATCH /profiles/{sim_id} — change status to suspended | 200 |
| 3.7 | GET /lookup after SIM suspended | 403 `{"error":"suspended"}` |
| 3.8 | PATCH status back to active; GET /lookup | 200, IP resolves again |
| 3.9 | DELETE /profiles/{sim_id} | 204, subsequent GET returns 404 |

---

### test_04_profiles_b.py — Profile B: `ip_resolution = "imsi"`

| # | Test | Expected |
|---|---|---|
| 4.1 | POST /profiles — imsi mode, iccid=null, 2 IMSIs with distinct static_ips | 201 |
| 4.2 | GET /lookup?imsi={imsi1}&apn=internet.operator.com | 200, `{"static_ip":"100.65.120.5"}` |
| 4.3 | GET /lookup?imsi={imsi1}&apn=ims.operator.com | 200, same IP (APN ignored in imsi mode) |
| 4.4 | GET /lookup?imsi={imsi2}&apn=internet.operator.com | 200, `{"static_ip":"101.65.120.5"}` |
| 4.5 | PATCH /profiles/{sim_id} — set real iccid | 200; GET shows iccid populated |
| 4.6 | PATCH /profiles/{sim_id}/imsis/{imsi1} — suspend IMSI #1 | 200 |
| 4.7 | GET /lookup?imsi={imsi1}&apn=internet.operator.com | 403 `{"error":"suspended"}` |
| 4.8 | GET /lookup?imsi={imsi2}&apn=internet.operator.com | 200, IMSI #2 still resolves |
| 4.9 | PATCH /profiles/{sim_id}/imsis/{imsi1} — update static_ip | 200; GET /lookup returns new IP |

---

### test_05_profiles_c.py — Profile C: `ip_resolution = "imsi_apn"`

| # | Test | Expected |
|---|---|---|
| 5.1 | POST /profiles — imsi_apn mode; IMSI #1 → [smf1→IP_A, smf2→IP_B]; IMSI #2 → [smf3→IP_C] | 201 |
| 5.2 | GET /lookup?imsi={imsi1}&apn=smf1.operator.com | 200, `{"static_ip":"IP_A"}` |
| 5.3 | GET /lookup?imsi={imsi1}&apn=smf2.operator.com | 200, `{"static_ip":"IP_B"}` |
| 5.4 | GET /lookup?imsi={imsi2}&apn=smf3.operator.com | 200, `{"static_ip":"IP_C"}` |
| 5.5 | GET /lookup?imsi={imsi1}&apn=smf9.unknown.com (no match, no wildcard) | 404 `{"error":"apn_not_found"}` |
| 5.6 | POST /profiles/{sim_id}/imsis/{imsi1} — add apn_ip {apn:null, ip:IP_D} (wildcard) | 200 |
| 5.7 | GET /lookup?imsi={imsi1}&apn=smf9.unknown.com | 200, `{"static_ip":"IP_D"}` (wildcard fires) |
| 5.8 | GET /lookup?imsi={imsi1}&apn=smf1.operator.com after wildcard added | 200, `{"static_ip":"IP_A"}` (exact wins) |
| 5.9 | Two concurrent GET /lookup for smf1 + smf2 same IMSI | both return their respective IPs |

---

### test_06_imsi_ops.py — IMSI Add / Remove

| # | Test | Expected |
|---|---|---|
| 6.1 | GET /profiles/{sim_id}/imsis | 200, list contains current IMSIs |
| 6.2 | POST /profiles/{sim_id}/imsis — add new IMSI with apn_ips | 201 |
| 6.3 | GET /lookup?imsi={new_imsi}&apn=internet.operator.com | 200, `{"static_ip":"..."}` |
| 6.4 | GET /profiles/{sim_id}/imsis/{new_imsi} | 200, apn_ips correct |
| 6.5 | DELETE /profiles/{sim_id}/imsis/{new_imsi} | 204 |
| 6.6 | GET /lookup after IMSI deleted | 404 |
| 6.7 | POST /profiles/{sim_id}/imsis — IMSI already assigned to another SIM | 409 `imsi_conflict` |
| 6.8 | DELETE last IMSI on a profile | 400 (profile must have at least 1 IMSI) or allowed (business decision to record) |

---

### test_07_dynamic_alloc.py — First-Connection Inline Allocation

Allocation is transparent: caller always uses `GET /lookup`, same endpoint as normal lookups.

| # | Test | Expected |
|---|---|---|
| 7.1 | Setup: pool + active range config covering IMSI range | — |
| 7.2 | IMSI in range, not yet in sim_profiles → GET /lookup?imsi={imsi}&apn=internet.operator.com | 200, `{"static_ip":"..."}` — profile created |
| 7.3 | Same IMSI again → GET /lookup | 200, same IP (existing profile, no re-allocation) |
| 7.4 | GET /pools/{pool_id}/stats after allocation | `allocated` +1, `available` -1 |
| 7.5 | GET /profiles?imsi={imsi} — verify auto-created profile | 200, ip_resolution=imsi, iccid=null |
| 7.6 | IMSI not in any range config → GET /lookup?imsi={unknown}&apn=internet.operator.com | 404 `{"error":"not_found"}` |
| 7.7 | IMSI in a suspended range config → GET /lookup | 404 (suspended range ignored) |
| 7.8 | Exhaust all IPs in pool → GET /lookup for next new IMSI | 503 `{"error":"pool_exhausted"}` |
| 7.9 | 10 concurrent GET /lookup for 10 distinct first-connection IMSIs in same pool | all 200, 10 distinct IPs, no duplicates |

---

### test_08_bulk.py — Bulk Upsert

| # | Test | Expected |
|---|---|---|
| 8.1 | POST /profiles/bulk with 500 Profile-A + 500 Profile-B + 500 Profile-C | 202, `job_id` returned |
| 8.2 | Poll GET /jobs/{job_id} until status=completed (max 10 min timeout) | `processed=1500`, `failed=0` |
| 8.3 | Spot-check 10 random sim_ids → GET /profiles/{sim_id} | 200, profile fields correct |
| 8.4 | GET /lookup for 10 random IMSIs from the batch | 200, all return correct static_ip |
| 8.5 | POST /profiles/bulk with 1 valid + 1 invalid IMSI (14 digits) | 202; job completed; `failed=1`, `processed=1` |
| 8.6 | GET /jobs/{job_id} errors array contains field=imsi details | 200, error row present |
| 8.7 | Bulk upsert same sim_id twice (idempotency) | second upsert updates, total profile count unchanged |
| 8.8 | POST /profiles/bulk with CSV file upload (multipart/form-data) | 202, same job flow |

---

### test_09_migration.py — Migration Script Validation

Runs the migration script against a controlled sample MariaDB dump (fixture data, not production).

| # | Test | Expected |
|---|---|---|
| 9.1 | Run migration script on Athens-only sample dump | sim_profiles count = distinct ICCID-groups + unmatched IMSIs |
| 9.2 | IMSI in imsi_iccid_map.csv → GET /profiles?imsi={imsi} | `iccid` = real ICCID from map |
| 9.3 | IMSI not in map → GET /profiles?imsi={imsi} | `iccid` = null |
| 9.4 | IMSI in 2 dumps, different IPs, same client → GET /profiles?imsi={imsi} | ip_resolution=imsi_apn, 2 apn_ips with apn=pgw1 and apn=pgw2 |
| 9.5 | IMSI in 2 dumps, same IP → GET /profiles?imsi={imsi} | ip_resolution=imsi, 1 apn_ips with apn=null |
| 9.6 | Range config rows → GET /range-configs?account_name={name} | count = tbl_imsi_range_config rows for that client |
| 9.7 | Pool stats post-migration | available = total IPs − allocated IMSIs |

---

### test_10_errors.py — Validation & Error Handling

| # | Test | Expected |
|---|---|---|
| 10.1 | POST /profiles — IMSI 14 digits | 400, field=imsi |
| 10.2 | POST /profiles — ICCID 10 digits | 400, field=iccid |
| 10.3 | POST /profiles — missing ip_resolution | 400 |
| 10.4 | POST /profiles — ip_resolution=bogus_value | 400 |
| 10.5 | POST /profiles — duplicate ICCID | 409 `iccid_conflict` |
| 10.6 | POST /profiles — duplicate IMSI | 409 `imsi_conflict` |
| 10.7 | GET /profiles/{unknown_uuid} | 404 |
| 10.8 | DELETE terminated profile | 404 |
| 10.9 | PATCH /profiles/{sim_id} — ICCID already used by another profile | 409 |
| 10.10 | GET /lookup — suspended SIM | 403 `{"error":"suspended"}` |
| 10.11 | PATCH ip_resolution from imsi → imsi_apn without adding apn fields | 400 validation_failed |
| 10.12 | PATCH ip_resolution from imsi → iccid; supply valid iccid_ips; verify old apn_ips cleared | 200; GET /lookup returns iccid_static_ip |
| 10.13 | GET /lookup — missing apn param | 400 |
| 10.14 | GET /lookup — missing imsi param | 400 |
| 10.15 | Any endpoint with invalid JWT | 401 |

---

### test_11_performance.py — Latency Assertions

Tests run against a pre-seeded 300K-profile dataset (loaded by a one-time fixture).
All timings measured end-to-end from test client to API response.

| # | Test | Pass Criteria |
|---|---|---|
| 11.1 | 100 sequential GET /lookup (warm DB, all existing profiles) | p99 ≤ 15ms |
| 11.2 | 50 concurrent GET /lookup | p99 ≤ 15ms; 0 errors |
| 11.3 | 200 concurrent GET /lookup (stress) | p99 ≤ 30ms; 0 errors |
| 11.4 | 10 concurrent POST /profiles/bulk (100 profiles each) | all complete; 0 errors |
| 11.5 | 10 concurrent first-connection GET /lookup (distinct IMSIs, same pool) | 10 distinct IPs; 0 duplicates |
| 11.6 | GET /pools/{pool_id}/stats with 300K allocated rows | response ≤ 200ms |
| 11.7 | GET /profiles/{sim_id} full profile (many IMSIs) | response ≤ 50ms |

---

## Run Order & Teardown

```
1. docker-compose -f docker-compose.test.yml up -d  (PostgreSQL + both services)
2. Wait for /health on both services
3. Run test_01 → test_11 sequentially (pytest -v --junitxml=results.xml)
4. Each module tears down its own fixtures in a finally block
5. docker-compose down --volumes
6. Output: results.xml + timing.csv + console summary

PASSED: 65 / FAILED: 0 / SKIPPED: 0
Total time: ~5 min (excluding 300K seed load ~3 min)
```

---

## CI Integration

```yaml
# .github/workflows/regression.yml (excerpt)
jobs:
  regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Start services
        run: docker compose -f docker-compose.test.yml up -d
      - name: Run tests
        run: |
          pip install -r requirements.txt
          pytest --junitxml=results.xml -n 1
      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: junit-results
          path: results.xml
```

---

## Kubernetes & Helm Deployment

> **Dev environment:** Deployed via the `aaa-platform` umbrella chart (Plan 7) with
> `values-dev.yaml` on **k3d / WSL2**. Run with `make test` — the Job is off by default
> (`aaa-regression-tester.enabled: false`) and enabled on demand.
> Production target: generic k8s or OCI/OKE.

### Overview

The regression test client runs as a **Kubernetes Job** (not a long-running Deployment) — it executes the full test suite, publishes metrics to Prometheus Pushgateway, then terminates. It is triggered on demand (CI pipeline or manual `helm upgrade --install`) and cleaned up automatically after completion.

---

### Helm Chart Structure

```
charts/aaa-regression-tester/
├── Chart.yaml
├── values.yaml
├── templates/
│   ├── job.yaml            # Kubernetes Job running the test suite
│   ├── configmap.yaml      # pytest.ini + run_all.sh
│   ├── secret.yaml         # TEST_JWT, PROVISION_URL, LOOKUP_URL
│   └── serviceaccount.yaml
```

**Chart.yaml**
```yaml
apiVersion: v2
name: aaa-regression-tester
description: Regression test suite for the AAA cloud-native platform
type: application
version: 1.0.0
appVersion: "1.0.0"
```

**values.yaml**
```yaml
image:
  repository: registry.example.com/aaa-regression-tester
  tag: "latest"
  pullPolicy: IfNotPresent

env:
  PROVISION_URL: "http://subscriber-profile-api:8080/v1"
  LOOKUP_URL: "http://aaa-lookup-service:8081/v1"
  PUSHGATEWAY_URL: "http://prometheus-pushgateway:9091"

# JWT token injected from an external Secret
jwtSecretName: "aaa-test-jwt"

job:
  backoffLimit: 0          # fail immediately on error; no retries
  ttlSecondsAfterFinished: 3600

resources:
  requests:
    cpu: "500m"
    memory: "256Mi"
  limits:
    cpu: "1"
    memory: "512Mi"

nodeSelector: {}
tolerations: []
```

---

### Pod Specification (Job template)

```yaml
# templates/job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "aaa-regression-tester.fullname" . }}
  labels:
    app.kubernetes.io/name: aaa-regression-tester
    app.kubernetes.io/component: test-runner
spec:
  backoffLimit: {{ .Values.job.backoffLimit }}
  ttlSecondsAfterFinished: {{ .Values.job.ttlSecondsAfterFinished }}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: aaa-regression-tester
      annotations:
        # No Prometheus scrape annotation — metrics pushed via Pushgateway
        prometheus.io/scrape: "false"
    spec:
      restartPolicy: Never
      serviceAccountName: {{ include "aaa-regression-tester.serviceAccountName" . }}
      containers:
        - name: regression-tester
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          command: ["/bin/sh", "-c"]
          args:
            - |
              pytest --junitxml=/results/results.xml -v && \
              python /app/push_metrics.py --pushgateway $PUSHGATEWAY_URL
          env:
            - name: PROVISION_URL
              value: {{ .Values.env.PROVISION_URL | quote }}
            - name: LOOKUP_URL
              value: {{ .Values.env.LOOKUP_URL | quote }}
            - name: PUSHGATEWAY_URL
              value: {{ .Values.env.PUSHGATEWAY_URL | quote }}
            - name: TEST_JWT
              valueFrom:
                secretKeyRef:
                  name: {{ .Values.jwtSecretName }}
                  key: token
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          volumeMounts:
            - name: results
              mountPath: /results
      volumes:
        - name: results
          emptyDir: {}
```

---

### Prometheus Metrics (via Pushgateway)

After the test run completes, `push_metrics.py` pushes the following metrics to the Prometheus Pushgateway:

| Metric | Type | Labels | Description |
|---|---|---|---|
| `regression_test_passed_total` | Gauge | `suite`, `module` | Number of tests that passed per module |
| `regression_test_failed_total` | Gauge | `suite`, `module` | Number of tests that failed per module |
| `regression_test_skipped_total` | Gauge | `suite`, `module` | Number of tests skipped |
| `regression_test_duration_seconds` | Gauge | `suite`, `module` | Wall-clock duration of each test module |
| `regression_suite_duration_seconds` | Gauge | `suite` | Total suite duration |
| `regression_lookup_latency_p99_ms` | Gauge | `test` | Measured p99 latency from test_11 |
| `regression_last_run_timestamp` | Gauge | `suite` | Unix timestamp of last run |
| `regression_suite_exit_code` | Gauge | `suite` | 0 = all passed, 1 = failures |

**Pushgateway scrape configuration (prometheus.yml):**
```yaml
scrape_configs:
  - job_name: pushgateway
    honor_labels: true
    static_configs:
      - targets: ['prometheus-pushgateway:9091']
```

---

### Grafana Dashboard — Regression Test Results

**Dashboard UID:** `aaa-regression-tests`

| Panel | Type | Query | Description |
|---|---|---|---|
| Suite Status | Stat | `regression_suite_exit_code{suite="aaa"}` | Green=0 (pass) / Red=1 (fail) |
| Pass / Fail / Skip | Pie chart | `regression_test_passed_total`, `regression_test_failed_total`, `regression_test_skipped_total` | Overall pass rate |
| Tests Passed by Module | Bar chart | `regression_test_passed_total by (module)` | Per-module breakdown |
| Suite Duration | Gauge | `regression_suite_duration_seconds{suite="aaa"}` | Total run time; threshold at 600s |
| Module Duration | Horizontal bar | `regression_test_duration_seconds by (module)` | Slowest modules highlighted |
| p99 Lookup Latency (test_11) | Gauge | `regression_lookup_latency_p99_ms{test="test_11"}` | Alert threshold at 15ms |
| Last Run Time | Stat | `regression_last_run_timestamp` | Time since last successful execution |
| History (pass/fail over time) | Time series | `regression_suite_exit_code` over 30 days | Trend line |

**Alerts:**
```yaml
groups:
  - name: regression
    rules:
      - alert: RegressionTestFailed
        expr: regression_suite_exit_code{suite="aaa"} == 1
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "AAA regression suite has failed"

      - alert: RegressionP99LatencyTooHigh
        expr: regression_lookup_latency_p99_ms{test="test_11"} > 15
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Lookup p99 latency {{ $value }}ms exceeds 15ms SLA in regression"

      - alert: RegressionTestStale
        expr: time() - regression_last_run_timestamp{suite="aaa"} > 86400
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "AAA regression suite has not run in over 24 hours"
```
