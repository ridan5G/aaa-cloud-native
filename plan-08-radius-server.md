# Plan 8 — RADIUS Authentication Server (`aaa-radius-server`)

## Role & SLA

The `aaa-radius-server` is the RADIUS protocol termination point. It receives
`Access-Request` packets from NAS/PGW/SMF/GGSN nodes over UDP/1812, performs
the two-stage AAA flow against existing HTTP services, and returns
`Access-Accept` (with `Framed-IP-Address`) or `Access-Reject`.

It is a **thin protocol-translation layer** — all business logic (subscriber
lookup, IP allocation) lives in `aaa-lookup-service` and `subscriber-profile-api`.
This service only speaks RADIUS and routes between them.

| Property | Value |
|---|---|
| Protocol | RADIUS over UDP/1812 (RFC 2865) |
| Callers | NAS, PGW, SMF, GGSN (any RADIUS-compliant AAA client) |
| Upstream (Stage 1) | `aaa-lookup-service` — `GET /lookup?imsi=&apn=` |
| Upstream (Stage 2) | `subscriber-profile-api` — `POST /v1/first-connection` |
| Response time SLA | Bounded by upstream p99: ~15 ms Stage 1 + network |
| Replicas | 2 per region (recommended) |
| Language | C++20 |
| Dependencies | libcurl, OpenSSL (MD5), spdlog, nlohmann/json |

---

## Architecture

```
NAS / PGW / SMF / GGSN   (UDP 1812)
        │
        ▼
aaa-radius-server
  ├── recvfrom loop  (main thread — receive only, no blocking HTTP)
  └── thread pool   (WORKER_THREADS workers, each owns a CURL handle)
        │
        ├─ Stage 1 ─► GET /lookup?imsi={imsi}&apn={apn}    (aaa-lookup-service)
        │                200 → Access-Accept + Framed-IP-Address
        │                403 → Access-Reject  (subscriber suspended)
        │                404 → Stage 2 ↓
        │
        └─ Stage 2 ─► POST /v1/first-connection             (subscriber-profile-api)
                         {imsi, apn, imei}
                         200     → Access-Accept + Framed-IP-Address
                         404/503 → Access-Reject  (no range config / pool exhausted)
```

**Stage 2 is rare.** It fires only on the very first connection for an IMSI
that has no provisioned profile yet. All subsequent connections hit Stage 1
with a 200 and Stage 2 is never reached again for that IMSI.

---

## RADIUS Packet Mapping

### Access-Request (inbound) — attribute extraction

| Attribute | Type | Source | Used for |
|---|---|---|---|
| User-Name | attr 1 | Access-Request | Fallback IMSI (if VSA absent) |
| Framed-IP-Address | attr 8 | — | Not in request; only in Accept |
| Vendor-Specific (3GPP-IMSI) | attr 26, vendor=10415, type=1 | Access-Request | **Preferred IMSI** source |
| Vendor-Specific (3GPP-IMEISV) | attr 26, vendor=10415, type=20 | Access-Request | IMEI for Stage 2 |
| Vendor-Specific (3GPP-Charging-Characteristics) | attr 26, vendor=10415, type=13 | Access-Request | **use_case_id** — forwarded to both upstreams |
| Called-Station-Id | attr 30 | Access-Request | APN |
| Calling-Station-Id | attr 31 | Access-Request | MSISDN (logged only) |

IMSI resolution priority: `3GPP-IMSI VSA` → `User-Name` fallback.

IMEI: `3GPP-IMEISV` is a 16-digit string (14 TAC+SNR + 2 SVN). Only the
first 14 digits (IMEI base) are forwarded in the `POST /v1/first-connection` body.

**use_case_id** (`3GPP-Charging-Characteristics`, VSA 10415:13): forwarded to
both upstream services as `use_case_id` so they can apply per-use-case routing,
pool selection, or policy logic. Omitted from both requests when absent.

### Access-Accept (outbound) — 26 bytes total

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Code = 2   |  Identifier   |        Length = 26             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                   Response Authenticator (16 bytes)           |
|                   MD5(Code|ID|Len|ReqAuth|Attrs|Secret)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Type = 8   |  Length = 6   |   Framed-IP-Address (4 bytes)  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Access-Reject (outbound) — 20 bytes total

Header only; no attributes. RFC 2865 §5 explicitly forbids `Framed-IP-Address`
in a Reject.

