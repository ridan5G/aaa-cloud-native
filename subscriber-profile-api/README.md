# Plan 4 — Provisioning API (`subscriber-profile-api`)

## Role

The provisioning service is the CRUD interface for all SIM data. Operators,
BSS/OSS systems, and migration scripts use it. It is entirely separate from the
AAA hot path — no latency SLA applies, but it must be correct and consistent.

| Property | Value |
|---|---|
| Callers | Operators, BSS/OSS, migration scripts, UI, aaa-radius-server (first-connection fallback) |
| Protocol | REST/HTTPS, JSON |
| Auth | Bearer JWT (OAuth 2.0 client_credentials) |
| Base URL | `https://provisioning.aaa-platform.example.com/v1` |
| DB | PRIMARY only (all reads use primary to avoid stale data post-write) |
| Replicas | 2–4 per deployment (no per-region requirement) |

---

## Container Spec

```
┌───────────────────────────────────────────────────────────────┐
│  Container: subscriber-profile-api                            │
│  Port: 8080                                                   │
│  Replicas: 2–4                                                │
│  DB: PRIMARY_URL only                                         │
│  Bulk jobs: async thread pool within this container           │
│  Resources: 1GB RAM / 1 CPU per replica                      │
└───────────────────────────────────────────────────────────────┘
```

---

## Complete Endpoint Reference

### SIM Profiles

| Method | Path | Description | Success | Notes |
|---|---|---|---|---|
| `POST` | `/profiles` | Create profile | 201 `{sim_id, created_at}` | Validates ip_resolution rules before insert |
| `GET` | `/profiles/{sim_id}` | Get full profile by UUID | 200 full profile JSON | |
| `GET` | `/profiles?iccid={iccid}` | Find by ICCID | 200 or 404 | |
| `GET` | `/profiles?imsi={imsi}` | Find by IMSI | 200 or 404 | Admin/debug use |
| `GET` | `/profiles?account_name={name}&status=active&ip_resolution={mode}&pool_id={uuid}&page=1&limit=100` | Paginated list | 200 `{items[], total, page}` | Max limit=1000; `pool_id` matches profiles with any IP from that pool |
| `PUT` | `/profiles/{sim_id}` | Replace full profile | 200 | All fields replaced; sim_id immutable |
| `PATCH` | `/profiles/{sim_id}` | Partial update (JSON Merge Patch) | 200 | Used to set iccid, change status, update metadata |
| `DELETE` | `/profiles/{sim_id}` | Soft-delete | 204 | Sets status=terminated; data retained |

### IMSI Operations

| Method | Path | Description | Success |
|---|---|---|---|
| `GET` | `/profiles/{sim_id}/imsis` | List all IMSIs on SIM | 200 `[{imsi, status, priority, apn_ips[]}, ...]` |
| `GET` | `/profiles/{sim_id}/imsis/{imsi}` | Get specific IMSI + apn_ips | 200 |
| `POST` | `/profiles/{sim_id}/imsis` | Add IMSI + apn_ips | 201 |
| `PATCH` | `/profiles/{sim_id}/imsis/{imsi}` | Update IMSI status, priority, or apn_ips | 200 |
| `DELETE` | `/profiles/{sim_id}/imsis/{imsi}` | Remove IMSI, its apn_ips, and return pool-managed IPs to pool | 204 |

### IP Release

| Method | Path | Description | Success |
|---|---|---|---|
| `POST` | `/profiles/{sim_id}/release-ips` | Return all pool-managed IPs for the SIM to the pool | 200 `{released_count, ips_released[]}` |

**`POST /profiles/{sim_id}/release-ips`**

Atomically clears all dynamic IP allocations for a SIM profile so the device gets a fresh IP on its next first-connection. IMSI bindings in `imsi2sim` are preserved — only the IP allocations in `imsi_apn_ips` and `sim_apn_ips` are removed and the IPs returned to `ip_pool_available`.

- Covers all IMSIs linked to the SIM, including multi-IMSI SIM siblings
- Static IPs (`pool_id IS NULL`) are never released
- Idempotent: calling with no IPs allocated returns `released_count: 0`
- Returns 404 if `sim_id` is not found or is terminated

**Response (200):**
```json
{
  "released_count": 2,
  "ips_released": [
    {"imsi": "278770000000001", "apn": null,       "ip": "10.0.0.5", "pool_id": "..."},
    {"imsi": "278770000000002", "apn": "internet",  "ip": "10.0.0.6", "pool_id": "..."},
    {"imsi": null,              "apn": "mgmt",      "ip": "10.0.1.1", "pool_id": "..."}
  ]
}
```

> `imsi: null` entries are card-level bindings from `sim_apn_ips` (e.g. `iccid`/`iccid_apn` resolution modes).

**`DELETE /profiles/{sim_id}/imsis/{imsi}` — enhanced behaviour**

In addition to removing the IMSI from `imsi2sim` (which cascades to `imsi_apn_ips`), any pool-managed IPs that were allocated to that IMSI are returned to `ip_pool_available` before deletion. The IMSI is then free to be assigned to a different profile without conflict.

### Routing Domains

A routing domain is a named uniqueness scope for IP addresses. Within one domain no two
pools may have overlapping subnets. `allowed_prefixes` optionally constrains which subnets
may be created in the domain.

| Method | Path | Description | Success | Notes |
|---|---|---|---|---|
| `POST` | `/routing-domains` | Create routing domain | 201 `{id, name}` | 409 if name already exists |
| `GET` | `/routing-domains` | List all routing domains | 200 `{items[], total, page}` | Returns full objects (id, name, description, allowed_prefixes, pool_count) |
| `GET` | `/routing-domains/{id}` | Get routing domain by UUID | 200 | Includes pool_count |
| `PATCH` | `/routing-domains/{id}` | Update name, description, or allowed_prefixes | 200 `{id}` | |
| `DELETE` | `/routing-domains/{id}` | Delete routing domain | 204 or 409 | 409 `domain_in_use` if any pools still reference it |
| `GET` | `/routing-domains/{id}/suggest-cidr?size=N` | Find smallest free CIDR with ≥ N usable IPs | 200 `{suggested_cidr, prefix_len, usable_hosts, …}` | 422 if `allowed_prefixes` is empty; 404 if no free block found |

