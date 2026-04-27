# Plan 3 — AAA Lookup Service (`aaa-lookup-service`)

## Role & SLA

The `aaa-lookup-service` is the AAA hot-path service. It is the **only** system the
RADIUS/Diameter nodes talk to for subscriber authentication. Every PGW/GGSN
Access-Request flows through it.

This service holds no primary DB connection. On a **read-replica DB miss** (IMSI not yet
in `imsi2sim`) it makes one outbound HTTP call to `subscriber-profile-api` to trigger
first-connection allocation, then returns the allocated IP directly to the caller.

| Property | Value |
|---|---|
| SLA | <15ms p99 end-to-end (DB hit); first-connection path adds ~50–500 ms (once per IMSI lifetime) |
| Callers | `aaa-radius-server` (single `GET /lookup` call) |
| Protocol | REST over HTTP |
| Scale | 3–6 replicas per region, co-located with AAA nodes |
| DB connection | LOCAL PostgreSQL read replica **only** — no primary connection |
| Outbound HTTP | `POST /v1/first-connection` on `subscriber-profile-api` — on DB miss only |

---

## The Single Endpoint

```
GET /v1/lookup?imsi={imsi}&apn={apn}[&imei={imei}][&use_case_id={use_case_id}]
GET /lookup?imsi={imsi}&apn={apn}[&imei={imei}][&use_case_id={use_case_id}]
```

Both paths are registered (`/v1/lookup` matches the Ingress rewrite rule; `/lookup` is the bare path for direct service calls). `imei` and `use_case_id` are optional — they are forwarded to `subscriber-profile-api` on first-connection only.

This is the **only** endpoint. It handles the hot path only:

| Situation | Response |
|---|---|
| IMSI found, profile active | 200 `{"static_ip":"..."}` |
| IMSI found, SIM or IMSI suspended | 403 `{"error":"suspended"}` |
| IMSI found, APN not matched (imsi_apn mode, no wildcard) | 404 `{"error":"apn_not_found"}` |
| IMSI **not in read replica** → first-connection allocates IP successfully | 200 `{"static_ip":"..."}` |
| IMSI **not in read replica** → no range config covers this IMSI | 404 `{"error":"not_found"}` |
| IMSI **not in read replica** → IP pool exhausted | 503 `{"error":"pool_exhausted"}` |
| IMSI **not in read replica** → `subscriber-profile-api` unreachable | 503 `{"error":"upstream_error"}` |
| `imsi` param missing | 400 `{"error":"missing_param","param":"imsi"}` |
| `apn` param missing | 400 `{"error":"missing_param","param":"apn"}` |

**A DB miss is not an error — it is the expected trigger for a first-connection IMSI.**
The lookup service handles this internally by calling `subscriber-profile-api`. The caller
(`aaa-radius-server`) always receives a single response with no awareness of the internal
first-connection exchange.

---

## Request / Response

```
GET /lookup?imsi=278773000002002&apn=smf1.operator.com
Authorization: Bearer <JWT>

HTTP/1.1 200 OK
Content-Type: application/json

{"static_ip": "100.65.120.5"}
```

---

## Internal Resolution Logic

