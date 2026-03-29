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
GET /lookup?imsi={imsi}&apn={apn}
```

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
  SELECT sp.sim_id,
         sp.status        AS sim_status,
         sp.ip_resolution,
         si.status        AS imsi_status,
         sa.apn           AS imsi_apn,
         sa.static_ip     AS imsi_static_ip,
         ci.apn           AS iccid_apn,
         ci.static_ip     AS iccid_static_ip
  FROM        imsi2sim    si
  JOIN        sim_profiles sp ON sp.sim_id = si.sim_id
  LEFT JOIN   imsi_apn_ips  sa ON sa.imsi = si.imsi
  LEFT JOIN   sim_apn_ips ci ON ci.sim_id = sp.sim_id
  WHERE si.imsi = $1

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

## Health Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Returns 200 if process is alive |
| `GET` | `/health/db` | Tests read replica connectivity; returns 200 or 503 |

---

## DB Connection Management

The service holds **one connection pool** — the local read replica only.

| Connection | Used for | Pool size |
|---|---|---|
| `READ_REPLICA_URL` | All hot-path lookups | 5–10 per replica |

No primary connection exists in this service. PgBouncer in transaction-mode sits
between the service and the read replica endpoint.

---

## Service Container Spec

```
┌───────────────────────────────────────────────────────────────┐
│  Container: aaa-lookup-service                                │
│  Language: C++20 / Drogon framework                           │
│  Port: 8081                                                   │
│  Replicas: 3–6 per region                                    │
│  Deployment: co-located with AAA (aaa-radius-server) nodes          │
│  Resources: 512MB RAM / 0.5 CPU per replica                  │
│  DB: READ_REPLICA_URL only (local to region)                 │
│  No primary DB connection — no writes of any kind            │
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

Metrics (Prometheus):
- `aaa_lookup_duration_seconds` histogram (p50, p95, p99) — full request latency including first-connection
- `aaa_lookup_requests_total` counter by `result` label (`resolved`, `not_found`, `suspended`, `apn_not_found`, `db_error`)
- `first_connection_requests_total` counter — DB miss rate; triggers internal first-connection call
- `first_connection_responses_total` counter by `status` (`200`, `404`, `503`, `error`) — outcomes of internal first-connection calls

Alerts:
- p99 > 15ms for >2 minutes → page on-call (DB hit path SLA)
- `first_connection_requests_total` spike > baseline × 5 → warning (possible range config gap or SIM import)
- `first_connection_responses_total{status=~"503|error"}` > 0 for 2m → critical (`subscriber-profile-api` unreachable)

**Note:** IP pool exhaustion metrics (`pool_exhausted_total`) and bulk job metrics are emitted by
`subscriber-profile-api`. First-connection call counters (`first_connection_requests_total`,
`first_connection_responses_total`) are emitted by **this service**.