**`POST /routing-domains` request body:**

```json
{
  "name": "vpn-north",
  "description": "VPN pools for northern region",
  "allowed_prefixes": ["10.0.0.0/8", "172.16.0.0/12"]
}
```

- `description` and `allowed_prefixes` are optional.
- `allowed_prefixes`: CIDR list; if non-empty, all pool subnets in this domain must be contained within one of these prefixes. Empty = unrestricted.

**`GET /routing-domains/{id}/suggest-cidr?size=N` response:**

```json
{
  "suggested_cidr": "10.0.1.0/24",
  "prefix_len": 24,
  "usable_hosts": 254,
  "routing_domain_id": "uuid-...",
  "routing_domain_name": "vpn-north"
}
```

Algorithm: finds the smallest prefix (e.g. `/24` for `size=250`) where no existing pool overlaps, within `allowed_prefixes`. Scans up to 10,000 candidate blocks per prefix.

**Error responses:**
- `422 no_allowed_prefixes` — domain has no `allowed_prefixes` configured (search space undefined).
- `404 no_free_cidr` — no non-overlapping block found within `allowed_prefixes`.
- `409 subnet_outside_allowed_prefixes` — emitted by `POST /pools` when the subnet is not contained within any allowed prefix.

### IP Pools

| Method | Path | Description | Success | Notes |
|---|---|---|---|---|
| `POST` | `/pools` | Create pool + pre-populate ip_pool_available | 201 `{pool_id}` | Synchronous pre-population; rejects with 409 if subnet overlaps another pool in the same routing domain |
| `GET` | `/pools/{pool_id}` | Get pool definition | 200 | Response includes `routing_domain` (name) and `routing_domain_id` (UUID) |
| `GET` | `/pools?account_name={name}&routing_domain={name}&routing_domain_id={uuid}&status=active&page=1&limit=100` | List pools with filters | 200 `{items[], total, page}` | Max limit=1000; filter by name or UUID |
| `GET` | `/pools/{pool_id}/stats` | total / allocated / available IP counts | 200 `{total, allocated, available}` | |
| `PATCH` | `/pools/{pool_id}` | Update name or status | 200 | `routing_domain_id` is immutable after creation |
| `DELETE` | `/pools/{pool_id}` | Delete pool | 204 or 409 | 409 if allocated > 0; check is app-layer only |

**`POST /pools` request body:**

```json
{
  "name":             "Pool-A",
  "account_name":     "Melita",
  "routing_domain":   "vpn-north",
  "routing_domain_id": "uuid-optional",
  "subnet":           "10.0.0.0/24",
  "start_ip":         "10.0.0.1",
  "end_ip":           "10.0.0.254"
}
```

- `routing_domain` (name) is optional; defaults to `"default"` if omitted.
- `routing_domain_id` (UUID) takes priority over `routing_domain` if both are supplied.
- `start_ip` / `end_ip` are optional; server derives them from the subnet if absent.
- On creation the server validates:
  1. Subnet is contained within the domain's `allowed_prefixes` (if non-empty) → `409 subnet_outside_allowed_prefixes`
  2. No overlapping subnet in the same routing domain → `409 pool_overlap`
- If `routing_domain` name does not exist it is **auto-created** with empty `allowed_prefixes` (backward-compatible behaviour for callers that pass only a name).

**Routing Domain concept:**

A routing domain is a named uniqueness scope for IP addresses. Within one routing domain no two pools may contain overlapping IP ranges — the same IP address can only be assigned once within a domain. Pools in different routing domains may share identical or overlapping subnets without conflict (e.g. NAT pools vs. VPN pools using the same RFC 1918 space).

Pool `routing_domain_id` is **immutable** after creation. To move a pool to a different domain, delete and recreate it.

### IMSI Range Configs

| Method | Path | Description | Success |
|---|---|---|---|
| `POST` | `/range-configs` | Create standalone IMSI range config (`iccid_range_id = NULL`) | 201 `{id}` |
| `GET` | `/range-configs/{id}` | Get range config | 200 |
| `GET` | `/range-configs?account_name={name}&status=active&pool_id={uuid}&ip_resolution={mode}` | List with filters | 200 |
| `PATCH` | `/range-configs/{id}` | Update pool_id, status, ip_resolution | 200 |
| `DELETE` | `/range-configs/{id}` | Delete range config | 204 |

### IMSI Range Config — APN Catalog & Pool Overrides

Defines the **APN catalog** for `ip_resolution = "imsi_apn"` or `"iccid_apn"`. Serves
two purposes simultaneously:

1. **APN catalog** — the full list of APNs to provision per SIM. On first-connection,
   IPs are allocated for **every APN in this table** in a single transaction, enabling full
   multi-APN auto-allocation (e.g. 2 IMSIs × 2 APNs = 4 IPs per SIM card with no manual
   provisioning). If the connecting APN is absent from the table it is added using the
   range's default `pool_id`.
2. **Pool routing** — each entry maps an APN to its own IP pool (`pool_id`), enabling
   `apn1 → 10.0.0.0/24`, `apn2 → 11.0.0.0/24` routing for the same IMSI range.

If no entries exist, first-connection falls back to single-APN behavior (backward compatible).

Applies per-slot in Multi-IMSI SIM groups: each `imsi-slot` independently defines its APN
catalog; the sibling pre-provisioning loop calls `_load_apn_pools` per slot so each sibling
IMSI gets IPs for all its APNs in the same transaction.