```
Input: imsi ($1), apn ($2)

All operations on READ_REPLICA connection only.

Step 1 — Execute hot-path SQL query:
  SELECT sp.status           AS sim_status,
         sp.ip_resolution,
         si.status           AS imsi_status,
         sa.apn              AS imsi_apn,
         sa.static_ip        AS imsi_static_ip,
         ci.apn              AS iccid_apn,
         ci.static_ip        AS iccid_static_ip
  FROM        imsi2sim       si
  JOIN        sim_profiles   sp ON sp.sim_id  = si.sim_id
  LEFT JOIN   imsi_apn_ips  sa ON sa.imsi     = si.imsi
  LEFT JOIN   sim_apn_ips   ci ON ci.sim_id   = sp.sim_id
  WHERE si.imsi = $1

The two LEFT JOINs produce a Cartesian product: the query returns
`|imsi_apn_ips rows for this IMSI| × |sim_apn_ips rows for this sim_id|` result rows.
If one side has no matching rows the LEFT JOIN still emits one result row with NULLs for
that side's columns. Resolvers iterate the full row vector and inspect only the columns
relevant to their mode — `imsi_apn` / `imsi_static_ip` for IMSI modes, `iccid_apn` /
`iccid_static_ip` for ICCID modes.

Step 2 — If NO rows returned (IMSI absent from read replica):
  → POST {PROVISIONING_URL}/v1/first-connection
    body: {"imsi": $1, "apn": $2, "imei": ..., "use_case_id": ...}
  → 200: return 200 {"static_ip": allocated_ip}   (fresh allocation, first connection)
  → 404: return 404 {"error":"not_found"}          (IMSI not in any range config)
  → 503: return 503 {"error":"pool_exhausted"|"upstream_error"}

Step 3 — Rows returned: apply resolution logic:
  if sim_status != 'active' OR imsi_status != 'active'
    → return 403 {"error":"suspended"}

  switch ip_resolution:
    "iccid":
      row = rows WHERE iccid_apn IS NULL
      return 200 {"static_ip": row.iccid_static_ip}

    "iccid_apn":
      row = rows WHERE iccid_apn = $2          (exact match)
      if not found: row = rows WHERE iccid_apn IS NULL  (wildcard)
      if not found: return 404 {"error":"apn_not_found"}
      return 200 {"static_ip": row.iccid_static_ip}

    "imsi":
      row = rows WHERE imsi_apn IS NULL
      return 200 {"static_ip": row.imsi_static_ip}

    "imsi_apn":
      row = rows WHERE imsi_apn = $2           (exact match)
      if not found: row = rows WHERE imsi_apn IS NULL   (wildcard)
      if not found: return 404 {"error":"apn_not_found"}
      return 200 {"static_ip": row.imsi_static_ip}
```

---

## APN Resolution Detail

The APN is always present in the request but is only used when `ip_resolution` requires it.

| ip_resolution | APN handling |
|---|---|
| `iccid` | Ignored — return the single card-level IP |
| `iccid_apn` | Exact match in `sim_apn_ips.apn`; fallback to `apn=NULL` wildcard |
| `imsi` | Ignored — return the single IMSI-level IP |
| `imsi_apn` | Exact match in `imsi_apn_ips.apn`; fallback to `apn=NULL` wildcard |

---

## Fast Path — ICCID Dual-IMSI Walk-through

This section walks through every combination of the four `ip_resolution` modes against a
single ICCID shared by two IMSIs, each with two APNs — 4 requests × 4 modes = 16 outcomes.

### Scenario: DB layout

```
sim_profiles:  sim_id = 42,  ip_resolution = <see per-mode table below>,  status = active

imsi2sim:
  IMSI-A  →  sim_id = 42
  IMSI-B  →  sim_id = 42

─── imsi_apn_ips (IMSI-level, only populated for imsi / imsi_apn modes) ──────────────────

  mode = imsi:
    IMSI-A │ apn = NULL    │ 100.65.1.10      ← single wildcard row, APN ignored
    IMSI-B │ apn = NULL    │ 100.65.2.10

  mode = imsi_apn:
    IMSI-A │ apn = apn1.net │ 100.65.1.11     ← per-APN rows, no wildcard
    IMSI-A │ apn = apn2.net │ 100.65.1.12
    IMSI-B │ apn = apn1.net │ 100.65.2.11
    IMSI-B │ apn = apn2.net │ 100.65.2.12

─── sim_apn_ips (card-level, only populated for iccid / iccid_apn modes) ─────────────────

  mode = iccid:
    sim_id = 42 │ apn = NULL    │ 100.65.3.10  ← single wildcard row, APN ignored

  mode = iccid_apn:
    sim_id = 42 │ apn = apn1.net │ 100.65.3.11 ← per-APN rows, no wildcard
    sim_id = 42 │ apn = apn2.net │ 100.65.3.12
```