### Response Authenticator

```
MD5(Code | ID | Length | RequestAuthenticator | Attributes | SharedSecret)
```

Computed with OpenSSL `EVP_DigestInit_ex(ctx, EVP_md5(), nullptr)`. The NAS
verifies this before trusting the response.

---

## Two-Stage AAA Flow (detailed)

```
Receive Access-Request
        │
        ▼
Extract IMSI (VSA 10415:1 or User-Name), APN (attr 30),
        IMEI (VSA 10415:20), use_case_id (VSA 10415:13)
        │
        ├─ IMSI or APN empty?
        │       YES → Access-Reject
        │
        ▼
Stage 1: GET {LOOKUP_URL}/lookup?imsi={imsi}&apn={apn}[&use_case_id={use_case_id}]
        │
        ├─ 200 OK:  parse {"static_ip": "x.x.x.x"}
        │            → Access-Accept + Framed-IP-Address
        │
        ├─ 403:     subscriber suspended
        │            → Access-Reject
        │
        ├─ 404:     profile not found → proceed to Stage 2
        │
        └─ other:   HTTP/network error
                     → Access-Reject

Stage 2: POST {PROVISIONING_URL}/v1/first-connection
         body: {"imsi": "...", "apn": "...", "imei": "...", "use_case_id": "..."}
               (use_case_id omitted when 3GPP-Charging-Characteristics was absent)
        │
        ├─ 200 OK:  parse {"static_ip": "x.x.x.x"}
        │            → Access-Accept + Framed-IP-Address
        │
        ├─ 404:     no range config covers this IMSI
        │            → Access-Reject
        │
        ├─ 503:     IP pool exhausted
        │            → Access-Reject
        │
        └─ other:   unexpected error
                     → Access-Reject
```

---

## Source Code Layout

```
aaa-radius-server/
├── CMakeLists.txt          C++20 build, vcpkg toolchain
├── vcpkg.json              Dependencies: curl, nlohmann-json, spdlog, openssl
├── Dockerfile              2-stage Ubuntu 24.04 build → minimal runtime image
├── README.md               Architecture, config reference, capacity sizing
└── src/
    ├── Config.h            Singleton loaded from env vars
    ├── Radius.h / .cpp     RADIUS packet parse + build (RFC 2865)
    ├── HttpClient.h / .cpp libcurl wrapper (per-thread CURL* handle)
    ├── Handler.h / .cpp    Two-stage AAA business logic
    └── main.cpp            UDP socket + WorkQueue + thread pool
```

### Component responsibilities

| File | Responsibility |
|---|---|
| `Config.h` | Singleton; reads all env vars; validates at startup |
| `Radius.cpp` | `parseAccessRequest()` — walks attribute TLVs, decodes VSAs; `buildAccessAccept()` / `buildAccessReject()` — assembles RFC 2865 packets with correct authenticator |
| `HttpClient.cpp` | One `CURL*` per instance; `get()` / `post()` with 5 s / 10 s timeouts; `CURLOPT_NOSIGNAL=1` (thread safe) |
| `Handler.cpp` | Calls `lookup()` then optionally `firstConnection()`; maps HTTP status codes to Accept/Reject |
| `main.cpp` | `recvfrom` loop; `WorkQueue` (MPMC with mutex+condvar); thread pool; `SIGTERM`/`SIGINT` closes socket to unblock `recvfrom` |

### Thread model

```
main thread:   recvfrom() → push WorkItem{data, src_addr} → WorkQueue
                                                                │
worker thread N:  pop() → parseAccessRequest()                  │
                        → Handler::handle()                     │
                            → HttpClient::get()  (blocking)     │
                            → HttpClient::post() (blocking)     │
                        → sendto()                              │
```

Each worker thread owns its own `Handler` → `HttpClient` → `CURL*` handle.
`curl_global_init` is called once from the main thread before any worker starts.
There is no shared mutable state between workers.

---

## Configuration

All configuration is via environment variables, read at startup by `Config::load()`.