| Method | Path | Description | Success |
|---|---|---|---|
| `GET` | `/range-configs/{id}/apn-pools` | List APN→pool overrides for this range config | 200 `{items[{id, apn, pool_id}]}` |
| `POST` | `/range-configs/{id}/apn-pools` | Add APN→pool override `{apn, pool_id}` | 201 `{id, apn, pool_id}` |
| `DELETE` | `/range-configs/{id}/apn-pools/{apn}` | Remove override for a specific APN | 204 |

### ICCID Range Configs (Multi-IMSI SIM Provisioning)

Parent table for SIM cards that carry multiple IMSIs. Each `iccid_range_configs` row
defines a range of physical SIM cards; child `imsi_range_configs` rows define the
IMSI ranges for each slot on those cards.

| Method | Path | Description | Success | Notes |
|---|---|---|---|---|
| `POST` | `/iccid-range-configs` | Create ICCID range + validate `imsi_count` | 201 `{id}` | `pool_id` is **optional** — each slot may define its own pool; parent pool is fallback |
| `GET` | `/iccid-range-configs/{id}` | Get ICCID range + all child IMSI ranges | 200 | Nested response includes `imsi_ranges[]` |
| `GET` | `/iccid-range-configs?account_name={name}&status=active&pool_id={uuid}&ip_resolution={mode}` | List with filters | 200 | |
| `PATCH` | `/iccid-range-configs/{id}` | Update description, status, pool_id | 200 | Cannot change f_iccid/t_iccid after creation |
| `DELETE` | `/iccid-range-configs/{id}` | Delete ICCID range + cascade deletes child IMSI ranges | 204 | |
| `POST` | `/iccid-range-configs/{id}/imsi-slots` | Add a child IMSI range (one slot) | 201 `{range_config_id}` | Slot `pool_id` overrides parent; validates cardinality equality |
| `PATCH` | `/iccid-range-configs/{id}/imsi-slots/{slot}` | Update a specific IMSI slot range | 200 | Re-validates cardinality |
| `DELETE` | `/iccid-range-configs/{id}/imsi-slots/{slot}` | Remove a slot | 204 | Allowed only if no profiles allocated from this slot |

### First-Connection Allocation (aaa-radius-server Fallback)

Called by aaa-radius-server when `aaa-lookup-service` returns 404 for an unknown IMSI.
This is the only write path that runs in the AAA authentication flow.

| Method | Path | Description | Success | Error |
|---|---|---|---|---|
| `POST` | `/first-connection` | Allocate IP and permanently create SIM profile | 201 new / 200 reused | 404 not in range; 503 pool exhausted |

**Note:** Returns 201 on first allocation, 200 on idempotent re-request (IMSI already provisioned). aaa-radius-server handles both as Access-Accept.

**Pool resolution order (first-connection):**
1. Slot's own `imsi_range_configs.pool_id` (preferred)
2. Parent `iccid_range_configs.pool_id` (fallback, for multi-IMSI SIM groups)
3. Per-APN pool from `range_config_apn_pools` (replaces step 1/2 per APN for `imsi_apn`/`iccid_apn` modes)

**Multi-APN provisioning (`imsi_apn` / `iccid_apn`):**
All APNs defined in `range_config_apn_pools` are provisioned in a single transaction.
Example: 2 IMSI slots × 2 APNs = 4 IPs per SIM card, all allocated on the first connection
of any slot. Subsequent connections (any IMSI, any defined APN) hit the idempotency path.

**Multi-IMSI SIM — thundering herd protection:**
When any IMSI on a multi-IMSI SIM first connects, ALL sibling IMSIs are pre-provisioned
in the same transaction. Each sibling gets IPs for all its defined APNs from its own slot
pools. On mass failover, every subsequent connection hits the idempotency path — zero write
pressure at failover time.

### Bulk Operations

| Method | Path | Description | Success |
|---|---|---|---|
| `POST` | `/profiles/bulk` | Upsert batch (JSON body or CSV file) | 202 `{job_id, submitted, status_url}` |
| `POST` | `/profiles/bulk-release-ips` | Release IPs for a batch of SIMs | 202 `{job_id, submitted, status_url}` |
| `POST` | `/imsis/bulk-delete` | Remove a batch of IMSIs and return their IPs to pool | 202 `{job_id, submitted, status_url}` |
| `GET` | `/jobs/{job_id}` | Poll bulk job status | 200 `{status, processed, failed, errors[]}` |

**`POST /profiles/bulk-release-ips`**

Accepts a JSON body with a list of `sim_id`s, or filter criteria to select SIMs. For each SIM, runs the same logic as `POST /profiles/{sim_id}/release-ips` (returns all pool-managed IPs to `ip_pool_available`, clears `imsi_apn_ips` and `sim_apn_ips`). Profiles without allocated IPs are silently skipped (counted as processed).

Request body (select by explicit list):
```json
{ "sim_ids": ["uuid1", "uuid2", "..."] }
```

Request body (select by filter — releases IPs for all matching active profiles):
```json
{ "account_name": "Melita", "pool_id": "uuid-of-pool" }
```

Either `sim_ids` or at least one filter field (`account_name`, `pool_id`) must be provided.

**`POST /imsis/bulk-delete`**

Accepts a JSON body with a list of IMSI strings, or a CSV file (single column: `imsi`). For each IMSI, runs the same logic as `DELETE /profiles/{sim_id}/imsis/{imsi}` — unlinks the IMSI from its SIM and returns its pool-managed IPs to `ip_pool_available`. IMSIs not found are recorded as errors but do not abort the job.

Request body (JSON):
```json
{ "imsis": ["278770000000001", "278770000000002"] }
```