The query always anchors on the incoming IMSI (`WHERE si.imsi = $1`). IMSI-B's request
produces an identical row set structure — only the `imsi_*` values differ.

### Per-mode SQL result rows (shown for an IMSI-A request)

**`imsi` mode** — 1 `imsi_apn_ips` row × 0 `sim_apn_ips` rows → 1 result row

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
NULL      100.65.1.10     NULL       NULL
```

**`imsi_apn` mode** — 2 `imsi_apn_ips` rows × 0 `sim_apn_ips` rows → 2 result rows

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
apn1.net  100.65.1.11     NULL       NULL
apn2.net  100.65.1.12     NULL       NULL
```

**`iccid` mode** — 0 `imsi_apn_ips` rows (→ 1 base row with NULLs) × 1 `sim_apn_ips` row → 1 result row

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
NULL      NULL            NULL       100.65.3.10
```

**`iccid_apn` mode** — 0 `imsi_apn_ips` rows (→ 1 base row with NULLs) × 2 `sim_apn_ips` rows → 2 result rows

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
NULL      NULL            apn1.net   100.65.3.11
NULL      NULL            apn2.net   100.65.3.12
```

### 16-outcome resolution matrix

| Request | `imsi` | `imsi_apn` | `iccid` | `iccid_apn` |
|---|---|---|---|---|
| IMSI-A, apn1.net | 200 `100.65.1.10` (APN ignored) | 200 `100.65.1.11` (exact match) | 200 `100.65.3.10` (APN ignored) | 200 `100.65.3.11` (exact match) |
| IMSI-A, apn2.net | 200 `100.65.1.10` (APN ignored) | 200 `100.65.1.12` (exact match) | 200 `100.65.3.10` (APN ignored) | 200 `100.65.3.12` (exact match) |
| IMSI-B, apn1.net | 200 `100.65.2.10` (APN ignored) | 200 `100.65.2.11` (exact match) | 200 `100.65.3.10` (APN ignored, same card) | 200 `100.65.3.11` (exact match, same card) |
| IMSI-B, apn2.net | 200 `100.65.2.10` (APN ignored) | 200 `100.65.2.12` (exact match) | 200 `100.65.3.10` (APN ignored, same card) | 200 `100.65.3.12` (exact match, same card) |

### Mode notes

**`imsi`** — Resolver picks the single row where `imsi_apn IS NULL`. APN in the request is
completely ignored. IMSI-A and IMSI-B each own a separate row in `imsi_apn_ips` so they
always receive different IPs regardless of the requested APN.

**`imsi_apn`** — Resolver scans for an exact `imsi_apn` match (priority 1), then falls back
to a `imsi_apn IS NULL` wildcard row (priority 2). In this scenario there is no wildcard —
only per-APN rows — so an unrecognised APN returns `404 apn_not_found`. IMSI-A and IMSI-B
maintain independent rows in `imsi_apn_ips`, so the same APN resolves to a different IP for
each IMSI.

**`iccid`** — Resolver picks the single row where `iccid_apn IS NULL`. APN is ignored.
Both IMSI-A and IMSI-B share `sim_id=42`, so both see the same `sim_apn_ips` row and
receive the identical card-level IP `100.65.3.10` regardless of which IMSI or APN is
requested.

**`iccid_apn`** — Resolver scans for an exact `iccid_apn` match, then falls back to a
`iccid_apn IS NULL` wildcard. APN differentiation is at card level: `IMSI-A, apn1.net`
and `IMSI-B, apn1.net` both resolve to `100.65.3.11` because they share the same
`sim_apn_ips` row. An unrecognised APN with no wildcard returns `404 apn_not_found`.

---

## Health Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Returns 200 if process is alive |
| `GET` | `/health/db` | Tests read replica connectivity; returns 200 or 503 |