| Variable | Default | Required | Description |
|---|---|---|---|
| `RADIUS_PORT` | `1812` | No | UDP port to listen on |
| `RADIUS_SECRET` | `testing123` | **Yes (non-empty)** | Shared secret with NAS clients; used for response authenticator |
| `LOOKUP_URL` | `http://aaa-lookup-service:8081` | No | aaa-lookup-service base URL (no `/v1` suffix) |
| `PROVISIONING_URL` | `http://subscriber-profile-api:8080` | No | subscriber-profile-api base URL (no `/v1` suffix) |
| `WORKER_THREADS` | `8` | No | Thread pool size (1–256); tune for throughput (see Capacity) |
| `LOG_LEVEL` | `info` | No | `trace` \| `debug` \| `info` \| `warn` \| `error` |

**`RADIUS_SECRET` must match the secret configured on every NAS client that
sends Access-Requests.** If it is wrong, the NAS will discard all responses
(response authenticator verification will fail on the NAS side).

---

## Capacity Sizing — 1000 RPS, 99.9% lookup hit rate

### Worker threads (critical parameter)

Workers block on the HTTP round-trip for the full duration of each request.
Capacity follows **Little's Law**: `Required workers = arrival rate × avg HTTP latency`

| Lookup service p50 | Workers needed for 1000 RPS | At default 8 workers |
|---|---|---|
| 3 ms | 3 | ✅ 2,667 RPS capacity |
| 5 ms | 5 | ✅ 1,600 RPS capacity |
| 8 ms | 8 | ⚠️ exactly at limit, zero headroom |
| 10 ms | 10 | ❌ 800 RPS capacity (drops requests) |

The lookup service SLA is p99 < 15 ms, so p50 is typically 3–7 ms in-cluster.
8 workers leaves no headroom if p50 drifts to 8 ms (DB replica lag, cold cache, etc.).

**Recommended: `WORKER_THREADS: 16`** — sustains 1000 RPS even if p50 reaches 16 ms,
and provides 3× headroom at 5 ms.

### CPU breakdown — ~38 µs compute per request

| Operation | Time |
|---|---|
| UDP `recvfrom` + `sendto` syscalls | ~2 µs |
| RADIUS packet parse (memcpy, strings) | ~4 µs |
| libcurl overhead (poll, HTTP frame parsing) | ~15 µs |
| nlohmann::json parse | ~4 µs |
| OpenSSL MD5 (response authenticator) | ~2 µs |
| Thread queue mutex ops | ~3 µs |
| spdlog format + write | ~8 µs |
| **Total compute per request** | **~38 µs** |

```
CPU at 1000 RPS = 1000 req/s × 38 µs = 38 ms/s ≈ 0.04 cores
```

### RAM breakdown — ~15–18 MB RSS

| Component | RSS |
|---|---|
| Binary + shared libs (libcurl, libssl3, libc) | ~12–15 MB |
| 16 thread stacks (virtual 8 MB each; actual RSS ~80 KB each) | ~1.3 MB |
| libcurl: 16 CURL handles × ~40 KB state | ~640 KB |
| libcurl: DNS cache + connection state | ~200 KB |
| In-flight request buffers (16 × ~600 bytes) | ~10 KB |
| Work queue (typically empty at steady-state 1000 RPS) | ~50 KB |
| spdlog ring buffer + formatter | ~1 MB |
| **Total RSS** | **~15–18 MB** |

### Recommended Helm values for 1000 RPS

```yaml
workerThreads: 16      # default 8 is insufficient if lookup p50 > 8 ms

resources:
  requests:
    cpu: "100m"        # compute is I/O-bound; actual usage ~40m at 1000 RPS
    memory: "32Mi"     # actual RSS ~15–18 MB
  limits:
    cpu: "250m"
    memory: "64Mi"
```

### 2-replica deployment totals

| | Per pod | Total (2 pods) |
|---|---|---|
| CPU request | 100m | **200m** |
| CPU limit | 250m | 500m |
| RAM request | 32Mi | **64Mi** |
| RAM limit | 64Mi | 128Mi |
| Worker threads | 16 | 32 effective |
| Throughput capacity | ~1,600 RPS (at 10 ms p50) | ~3,200 RPS combined |

---

## Container Spec

```
┌───────────────────────────────────────────────────────────────────┐
│  Container: aaa-radius-server                                     │
│  Language:  C++20 (compiled, single static-linked binary)         │
│  Protocol:  UDP/1812 (RADIUS RFC 2865)                            │
│  Replicas:  2 per region (recommended)                            │
│  Resources: 100m CPU / 32Mi RAM per replica (at 1000 RPS)        │
│  Deps:      libcurl, libssl3, spdlog, nlohmann/json               │
│  No DB connection — entirely stateless                            │
└───────────────────────────────────────────────────────────────────┘
```