CSV upload (`Content-Type: multipart/form-data`):
```csv
imsi
278770000000001
278770000000002
```

Response (both endpoints, 202):
```json
{
  "job_id": "bulk-job-uuid",
  "submitted": 1500,
  "status_url": "/v1/jobs/bulk-job-uuid"
}
```

Job result (via `GET /jobs/{job_id}`):
```json
{
  "job_id": "bulk-job-uuid",
  "status": "completed",
  "processed": 1498,
  "failed": 2,
  "errors": [
    {"index": 42,  "value": "278770000000099", "error": "not_found"},
    {"index": 107, "value": "278770000000200", "error": "not_found"}
  ]
}
```

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/health/db` | DB primary connectivity |

---

## Validation Rules (enforced at API layer)

These rules are applied before any DB write. Validation errors return 400.

| Rule | Error |
|---|---|
| `imsi` must be exactly 15 digits | validation_failed, field=imsi |
| `iccid` must be 19–20 digits (when not null) | validation_failed, field=iccid |
| `ip_resolution` must be one of the 6 enum values | validation_failed, field=ip_resolution |
| Profile A: `iccid_ips` must have exactly 1 entry with no `apn` field | validation_failed |
| Profile B: each IMSI must have exactly 1 `apn_ips` entry with no `apn` field | validation_failed |
| Profile C: each IMSI may have multiple `apn_ips`; `apn` values must be distinct | validation_failed |
| PATCH changing `ip_resolution` to imsi_apn without supplying `apn` fields | validation_failed |
| `pool_id` in iccid_ips or apn_ips must exist in `ip_pools` | validation_failed, field=pool_id |
| `POST /pools`: subnet must not overlap with any existing pool in the same routing domain | 409 `pool_overlap` (see example below) |
| `POST /pools`: `routing_domain` must not be empty if provided | validation_failed, field=routing_domain |
| `POST /pools`: subnet must be contained within the domain's `allowed_prefixes` (when non-empty) | 409 `subnet_outside_allowed_prefixes` |
| `POST /routing-domains`: `name` must not be empty | validation_failed, field=name |
| `POST /routing-domains`: each entry in `allowed_prefixes` must be valid CIDR notation | validation_failed, field=allowed_prefixes |
| `DELETE /routing-domains/{id}`: cannot delete if pools exist in the domain | 409 `domain_in_use` |
| `GET /routing-domains/{id}/suggest-cidr`: domain must have non-empty `allowed_prefixes` | 422 `no_allowed_prefixes` |
| `f_imsi` must be ≤ `t_imsi` in range-configs | validation_failed |
| `f_iccid` must be ≤ `t_iccid` in iccid-range-configs | validation_failed |
| `f_iccid` and `t_iccid` must be 19–20 digits | validation_failed |
| `imsi_count` must be 1–10 | validation_failed, field=imsi_count |
| `POST /iccid-range-configs`: `pool_id` is optional; if provided, must exist in `ip_pools` | validation_failed, field=pool_id |
| `POST /range-configs/{id}/apn-pools`: `apn` must not be empty | validation_failed, field=apn |
| `POST /range-configs/{id}/apn-pools`: `pool_id` must exist in `ip_pools` | validation_failed, field=pool_id |
| `POST /range-configs/{id}/apn-pools`: duplicate `apn` for same range_config_id not allowed | validation_failed, field=apn |
| All child IMSI slot ranges for the same `iccid_range_id` must have **identical cardinality**: `t_imsi - f_imsi` must equal `t_iccid - f_iccid` for every slot | validation_failed, detail: "imsi range cardinality N does not match iccid range cardinality M" |
| Child IMSI slot `ip_resolution` must match its parent `iccid_range_configs.ip_resolution` | validation_failed, detail: "imsi slot ip_resolution 'imsi_apn' conflicts with parent iccid range ip_resolution 'imsi'" |
| `imsi_slot` must be unique within a `iccid_range_id` group (enforced by DB UNIQUE constraint too) | validation_failed, field=imsi_slot |
| `POST /first-connection`: `imsi` must be exactly 15 digits | 400 |
| `POST /first-connection`: `apn` must be present | 400 |
| `POST /first-connection`: `use_case_id` is optional; included in logs when present | — |

---

## Resolution Reference — ICCID Dual-IMSI (16 outcomes)

The table below shows the static IP returned by `GET /lookup` for every combination of
`ip_resolution` mode, IMSI, and APN when one ICCID is shared by two IMSIs (each with two
configured APNs). Operators provisioning profiles via this API should use it to confirm
the expected lookup behaviour before activating SIMs.

### DB layout for this scenario

```
sim_profiles:  sim_id = 42,  ip_resolution = <see per-mode table below>,  status = active

imsi2sim:
  IMSI-A  →  sim_id = 42
  IMSI-B  →  sim_id = 42

─── imsi_apn_ips (only populated for imsi / imsi_apn modes) ─────────────────────────────

  mode = imsi:
    IMSI-A │ apn = NULL    │ 100.65.1.10      ← single wildcard row, APN ignored
    IMSI-B │ apn = NULL    │ 100.65.2.10

  mode = imsi_apn:
    IMSI-A │ apn = apn1.net │ 100.65.1.11     ← per-APN rows, no wildcard
    IMSI-A │ apn = apn2.net │ 100.65.1.12
    IMSI-B │ apn = apn1.net │ 100.65.2.11
    IMSI-B │ apn = apn2.net │ 100.65.2.12

─── sim_apn_ips (only populated for iccid / iccid_apn modes) ────────────────────────────

  mode = iccid:
    sim_id = 42 │ apn = NULL    │ 100.65.3.10  ← single wildcard row, APN ignored

  mode = iccid_apn:
    sim_id = 42 │ apn = apn1.net │ 100.65.3.11 ← per-APN rows, no wildcard
    sim_id = 42 │ apn = apn2.net │ 100.65.3.12