---

## Environment Variables

All configuration is loaded from environment variables at startup (see `src/Config.h`).

| Variable | Default | Description |
|---|---|---|
| `HTTP_PORT` | `8081` | HTTP API listener port |
| `METRICS_PORT` | `9090` | Prometheus metrics endpoint port |
| `THREAD_COUNT` | `0` (auto) | Drogon event loop thread count; 0 = logical CPU count |
| `DB_HOST` | `localhost` | PostgreSQL read replica hostname |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `aaa` | Database name |
| `DB_USER` | `aaa_ro` | Read-only DB user |
| `DB_PASSWORD` | *(empty)* | DB password — required in production |
| `DB_POOL_SIZE` | `8` | Connections per pod (1–100) |
| `DB_TIMEOUT_SEC` | `1.0` | Query timeout in seconds |
| `JWT_PUBLIC_KEY_PATH` | `/etc/jwt/public.key` | RS256 PEM public key path |
| `JWT_SKIP_VERIFY` | `false` | Set `true` in local dev to bypass JWT validation |
| `PROVISIONING_URL` | `http://subscriber-profile-api:8080` | Base URL for first-connection calls |
| `LOG_LEVEL` | `info` | Spdlog level: `trace` \| `debug` \| `info` \| `warn` \| `error` |

---

## DB Connection Management

The service holds **one connection pool** — the local read replica only.

| Variable | Used for | Default pool size |
|---|---|---|
| `DB_HOST` / `DB_USER` / … | All hot-path lookups | 8 per pod (`DB_POOL_SIZE`) |

No primary connection exists in this service. PgBouncer in transaction-mode sits
between the service and the read replica endpoint.

---

## Service Container Spec

```
┌───────────────────────────────────────────────────────────────┐
│  Container: aaa-lookup-service                                │
│  Language: C++20 / Drogon framework                           │
│  Port: 8081  (HTTP API)                                       │
│  Port: 9090  (Prometheus metrics)                             │
│  Replicas: 3–6 per region                                     │
│  Deployment: co-located with AAA (aaa-radius-server) nodes    │
│  Resources: 512MB RAM / 0.5 CPU per replica                   │
│  DB: read replica only (DB_HOST/DB_USER/DB_PASSWORD)          │
│  No primary DB connection — no writes of any kind             │
└───────────────────────────────────────────────────────────────┘
```

**Why separate from `subscriber-profile-api`:**
- Bulk import jobs in `subscriber-profile-api` are CPU/IO intensive and must not share
  process with the 15ms SLA lookup
- `aaa-lookup-service` scales independently per region, co-located with AAA hardware
- Independent deploy: provisioning API upgrades (including first-connection logic changes)
  cannot cause AAA downtime
- Read-only service is simpler to reason about, audit, and scale

---

## aaa-radius-server Integration (`rlm_rest`) — Single-Call

aaa-radius-server makes **one** call to `GET /lookup`. The lookup service handles
first-connection internally on DB miss. aaa-radius-server never calls
`subscriber-profile-api` directly.

```
# /etc/freeradius/3.0/mods-enabled/rest
rest {
    connect_uri = "https://lookup.aaa-platform.example.com"

    authorize {
        uri = "%{connect_uri}/lookup?imsi=%{User-Name}&apn=%{Called-Station-Id}"
        method = 'get'
    }
}

# /etc/freeradius/3.0/policy.d/aaa_lookup
policy aaa_lookup {
    if (&rest_http_status_code == 200) {
        update reply { Framed-IP-Address := "%{rest:static_ip}" }
        accept
    }
    elsif (&rest_http_status_code == 403) {
        update reply { Reply-Message := "SIM suspended" }
        reject
    }
    elsif (&rest_http_status_code == 404) {
        # IMSI not in any range config — lookup service already attempted first-connection
        update reply { Reply-Message := "Unknown SIM" }
        reject
    }
    elsif (&rest_http_status_code == 503) {
        # Pool exhausted or subscriber-profile-api unreachable (handled inside lookup pod)
        update reply { Reply-Message := "Pool exhausted or provisioning error" }
        reject
    }
    else {
        update reply { Reply-Message := "Internal error" }
        reject
    }
}
```