**Why a custom C++ server instead of aaa-radius-server + rlm_rest:**

| Concern | aaa-radius-server + rlm_rest | aaa-radius-server |
|---|---|---|
| Container size | ~200 MB (full daemon + modules) | ~25 MB (binary + runtime libs) |
| Configuration | Unlang policy files, complex module config | 6 env vars |
| Attribute mapping | Requires rlm_rest template files | Compiled into Handler.cpp |
| Operational complexity | Large daemon with many unneeded modules | Single-purpose binary |
| Debugging | Opaque rlm_rest logs | Structured spdlog output |
| First-connection fallback | Two separate REST module stanzas | Single `if (status==404)` in Handler.cpp |

---

## Helm Chart

```
charts/aaa-radius-server/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── _helpers.tpl
    ├── deployment.yaml   # Deployment with UDP containerPort 1812
    ├── service.yaml      # ClusterIP UDP service on port 1812
    └── secret.yaml       # Kubernetes Secret for radius-secret key
```

The `RADIUS_SECRET` is read from a Kubernetes Secret (key: `radius-secret`).
In dev environments `radiusSecret.value` in `values.yaml` creates the Secret
automatically. In production, set `radiusSecret.secretName` to reference an
externally managed Secret (Vault, SOPS, etc.).

---

## Observability

### Structured log lines (spdlog JSON-style to stdout)

Every request logs at `info` level:

```
[aaa-radius] IMSI=123456789012345 APN=internet.operator.com result=accept framed_ip=100.65.120.5 stage=1 latency_ms=3.2
[aaa-radius] IMSI=234567890123456 APN=internet.operator.com result=reject reason=suspended stage=1 latency_ms=2.8
[aaa-radius] IMSI=345678901234567 APN=internet.operator.com result=accept framed_ip=100.65.120.9 stage=2 latency_ms=52.1
[aaa-radius] IMSI=456789012345678 APN=internet.operator.com result=reject reason=no_range_config stage=2 latency_ms=48.3
```

**IMSI is logged as the full 15-digit number** for operator readability and ease of debugging.
All log lines in all services (lookup, API, RADIUS) use the plain IMSI.

### Key log events

| Event | Level | Trigger |
|---|---|---|
| Server startup / port binding | `info` | Process start |
| Signal received / shutdown initiated | `info` | SIGTERM / SIGINT |
| Malformed / non-Access-Request packet | `debug` | `parseAccessRequest()` returns nullopt |
| `sendto` failure | `error` | OS error on UDP write |
| `curl_global_init` failure | `critical` | Startup failure |
| HTTP errors (non-200/403/404) from upstreams | `warn` | Unexpected upstream response |

### Metrics

All metrics are exposed at `GET /metrics` (Prometheus text format) on the configured metrics port.

**RADIUS layer:**

| Metric | Labels | Description |
|---|---|---|
| `radius_access_requests_total` | — | Valid Access-Request packets received |
| `radius_packets_dropped_total` | — | Malformed / non-AccessRequest packets |
| `radius_responses_total` | `result` (accept\|reject) | RADIUS responses sent |
| `radius_requests_total` | `result` (accept\|reject), `stage` (1\|2) | Completed requests broken down by outcome and stage — stage 1 = lookup hit, stage 2 = first-connection used |
| `radius_request_duration_ms` | — (histogram) | End-to-end RADIUS request latency; buckets: 1 5 10 25 50 100 250 500 1000 ms |
| `radius_upstream_errors_total` | `upstream` (lookup\|first_connection), `status_code` | Unexpected upstream failures (curl errors, non-business HTTP status codes) |

**Upstream call counters:**

| Metric | Labels | Description |
|---|---|---|
| `lookup_requests_total` | — | HTTP GET requests sent to aaa-lookup-service |
| `lookup_responses_total` | `status` (200\|403\|404\|error) | Lookup service responses |
| `first_connection_requests_total` | — | HTTP POST requests sent to subscriber-profile-api |
| `first_connection_responses_total` | `status` (200\|404\|503\|error) | First-connection responses |

The Grafana dashboard (`charts/aaa-platform/files/aaa-platform-dashboard.json`) has panels
for all metrics listed above.