```

### 16-outcome matrix (4 requests × 4 modes)

| Request | `imsi` | `imsi_apn` | `iccid` | `iccid_apn` |
|---|---|---|---|---|
| IMSI-A, apn1.net | 200 `100.65.1.10` (APN ignored) | 200 `100.65.1.11` (exact match) | 200 `100.65.3.10` (APN ignored) | 200 `100.65.3.11` (exact match) |
| IMSI-A, apn2.net | 200 `100.65.1.10` (APN ignored) | 200 `100.65.1.12` (exact match) | 200 `100.65.3.10` (APN ignored) | 200 `100.65.3.12` (exact match) |
| IMSI-B, apn1.net | 200 `100.65.2.10` (APN ignored) | 200 `100.65.2.11` (exact match) | 200 `100.65.3.10` (APN ignored, same card) | 200 `100.65.3.11` (exact match, same card) |
| IMSI-B, apn2.net | 200 `100.65.2.10` (APN ignored) | 200 `100.65.2.12` (exact match) | 200 `100.65.3.10` (APN ignored, same card) | 200 `100.65.3.12` (exact match, same card) |

### Mode notes

**`imsi`** — One row per IMSI in `imsi_apn_ips` with `apn=NULL`. APN is ignored. IMSI-A
and IMSI-B receive different IPs because each owns its own row.

**`imsi_apn`** — One row per IMSI×APN in `imsi_apn_ips`. Resolver tries exact APN match
first; falls back to `apn=NULL` wildcard if present. No wildcard in this scenario —
an unconfigured APN returns `404 apn_not_found`. IMSI-A and IMSI-B are independent.

**`iccid`** — One row in `sim_apn_ips` with `apn=NULL`. APN is ignored. Both IMSI-A and
IMSI-B share `sim_id=42`, so both receive the identical card-level IP.

**`iccid_apn`** — One row per APN in `sim_apn_ips`. Resolver tries exact APN match first;
falls back to `apn=NULL` wildcard. Both IMSI-A and IMSI-B share the same `sim_apn_ips`
rows — `IMSI-A, apn1.net` and `IMSI-B, apn1.net` resolve to the same IP.

---

## Request / Response Examples

### Create Routing Domain

```http
POST /v1/routing-domains
Content-Type: application/json

{
  "name": "vpn-north",
  "description": "VPN pools for northern region",
  "allowed_prefixes": ["10.0.0.0/8"]
}

HTTP/1.1 201 Created
{ "id": "d1e2f3a4-b5c6-7890-abcd-ef1234567890", "name": "vpn-north" }
```

### Suggest Free CIDR

```http
GET /v1/routing-domains/d1e2f3a4-b5c6-7890-abcd-ef1234567890/suggest-cidr?size=250

HTTP/1.1 200 OK
{
  "suggested_cidr": "10.0.0.0/24",
  "prefix_len": 24,
  "usable_hosts": 254,
  "routing_domain_id": "d1e2f3a4-b5c6-7890-abcd-ef1234567890",
  "routing_domain_name": "vpn-north"
}

# If allowed_prefixes is empty:
HTTP/1.1 422 Unprocessable Entity
{ "error": "no_allowed_prefixes", "detail": "Configure allowed_prefixes on this routing domain before using suggest-cidr..." }
```

### Create Pool (with routing domain)

```http
POST /v1/pools
Content-Type: application/json

{
  "name":              "VPN-North-A",
  "account_name":      "Melita",
  "routing_domain_id": "d1e2f3a4-b5c6-7890-abcd-ef1234567890",
  "subnet":            "10.0.0.0/24"
}

HTTP/1.1 201 Created
{ "pool_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890" }
```

### Subnet Outside Allowed Prefixes Error (409)

```http
POST /v1/pools
Content-Type: application/json

{
  "name":              "Bad-Pool",
  "routing_domain_id": "d1e2f3a4-b5c6-7890-abcd-ef1234567890",
  "subnet":            "192.168.1.0/24"
}

HTTP/1.1 409 Conflict
{
  "error": "subnet_outside_allowed_prefixes",
  "detail": "Subnet 192.168.1.0/24 is not within the allowed prefixes for this routing domain: ['10.0.0.0/8']",
  "allowed_prefixes": ["10.0.0.0/8"]
}
```

### Pool Overlap Error (409)

```http
POST /v1/pools
Content-Type: application/json

{
  "pool_name":      "VPN-North-B",
  "routing_domain": "vpn-north",
  "subnet":         "10.0.0.128/25"
}