**RADIUS attribute mapping:**

| RADIUS attribute | Field | Destination |
|---|---|---|
| User-Name (attr 1) | imsi | `GET /lookup?imsi=` |
| Called-Station-Id (attr 30) | apn | `GET /lookup?apn=` |
| 3GPP-IMEISV (26-20) | imei | `GET /lookup?imei=` (forwarded by lookup to first-connection internally) |
| 3GPP-Charging-Characteristics (26-13) | use_case_id | `GET /lookup?use_case_id=` (forwarded internally) |
| Framed-IP-Address (attr 8) | static_ip | Written to Access-Accept from 200 response |

**First-connection is rare.** It fires only on the very first `GET /lookup` for an IMSI
that has no provisioned profile in the read replica. All subsequent connections return 200
directly from the DB cache. The first-connection path adds latency (~50–500 ms) but is
completely transparent to aaa-radius-server.

---

## Multi-Region Architecture

```
         PostgreSQL Primary (primary region)
              │ streaming replication
    ┌─────────┴──────────┐
    ▼                    ▼
EU Read Replica      US Read Replica
    │                    │
    ▼                    ▼
EU aaa-lookup        US aaa-lookup     ← reads only, always local (< 5ms to replica)
EU aaa-radius-server        US aaa-radius-server
    │                    │
    └─────────┬──────────┘
              │ DB miss → first-connection (internal to lookup pod, once per IMSI lifetime)
              ▼
   aaa-lookup-service → subscriber-profile-api (primary region)
                          → writes to PostgreSQL Primary
                          (cross-region write latency ~50–100ms — acceptable, fires once per IMSI lifetime)
```

---

## Observability

Every `GET /lookup` call emits a structured log line:

```json
{
  "ts": "2026-02-26T14:00:00.123Z",
  "imsi_hash": "sha256(imsi)[0:8]",   // partial hash — never log raw IMSI
  "apn": "smf1.operator.com",
  "result": "resolved|not_found|suspended|apn_not_found",
  "ip_resolution": "imsi",
  "latency_ms": 2.4,
  "db": "replica"
}
```

Metrics (Prometheus, exposed on port 9090):
- `aaa_lookup_requests_total` counter by `result` label (`resolved`, `not_found`, `suspended`, `apn_not_found`, `bad_request`, `db_error`)
- `aaa_lookup_duration_seconds` histogram (p50, p95, p99) — full request latency; buckets tuned to 15ms SLA (1ms, 3ms, 5ms, 8ms, 10ms, 15ms, 25ms, 50ms, 100ms, 500ms)
- `aaa_in_flight_requests` gauge — number of concurrent active requests
- `aaa_db_errors_total` counter — DB connection failures and timeouts
- `first_connection_requests_total` counter — DB miss rate; triggers internal first-connection call
- `first_connection_responses_total` counter by `status` (`200`, `404`, `503`, `error`) — outcomes of internal first-connection calls
- `first_connection_duration_seconds` histogram — round-trip latency to `subscriber-profile-api`

Alerts:
- p99 > 15ms for >2 minutes → page on-call (DB hit path SLA)
- `first_connection_requests_total` spike > baseline × 5 → warning (possible range config gap or SIM import)
- `first_connection_responses_total{status=~"503|error"}` > 0 for 2m → critical (`subscriber-profile-api` unreachable)

**Note:** IP pool exhaustion metrics (`pool_exhausted_total`) and bulk job metrics are emitted by
`subscriber-profile-api`. First-connection call counters (`first_connection_requests_total`,
`first_connection_responses_total`) are emitted by **this service**.