---

## Security

- **Shared secret (`RADIUS_SECRET`)**: The only authentication mechanism between
  NAS and this server. Use a strong random value (≥ 32 characters) in production.
  Rotate by updating the Kubernetes Secret and rolling the deployment.
- **No TLS on RADIUS UDP**: RFC 2865 RADIUS is not encrypted. Ensure NAS ↔ server
  traffic is confined to a private network or VPN. For encrypted RADIUS consider
  RadSec (RFC 6614, RADIUS over TLS), which is out of scope for this implementation.
- **Container security**: `runAsNonRoot: true`, `runAsUser: 999`. The binary binds
  to port 1812 — no `CAP_NET_BIND_SERVICE` needed as 1812 > 1024.
- **No write access to DB**: This service makes no DB connections. All writes flow
  through `subscriber-profile-api`.

---

## Regression Tests (test_12)

Tests live in `aaa-regression-tester/test_12_radius.py` (class `TestRadiusServer`,
marked `@pytest.mark.radius`).

The entire class is **skipped automatically** if `aaa-radius-server` is not
reachable at `RADIUS_HOST:RADIUS_PORT`. No test infrastructure changes needed
when running the suite without the RADIUS server.

| Test | Description |
|---|---|
| `test_01` | Pre-condition: lookup returns 200 for pre-provisioned IMSI before any RADIUS test |
| `test_02` | Known IMSI → Stage 1 hit → `Access-Accept` (code=2) |
| `test_03` | `Framed-IP-Address` in Accept equals the provisioned `static_ip` |
| `test_04` | Suspend subscriber via PATCH → RADIUS returns `Access-Reject` (code=3) |
| `test_05` | Reactivate via PATCH → RADIUS returns `Access-Accept` with original IP |
| `test_06` | Unknown IMSI in a configured range → Stage 2 first-connection → `Access-Accept` with allocated IP |
| `test_07` | Same IMSI again (now has profile) → Stage 1 hit → same `Framed-IP-Address` (idempotency) |
| `test_08` | IMSI outside all range configs → Stage 1 404 + Stage 2 404 → `Access-Reject` |
| `test_09` | Raw socket test: RFC 2865 response authenticator verifies correctly |
| `test_10` | `Access-Reject` packet contains no `Framed-IP-Address` attribute (attr 8) |

### IMSI ranges (test_12 only — no overlap with other modules)

| Constant | Value | Purpose |
|---|---|---|
| `IMSI_KNOWN` | `278771200000001` | Pre-provisioned profile; used in tests 01–05 |
| `KNOWN_STATIC_IP` | `100.65.120.201` | Expected Framed-IP for IMSI_KNOWN |
| `IMSI_FC_NEW` | `278771200001001` | No profile before test_06; allocated by first-connection |
| `IMSI_OOB` | `278771209999001` | Outside all range configs; always rejects |
| `TEST_APN` | `internet.operator.com` | APN used in all requests |

### Running locally (docker-compose)

```bash
# Start full stack including aaa-radius-server
docker compose -f aaa-regression-tester/docker-compose.test.yml up -d

# Run only RADIUS tests
docker compose -f aaa-regression-tester/docker-compose.test.yml run --rm tester \
    pytest test_12_radius.py -v

# Run full suite (RADIUS tests auto-skip if server unreachable)
docker compose -f aaa-regression-tester/docker-compose.test.yml run --rm tester

# Skip RADIUS tests explicitly
docker compose -f aaa-regression-tester/docker-compose.test.yml run --rm tester \
    pytest -m "not radius"
```

---

## Multi-Region Notes

Unlike `aaa-lookup-service` (which is co-located with read replicas per region),
`aaa-radius-server` is co-located with the **NAS/PGW nodes** per region. Its
upstream calls go to the regional `aaa-lookup-service` (Stage 1, fast, local)
and to the central `subscriber-profile-api` (Stage 2 only, infrequent, accepts
~50–100 ms cross-region latency).

```
Region EU                               Central
────────────────────────────────────────────────────────────
NAS/PGW → aaa-radius-server (EU)
                │ Stage 1 (local, ~5 ms)
                └─► aaa-lookup-service (EU) → EU read replica
                │
                │ Stage 2 only, ~once per IMSI lifetime
                └─► subscriber-profile-api ──► PostgreSQL Primary
```