HTTP/1.1 409 Conflict
{
  "error": "pool_overlap",
  "detail": "Subnet 10.0.0.128/25 overlaps with pool 'VPN-North-A' (10.0.0.0/24) in routing domain 'vpn-north'",
  "conflicting_pool_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

---

### Create Profile B (imsi mode, no ICCID yet)

```http
POST /v1/profiles
Content-Type: application/json

{
  "iccid": null,
  "account_name": "Melita",
  "status": "active",
  "ip_resolution": "imsi",
  "imsis": [
    {
      "imsi": "278773000002002",
      "apn_ips": [{ "static_ip": "100.65.120.5", "pool_id": "pool-uuid-abc", "pool_name": "pool1" }]
    }
  ],
  "metadata": { "tags": ["iot"] }
}

HTTP/1.1 201 Created
{ "sim_id": "550e8400-e29b-41d4-a716-446655440000", "created_at": "2026-02-26T10:00:00Z" }
```

### Enrich ICCID

```http
PATCH /v1/profiles/550e8400-e29b-41d4-a716-446655440000
Content-Type: application/json

{ "iccid": "8944501012345678901" }

HTTP/1.1 200 OK
```

### Add IMSI

```http
POST /v1/profiles/550e8400-e29b-41d4-a716-446655440000/imsis
Content-Type: application/json

{
  "imsi": "278773000002005",
  "priority": 2,
  "apn_ips": [{ "static_ip": "100.65.120.6", "pool_id": "pool-uuid-abc", "pool_name": "pool1" }]
}

HTTP/1.1 201 Created
```

### Bulk Upsert (JSON body)

```http
POST /v1/profiles/bulk
Content-Type: application/json

{
  "mode": "upsert",
  "profiles": [ ...up to 100K SIM profile objects... ]
}

HTTP/1.1 202 Accepted
{
  "job_id": "bulk-job-uuid-456",
  "submitted": 100000,
  "status_url": "/v1/jobs/bulk-job-uuid-456"
}
```

### Bulk Upsert (CSV upload)

```http
POST /v1/profiles/bulk
Content-Type: multipart/form-data; boundary=...

--boundary
Content-Disposition: form-data; name="file"; filename="batch.csv"
Content-Type: text/csv

sim_id,iccid,account_name,status,ip_resolution,...
...

HTTP/1.1 202 Accepted
{ "job_id": "bulk-job-uuid-789", "submitted": 5000, "status_url": "/v1/jobs/bulk-job-uuid-789" }
```

### Poll Job Status

```http
GET /v1/jobs/bulk-job-uuid-456

HTTP/1.1 200 OK
{
  "job_id": "bulk-job-uuid-456",
  "status": "completed",
  "processed": 99998,
  "failed": 2,
  "errors": [
    { "row": 1042, "field": "imsi", "message": "must be 15 digits", "value": "27877300000200" },
    { "row": 5518, "field": "iccid", "message": "must be 19-20 digits", "value": "894450101" }
  ]
}
```

### Create ICCID Range Config (Multi-IMSI SIM batch)

```http
POST /v1/iccid-range-configs
Content-Type: application/json

{
  "account_name": "Melita",
  "f_iccid": "8944501010000000000",
  "t_iccid": "8944501010000999999",
  "pool_id": "pool-uuid-abc",
  "ip_resolution": "imsi",
  "imsi_count": 2,
  "description": "Melita dual-IMSI IoT batch 2026"
}

HTTP/1.1 201 Created
{ "id": 1 }
```

### Add IMSI Slots to ICCID Range

```http
POST /v1/iccid-range-configs/1/imsi-slots
Content-Type: application/json

{
  "f_imsi": "278770000000000",
  "t_imsi": "278770000999999",
  "pool_id": "pool-uuid-abc",
  "ip_resolution": "imsi",
  "imsi_slot": 1,
  "description": "Melita primary IMSI slot"
}

HTTP/1.1 201 Created
{ "range_config_id": 42 }
```

```http
POST /v1/iccid-range-configs/1/imsi-slots
Content-Type: application/json

{
  "f_imsi": "278771000000000",
  "t_imsi": "278771000999999",
  "pool_id": "pool-uuid-abc",
  "ip_resolution": "imsi",
  "imsi_slot": 2,
  "description": "Melita secondary IMSI slot"
}
# Cardinality check: t_imsi - f_imsi = 999999 = t_iccid - f_iccid ✓

HTTP/1.1 201 Created
{ "range_config_id": 43 }
```

```http
# Cardinality mismatch example:
POST /v1/iccid-range-configs/1/imsi-slots
{ "f_imsi": "278772000000000", "t_imsi": "278772000099999", ... }
# t_imsi - f_imsi = 99999 ≠ 999999 (iccid range cardinality)

HTTP/1.1 400 Bad Request
{
  "error": "validation_failed",
  "details": [{
    "field": "imsi_range",
    "message": "cardinality 100000 does not match iccid range cardinality 1000000"
  }]
}
```

### First-Connection Allocation (aaa-radius-server → provisioning)

```http
POST /v1/first-connection
Content-Type: application/json

{ "imsi": "278770000000042", "apn": "internet.operator.com", "imei": "865914030178379" }

HTTP/1.1 201 Created       ← new allocation
{ "sim_id": "550e8400-e29b-41d4-a716-446655440000", "static_ip": "100.65.120.5" }

HTTP/1.1 200 OK            ← IMSI already provisioned (idempotent re-request)
{ "sim_id": "550e8400-e29b-41d4-a716-446655440000", "static_ip": "100.65.120.5" }

# IMSI not in any active range config:
HTTP/1.1 404 Not Found
{ "error": "not_found" }

# Pool exhausted:
HTTP/1.1 503 Service Unavailable
{ "error": "pool_exhausted", "pool_id": "pool-uuid-abc" }
```

For the multi-IMSI SIM case above (`imsi_slot` match):
- `278770000000042` falls in slot-1 range (`278770000000000`–`278770000999999`)
- Offset = 42
- Derived ICCID = `8944501010000000000` + 42 = `8944501010000000042`
- Profile created with real ICCID; sibling IMSI `278771000000042` (slot 2) pre-provisioned
  in the same transaction — its next connection hits the fast path immediately

```json
// 400 — Validation error
{
  "error": "validation_failed",
  "details": [
    { "field": "imsi", "message": "must be 15 digits" },
    { "field": "ip_resolution", "message": "required field missing" }
  ]
}

// 404 — Not found
{ "error": "not_found", "resource": "subscriber_profile", "sim_id": "..." }

// 409 — ICCID conflict
{ "error": "iccid_conflict", "iccid": "8944501012345678901", "existing_sim_id": "..." }

// 409 — IMSI conflict
{ "error": "imsi_conflict", "imsi": "278773000002002", "existing_sim_id": "..." }

// 409 — Pool in use (on pool DELETE)
{ "error": "pool_in_use", "pool_id": "pool-uuid-abc", "allocated": 1234 }
```

---

## HTTP Status Codes

| Code | Meaning |
|---|---|
| 200 | OK — GET, PATCH, PUT |
| 201 | Created — POST |
| 202 | Accepted — async bulk job started |
| 204 | No Content — DELETE |
| 400 | Bad Request — validation error |
| 401 | Unauthorized — invalid or missing JWT |
| 403 | Forbidden — JWT scope doesn't cover the requested account |
| 404 | Not Found |
| 409 | Conflict — duplicate ICCID, IMSI, or pool in use |
| 429 | Too Many Requests — rate limit |
| 500 | Internal Server Error |

---

## Bulk Job Processing — Internals

Bulk jobs run as an async thread pool within `subscriber-profile-api`.
No separate worker process or message queue is needed at this scale.

```
1. POST /profiles/bulk → validate top-level shape → write job record (status=queued)
                       → return 202 immediately
2. Thread pool picks up job → processes profiles in batches of 1000
   For each batch:
     a. Validate each profile (same rules as single POST)
     b. INSERT INTO sim_profiles ON CONFLICT (sim_id) DO UPDATE
     c. INSERT INTO imsi2sim ON CONFLICT (imsi) DO NOTHING
     d. INSERT INTO imsi_apn_ips ON CONFLICT DO NOTHING
     e. Accumulate per-row errors (do not abort the whole job on a single bad row)
3. Update job record: status=completed, processed=N, failed=M, errors=[...]
4. GET /jobs/{job_id} reads job record
```

**CSV bulk upload:** The CSV is parsed server-side into the same profile objects as the JSON path.
Required CSV columns:

```
iccid, account_name, status, ip_resolution, imsi, apn, static_ip, pool_id
```

**One IMSI per row. Rows sharing the same non-empty `iccid` are merged into a single profile.**
Each row contributes one IMSI (and its IP entry) to that card. This is the canonical format for
all import scenarios — multi-IMSI cards are represented as consecutive rows with the same ICCID.

Rules:
- Rows with the same `iccid` are merged: the first row sets `account_name`, `status`,
  `ip_resolution`; subsequent rows add their IMSI to the same profile.
- `imsi_apn` / `iccid_apn` multi-APN profiles: one row per IMSI per APN, all sharing the same `iccid`.
- The `apn` column is used only for `imsi_apn` / `iccid_apn` modes; leave blank for `imsi` / `iccid`.
- `static_ip` and `pool_id` may be blank for auto-allocated SIMs (IP assigned on first
  RADIUS connect via range config).
- Rows without an `iccid` are never merged — each becomes its own profile.

Example — dual-IMSI card (`iccid_apn` mode):
```
iccid,             account_name, status, ip_resolution, imsi,            apn,      static_ip, pool_id
8935501234567890,  Melita,       active, iccid_apn,     123456789012345, internet, 10.0.0.1,  <uuid>
8935501234567890,  Melita,       active, iccid_apn,     123456789012346, internet, 10.0.0.2,  <uuid>
```
→ produces **one** profile with two IMSIs.

---

## First-Connection Allocation — Internals

`POST /first-connection` is the write path that runs in the AAA flow when aaa-radius-server
falls through from `aaa-lookup-service`'s 404. It owns the full allocation transaction
described in the DB plan.

The `ip_resolution` that governs how the profile is created and where the IP is stored
comes **entirely from the range config**, not from the request body. aaa-radius-server passes
`imsi`, `apn`, `imei`, and optionally `use_case_id` (sourced from 3GPP-Charging-Characteristics VSA).

```
1. Validate imsi (15 digits) and apn (present)

2. Idempotency: check if IMSI is already provisioned
   SELECT i.sim_id::text, sp.ip_resolution
   FROM imsi2sim i
   JOIN sim_profiles sp ON sp.sim_id = i.sim_id
   WHERE i.imsi = $imsi

   → Found: query the table that matches the profile's current ip_resolution
     (join ensures stale rows in the wrong table are ignored after a mode switch)

     IF ip_resolution IN ('imsi', 'imsi_apn'):
       SELECT host(static_ip) FROM imsi_apn_ips
       WHERE imsi = $imsi AND (apn = $apn OR apn IS NULL)
       ORDER BY apn NULLS LAST LIMIT 1

     ELSE -- iccid, iccid_apn:
       SELECT host(static_ip) FROM sim_apn_ips
       WHERE sim_id = $sim_id AND (apn = $apn OR apn IS NULL)
       ORDER BY apn NULLS LAST LIMIT 1

     → Return 200 {sim_id, static_ip}

3. Look up imsi_range_configs:
   - Standalone path (iccid_range_id IS NULL):
       SELECT irc.pool_id, irc.ip_resolution, irc.account_name, irc.iccid_range_id
       FROM imsi_range_configs irc
       WHERE f_imsi <= $imsi AND t_imsi >= $imsi AND status='active'
       ORDER BY f_imsi LIMIT 1
     ip_resolution → from imsi_range_configs directly

   - Multi-IMSI path (iccid_range_id IS NOT NULL):
       SELECT irc.f_imsi, irc.iccid_range_id, irc.imsi_slot,
              ir.pool_id, ir.ip_resolution, ir.account_name, ir.f_iccid
       FROM imsi_range_configs irc
       JOIN iccid_range_configs ir ON ir.id = irc.iccid_range_id
       WHERE irc.f_imsi <= $imsi AND irc.t_imsi >= $imsi AND irc.status='active'
       ORDER BY irc.f_imsi LIMIT 1
     ip_resolution → from iccid_range_configs (parent), never from child row

   → Not found: return 404

4. Branch on iccid_range_id:

   ── NULL (single-IMSI SIM) ──────────────────────────────────────────────────
   BEGIN
     Claim IP from ip_pool_available (SELECT FOR UPDATE SKIP LOCKED)
     → No IP: ROLLBACK, return 503

     INSERT sim_profiles (iccid=NULL, account_name, ip_resolution=$ip_resolution)
     INSERT imsi2sim (imsi, sim_id, priority=1)

     IF ip_resolution IN ('imsi', 'imsi_apn'):
       INSERT imsi_apn_ips (
         imsi,
         apn = NULL if 'imsi' else $apn,   -- store incoming APN for imsi_apn mode
         static_ip = $allocated_ip,
         pool_id
       )
     ELSIF ip_resolution IN ('iccid', 'iccid_apn'):
       INSERT sim_apn_ips (
         sim_id,
         apn = NULL if 'iccid' else $apn,
         static_ip = $allocated_ip,
         pool_id
       )
   COMMIT
   Return 200 {"static_ip": $allocated_ip}

   ── NOT NULL (Multi-IMSI SIM) ───────────────────────────────────────────────
   offset       = numeric($imsi) - numeric(f_imsi)
   derived_iccid = zero-pad(numeric(f_iccid) + offset, len(f_iccid))

   BEGIN
     SELECT sim_id FROM sim_profiles
     WHERE iccid = $derived_iccid FOR UPDATE

     IF found (another slot already connected first):
       Reuse existing sim_id and existing static_ip from the card
       INSERT imsi2sim (imsi, sim_id, priority=imsi_slot) ON CONFLICT DO NOTHING
       IF ip_resolution IN ('imsi', 'imsi_apn'):
         INSERT imsi_apn_ips (imsi, apn=NULL/'$apn', existing_ip) ON CONFLICT DO NOTHING
       -- iccid/iccid_apn: sim_apn_ips already covers all IMSIs on this card

     ELSE (first slot to connect for this card):
       Claim one IP from ip_pool_available (SELECT FOR UPDATE SKIP LOCKED)
       → No IP: ROLLBACK, return 503

       INSERT sim_profiles (iccid=derived_iccid, account_name,
                                ip_resolution=$ip_resolution)

       IF ip_resolution IN ('iccid', 'iccid_apn'):
         INSERT sim_apn_ips (sim_id, apn=NULL/'$apn', static_ip, pool_id)
         -- One card-level row covers all sibling IMSIs; no per-IMSI rows needed

       FOR each sibling slot in imsi_range_configs WHERE iccid_range_id = X:
         sibling_imsi = zero-pad(numeric(sibling.f_imsi) + offset, 15)
         INSERT imsi2sim (sibling_imsi, sim_id, priority=slot) ON CONFLICT DO NOTHING
         IF ip_resolution IN ('imsi', 'imsi_apn'):
           -- Load APN catalog for this sibling's slot; each slot has independent overrides.
           sibling_apn_pools = _load_apn_pools(sibling.id, sibling_base_pool, ip_resolution, $apn)
           FOR each (apn_val, apn_pool) in sibling_apn_pools:
             sibling_ip = CLAIM IP from apn_pool (SELECT FOR UPDATE SKIP LOCKED)
             → No IP: ROLLBACK, return 503
             INSERT imsi_apn_ips (sibling_imsi, apn_val, sibling_ip, apn_pool)
             ON CONFLICT DO NOTHING
         -- iccid / iccid_apn: sim_apn_ips rows already inserted above cover all IMSIs on the card
   COMMIT
   Return 200 {"static_ip": $allocated_ip or $existing_ip}
```

**`ip_resolution` routing summary:**

| `ip_resolution` (from range config) | `apn` stored | IP table | Card vs IMSI |
|---|---|---|---|
| `imsi` | NULL (wildcard) | `imsi_apn_ips` | Per IMSI |
| `imsi_apn` | APN from Access-Request | `imsi_apn_ips` | Per IMSI |
| `iccid` | NULL (wildcard) | `sim_apn_ips` | Card-level (shared by all IMSIs) |
| `iccid_apn` | APN from Access-Request | `sim_apn_ips` | Card-level |

**Concurrency safety:** `SELECT ... FOR UPDATE` on the ICCID check prevents two concurrent
connections from the same multi-IMSI card racing to create duplicate profiles.

---

## Observability

Structured logs per request:
```json
{
  "ts": "...", "method": "POST", "path": "/profiles",
  "status": 201, "latency_ms": 8.2,
  "sim_id": "550e8400-...", "account_name": "Melita"
}
```

First-connection log:
```json
{
  "ts": "...", "path": "/first-connection",
  "imsi": "123456789012345",
  "result": "allocated|reused|not_found|pool_exhausted",
  "multi_imsi": true,
  "siblings_provisioned": 2,
  "pool_id": "pool-uuid-abc",
  "apns_provisioned": 2,
  "use_case_id": "pgw1",
  "latency_ms": 18.3
}
```
Note: `use_case_id` is omitted from the log when not provided by the caller. IMSI is logged as
the full 15-digit number for operator readability.

Metrics (Prometheus):
- `api_request_duration_ms` histogram by method + path
- `first_connection_total` counter by result label (allocated / reused / not_found / pool_exhausted)
- `pool_exhausted_total` counter by pool_id — alert if rate > 0
- `multi_imsi_siblings_provisioned_total` counter
- `bulk_job_profiles_total` counter (processed + failed)
- `bulk_job_duration_seconds` histogram

Alerts:
- `pool_exhausted_total` rate > 0 for any pool → alert (pool needs expansion)
- `first_connection_total{result="not_found"}` spike → alert (IMSI range misconfiguration)

---

## Migration Script Integration

The migration script (Perl/Python) produces 4 CSV files that are loaded via the bulk API
or directly via `COPY` into PostgreSQL staging tables. The provisioning API does not need
to know about migration specifically — it just receives the same POST/bulk calls as any
other provisioning source.

The `PATCH /profiles/{sim_id}` endpoint is the mechanism for all post-migration
ICCID enrichment and APN label renaming.
