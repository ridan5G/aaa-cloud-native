# Plan 3 — AAA Lookup Service (`aaa-lookup-service`)

## Role & SLA

The `aaa-lookup-service` is the AAA hot-path service. It is the **only** system the
RADIUS/Diameter nodes talk to for subscriber authentication. Every PGW/GGSN
Access-Request flows through it.

This service is **strictly read-only**. It holds no primary DB connection and performs
no writes under any circumstance. First-connection IP allocation is delegated to
`subscriber-profile-api` via a FreeRADIUS fallback call (see below).

| Property | Value |
|---|---|
| SLA | <15ms p99 end-to-end |
| Callers | FreeRADIUS (`rlm_rest` module) or custom Diameter peer |
| Protocol | REST over HTTPS |
| Scale | 3–6 replicas per region, co-located with AAA nodes |
| DB connection | LOCAL PostgreSQL read replica **only** — no primary connection |
| Writes | None — service is fully read-only |

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
| IMSI **not found** in profiles | 404 `{"error":"not_found"}` |
| `imsi` param missing | 400 `{"error":"missing_param","param":"imsi"}` |
| `apn` param missing | 400 `{"error":"missing_param","param":"apn"}` |

**404 `not_found` is not an error — it is the expected signal for a first-connection IMSI.**
FreeRADIUS handles it by falling through to `subscriber-profile-api` (see FreeRADIUS
configuration below). `aaa-lookup-service` is uninvolved in that allocation.

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
  SELECT sp.device_id,
         sp.status        AS sim_status,
         sp.ip_resolution,
         si.status        AS imsi_status,
         sa.apn           AS imsi_apn,
         sa.static_ip     AS imsi_static_ip,
         ci.apn           AS iccid_apn,
         ci.static_ip     AS iccid_static_ip
  FROM        subscriber_imsis    si
  JOIN        subscriber_profiles sp ON sp.device_id = si.device_id
  LEFT JOIN   subscriber_apn_ips  sa ON sa.imsi = si.imsi
  LEFT JOIN   subscriber_iccid_ips ci ON ci.device_id = sp.device_id
  WHERE si.imsi = $1

Step 2 — If NO rows returned:
  → return 404 {"error":"not_found"}
  (FreeRADIUS fallback calls subscriber-profile-api — not our concern)

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
| `iccid_apn` | Exact match in `subscriber_iccid_ips.apn`; fallback to `apn=NULL` wildcard |
| `imsi` | Ignored — return the single IMSI-level IP |
| `imsi_apn` | Exact match in `subscriber_apn_ips.apn`; fallback to `apn=NULL` wildcard |

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
│  Language: Go or Python (FastAPI) — Go preferred for latency  │
│  Port: 8081                                                   │
│  Replicas: 3–6 per region                                    │
│  Deployment: co-located with AAA (FreeRADIUS) nodes          │
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

## FreeRADIUS Integration (`rlm_rest`) — Two-Stage Configuration

FreeRADIUS calls `aaa-lookup-service` first. On 404, it falls through to
`subscriber-profile-api` for first-connection allocation. The caller gets
a transparent `Framed-IP-Address` in either case.

```
# /etc/freeradius/3.0/mods-enabled/rest
rest {
    connect_uri = "https://lookup.aaa-platform.example.com/v1"

    authorize {
        # Stage 1 — hot-path read (aaa-lookup-service)
        uri = "%{connect_uri}/lookup?imsi=%{User-Name}&apn=%{Called-Station-Id}"
        method = 'get'
        tls { ... }

        # On 200: extract static_ip → Framed-IP-Address → Access-Accept
        # On 403: Access-Reject, Reply-Message = "Subscriber suspended"
        # On 404: fall through to Stage 2 (unlang policy below)
    }
}

# /etc/freeradius/3.0/policy.d/aaa_first_connection
policy aaa_lookup {
    if (&rest_http_status_code == 200) {
        update reply { Framed-IP-Address := "%{rest:static_ip}" }
        accept
    }
    elsif (&rest_http_status_code == 403) {
        update reply { Reply-Message := "Subscriber suspended" }
        reject
    }
    elsif (&rest_http_status_code == 404) {
        # Stage 2 — first-connection allocation (subscriber-profile-api)
        rest_call {
            uri  = "https://provisioning.aaa-platform.example.com/v1/first-connection"
            method = 'post'
            body = '{"imsi":"%{User-Name}","apn":"%{Called-Station-Id}","imei":"%{3GPP-IMEISV}"}'
        }
        if (&rest_http_status_code == 200) {
            update reply { Framed-IP-Address := "%{rest:static_ip}" }
            accept
        }
        elsif (&rest_http_status_code == 404) {
            update reply { Reply-Message := "Unknown subscriber" }
            reject
        }
        elsif (&rest_http_status_code == 503) {
            update reply { Reply-Message := "Pool exhausted" }
            reject
        }
        else {
            update reply { Reply-Message := "Internal error" }
            reject
        }
    }
}
```

**RADIUS attribute mapping:**

| RADIUS attribute | Field | Destination |
|---|---|---|
| User-Name (attr 1) | imsi | `GET /lookup?imsi=` and `POST /first-connection` body |
| Called-Station-Id (attr 30) | apn | `GET /lookup?apn=` and `POST /first-connection` body |
| 3GPP-IMEISV (26-20) | imei | `POST /first-connection` body only |
| Framed-IP-Address (attr 8) | static_ip | Written to Access-Accept from 200 response |

**Stage 2 is rare.** It fires only on the very first connection for an IMSI that has
never been seen before. All subsequent connections for that IMSI return 200 in Stage 1
and Stage 2 is never reached again.

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
EU FreeRADIUS        US FreeRADIUS
    │                    │
    └─────────┬──────────┘
              │ 404 → first-connection only
              ▼
   subscriber-profile-api (primary region)
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
- `lookup_latency_ms` histogram (p50, p95, p99)
- `lookup_result_total` counter by result label
- `not_found_total` counter (triggers Stage 2 in FreeRADIUS — monitor for spikes)

Alerts:
- p99 > 15ms for >2 minutes → page on-call
- `not_found_total` spike > baseline × 5 → alert (possible IMSI range misconfiguration)

**Note:** first-connection allocation metrics (`first_connection_total`, `pool_exhausted_total`)
are emitted by `subscriber-profile-api`, not this service.
