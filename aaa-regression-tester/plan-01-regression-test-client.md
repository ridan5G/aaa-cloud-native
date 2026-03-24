# Plan 1 — Regression Test Client

## Overview

A standalone test suite (`aaa-regression-tester`) that exercises every REST API endpoint
across both services and verifies correct behaviour for all IP resolution modes,
dynamic first-connection allocation, multi-IMSI SIM cards, RADIUS authentication,
bulk operations, export/search, and failure scenarios.

**Technology:** Python 3.11 · `pytest` · `httpx` (sync client, class-scoped fixtures)
**Target environments:**
- In-cluster: Kubernetes Job via `make test` (primary)
- Local: Docker Compose (`docker-compose.test.yml`) against the same containers
**Output:** JUnit XML (`/app/results/results.xml`) · console pass/fail summary · Prometheus Pushgateway metrics

**Current suite result: 159 passed · 0 failed · 0 skipped · ~80 s**

---

## Repository Layout

```
aaa-regression-tester/
├── conftest.py                       # base URLs, JWT/RADIUS env, shared fixtures & helpers
├── pytest.ini                        # markers, timeout=60, test path config
├── requirements.txt                  # pytest, httpx, pytest-asyncio, pytest-timeout
├── run_all.sh                        # executes full suite, pushes metrics to Pushgateway
├── docker-compose.test.yml           # local stack: PostgreSQL 15 + both services
│
├── fixtures/
│   ├── pools.py                      # create_pool / delete_pool / get_pool_stats helpers
│   ├── range_configs.py              # create_range_config / delete_range_config helpers
│   ├── profiles.py                   # create_profile_imsi / _imsi_apn / _iccid / delete_profile
│   └── radius.py                     # RadiusClient, build_access_request, parse_response
│
├── test_01_pools.py                  # IP pool CRUD + stats                      [ 8 tests]
├── test_02_range_configs.py          # IMSI range config CRUD                    [ 8 tests]
├── test_03_profiles_a.py             # Profile A: ip_resolution=iccid            [ 9 tests]
├── test_04_profiles_b.py             # Profile B: ip_resolution=imsi             [ 9 tests]
├── test_05_profiles_c.py             # Profile C: ip_resolution=imsi_apn         [ 9 tests]
├── test_06_imsi_ops.py               # Add / remove IMSI, per-IMSI suspend       [ 8 tests]
├── test_07_dynamic_alloc.py          # First-connection single-IMSI baseline      [ 9 tests]
├── test_07b_dynamic_alloc_modes.py   # First-connection all 7 allocation modes   [25 tests]
├── test_07c_release_ips.py           # IP release / IMSI detach + IP return       [ 7 tests]
├── test_08_bulk.py                   # Bulk upsert via POST /profiles/bulk        [ 8 tests]
├── test_10_errors.py                 # Validation, 404, 409, 503, auth errors    [16 tests]
├── test_12_radius.py                 # End-to-end RADIUS authentication          [14 tests]
├── test_13_export_and_ip_search.py   # Export CSV + IP filter + terminated SIMs  [13 tests]
└── test_14_export_delete_reprovision.py  # Export → delete → bulk re-import (4 SIM types) [16 tests]
```

> **Not implemented:** `test_09_migration.py` (migration script tests — deferred) ·
> `test_11_performance.py` (latency assertions under load — deferred).

---

## Environment & Configuration

```python
# conftest.py — key env vars

PROVISION_BASE = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
LOOKUP_BASE    = os.getenv("LOOKUP_URL",    "http://localhost:8081/v1")
JWT_TOKEN      = os.getenv("TEST_JWT",      "dev-skip-verify")

# RADIUS (test_12 only — suite auto-skips if RADIUS_HOST is empty)
RADIUS_HOST    = os.getenv("RADIUS_HOST", "")
RADIUS_PORT    = int(os.getenv("RADIUS_PORT", "1812"))
RADIUS_SECRET  = os.getenv("RADIUS_SECRET", "")

# DB flush (conftest setup_session — clears tables before every run)
DB_URL         = os.getenv("DB_URL", "postgres://aaa_app:devpassword@localhost:5432/aaa")

# ── use_case_id convention ────────────────────────────────────────────────────
# aaa-radius-server reads the 3GPP-Charging-Characteristics VSA (vendor 10415,
# type 13) from every RADIUS Access-Request and forwards its value as
# use_case_id to GET /lookup and POST /first-connection.
# Tests use the fixed constant below so the same server code paths are exercised
# without requiring a real RADIUS packet.
USE_CASE_ID    = "0800"
```

**use_case_id in lookup and first-connection calls:**
All `GET /lookup` and `POST /first-connection` calls in test_03 through test_13
(and in the `_first_connection()` / `_fc()` helpers used by test_07 and test_07b)
pass `use_case_id=USE_CASE_ID`. Two intentional exceptions:
- **test_10 tests 10.13 / 10.14** — boundary tests for missing required params; adding `use_case_id` would not change the expected 400 but would obscure the intent.
- **test_12 pre-condition 404 checks** — raw lookups for IMSIs that do not yet exist; the explicit "with vs without" coverage is already provided by tests 10.16 / 10.17.

**Run order is sequential** (test_01 → test_13). Each module is self-contained: it creates
its own fixtures in `setup_class`, runs its cases, then tears down in `teardown_class`.
No shared mutable state between modules.

---

## Test Cases by Module

---

### test_01_pools.py — IP Pool CRUD + Stats

**APIs validated:** `POST /pools` · `GET /pools/{id}` · `GET /pools/{id}/stats` ·
`PATCH /pools/{id}` · `GET /pools` · `DELETE /pools/{id}`

Verifies the full lifecycle of an IP address pool: creation with CIDR validation,
stat counters immediately after creation, rename, list filtering by account, and
deletion blocked when allocations are active.

| # | Test | Expected |
|---|---|---|
| 1.1 | `POST /pools` with valid subnet (100.65.120.0/24) | 201, `pool_id` UUID returned |
| 1.2 | `GET /pools/{pool_id}` | 200, subnet / start_ip / end_ip correct |
| 1.3 | `GET /pools/{pool_id}/stats` immediately after creation | `available=253`, `allocated=0` |
| 1.4 | `PATCH /pools/{pool_id}` — rename pool | 200; GET confirms new name |
| 1.5 | `GET /pools?account_name=Melita` | 200, list includes created pool |
| 1.6 | `DELETE /pools/{pool_id}` with 0 allocations | 204 |
| 1.7 | `DELETE /pools/{pool_id}` with active allocations | 409 (pool in use) |
| 1.8 | `POST /pools` with invalid CIDR | 400 validation_failed |

---

### test_02_range_configs.py — IMSI Range Config CRUD

**APIs validated:** `POST /range-configs` · `GET /range-configs/{id}` · `GET /range-configs` ·
`PATCH /range-configs/{id}` · `DELETE /range-configs/{id}`

Verifies IMSI range configuration management: ranges link a consecutive block of IMSIs
to a specific IP pool and allocation mode, and drive dynamic first-connection allocation.
Covers IMSI boundary validation and suspension flow.

| # | Test | Expected |
|---|---|---|
| 2.1 | `POST /range-configs` with valid f_imsi / t_imsi / pool_id | 201, `id` returned |
| 2.2 | `GET /range-configs/{id}` | 200, all fields correct |
| 2.3 | `GET /range-configs?account_name=Melita` | 200, list includes created config |
| 2.4 | `PATCH /range-configs/{id}` — change pool_id and ip_resolution | 200; GET confirms update |
| 2.5 | `PATCH /range-configs/{id}` — set status=suspended | 200 |
| 2.6 | `DELETE /range-configs/{id}` | 204 |
| 2.7 | `POST /range-configs` with f_imsi > t_imsi (inverted range) | 400 validation_failed |
| 2.8 | `POST /range-configs` with non-15-digit IMSI boundary | 400 validation_failed |

---

### test_03_profiles_a.py — Profile A: `ip_resolution = "iccid"`

**APIs validated:** `POST /profiles` · `GET /profiles/{sim_id}` · `GET /lookup` ·
`PATCH /profiles/{sim_id}` · `DELETE /profiles/{sim_id}`

In `iccid` mode the APN is ignored — all IMSIs on the SIM card share a single card-level
static IP. Tests the full profile lifecycle: create with 2 IMSIs, lookup (APN irrelevant),
suspend/reactivate, and soft-delete. After deletion the profile row is retained with
`status=terminated` and remains readable via GET (not 404).

| # | Test | Expected |
|---|---|---|
| 3.1 | `POST /profiles` — iccid mode, 2 IMSIs, 1 iccid_ip | 201, `sim_id` returned |
| 3.2 | `GET /profiles/{sim_id}` | 200, `iccid_ips[0].static_ip` = 100.65.140.5 |
| 3.3 | `GET /lookup?imsi=IMSI1&apn=internet.operator.com` | 200, `{"static_ip":"100.65.140.5"}` |
| 3.4 | `GET /lookup?imsi=IMSI2&apn=ims.operator.com` | 200, same IP (different IMSI, APN ignored) |
| 3.5 | `GET /lookup?imsi=IMSI1&apn=any.garbage.apn` | 200, same IP (APN irrelevant in iccid mode) |
| 3.6 | `PATCH /profiles/{sim_id}` — status=suspended | 200 |
| 3.7 | `GET /lookup` after SIM suspended | 403 `{"error":"suspended"}` |
| 3.8 | `PATCH` status=active; `GET /lookup` | 200, IP resolves again |
| 3.9 | `DELETE /profiles/{sim_id}` → 204; subsequent `GET` | **200** with `status=terminated` *(was 404 before fix)* |

---

### test_04_profiles_b.py — Profile B: `ip_resolution = "imsi"`

**APIs validated:** `POST /profiles` · `GET /lookup` · `PATCH /profiles/{sim_id}` ·
`PATCH /profiles/{sim_id}/imsis/{imsi}`

In `imsi` mode each IMSI has its own static IP and APN is ignored. Tests per-IMSI
suspension (one IMSI blocked while siblings continue resolving), ICCID enrichment
on an initially iccid-null profile, and per-IMSI IP updates.

| # | Test | Expected |
|---|---|---|
| 4.1 | `POST /profiles` — imsi mode, iccid=null, 2 IMSIs with distinct IPs | 201 |
| 4.2 | `GET /lookup?imsi=IMSI1&apn=internet.operator.com` | 200, `{"static_ip":"100.65.120.5"}` |
| 4.3 | `GET /lookup?imsi=IMSI1&apn=ims.operator.com` | 200, same IP (APN ignored) |
| 4.4 | `GET /lookup?imsi=IMSI2&apn=internet.operator.com` | 200, `{"static_ip":"101.65.120.5"}` |
| 4.5 | `PATCH /profiles/{sim_id}` — set real iccid | 200; GET shows iccid populated |
| 4.6 | `PATCH /profiles/{sim_id}/imsis/{imsi1}` — suspend IMSI #1 | 200 |
| 4.7 | `GET /lookup?imsi=IMSI1` | 403 `{"error":"suspended"}` |
| 4.8 | `GET /lookup?imsi=IMSI2` | 200, IMSI #2 still resolves |
| 4.9 | `PATCH /profiles/{sim_id}/imsis/{imsi1}` — update static_ip | 200; GET /lookup returns new IP |

---

### test_05_profiles_c.py — Profile C: `ip_resolution = "imsi_apn"`

**APIs validated:** `POST /profiles` · `GET /lookup` · `POST /profiles/{sim_id}/imsis/{imsi}`

In `imsi_apn` mode each IMSI×APN pair has its own static IP. Tests APN-exact matching,
wildcard APN fallback (`apn=null`), and that exact matches take priority over the wildcard.
Also validates concurrent lookups for different APNs on the same IMSI.

| # | Test | Expected |
|---|---|---|
| 5.1 | `POST /profiles` — imsi_apn mode; IMSI1→[smf1→IP_A, smf2→IP_B]; IMSI2→[smf3→IP_C] | 201 |
| 5.2 | `GET /lookup?imsi=IMSI1&apn=smf1.operator.com` | 200, `{"static_ip":"IP_A"}` |
| 5.3 | `GET /lookup?imsi=IMSI1&apn=smf2.operator.com` | 200, `{"static_ip":"IP_B"}` |
| 5.4 | `GET /lookup?imsi=IMSI2&apn=smf3.operator.com` | 200, `{"static_ip":"IP_C"}` |
| 5.5 | `GET /lookup?imsi=IMSI1&apn=smf9.unknown.com` (no match, no wildcard) | 404 `{"error":"apn_not_found"}` |
| 5.6 | `POST /profiles/{sim_id}/imsis/{imsi1}` — add apn_ip `{apn:null, ip:IP_D}` (wildcard) | 200 |
| 5.7 | `GET /lookup?imsi=IMSI1&apn=smf9.unknown.com` | 200, `{"static_ip":"IP_D"}` (wildcard fires) |
| 5.8 | `GET /lookup?imsi=IMSI1&apn=smf1.operator.com` after wildcard added | 200, `{"static_ip":"IP_A"}` (exact wins) |
| 5.9 | Two concurrent `GET /lookup` for smf1 + smf2 same IMSI | both return their respective IPs |

---

### test_06_imsi_ops.py — IMSI Add / Remove

**APIs validated:** `GET /profiles/{sim_id}/imsis` · `POST /profiles/{sim_id}/imsis` ·
`GET /profiles/{sim_id}/imsis/{imsi}` · `DELETE /profiles/{sim_id}/imsis/{imsi}` · `GET /lookup`

Verifies that IMSIs can be added and removed from an existing profile independently,
and that the lookup service reflects changes immediately. Also covers conflict detection
(IMSI already assigned to another profile) and the last-IMSI deletion rule.

| # | Test | Expected |
|---|---|---|
| 6.1 | `GET /profiles/{sim_id}/imsis` | 200, list contains current IMSIs |
| 6.2 | `POST /profiles/{sim_id}/imsis` — add new IMSI with apn_ips | 201 |
| 6.3 | `GET /lookup?imsi={new_imsi}&apn=internet.operator.com` | 200, resolves |
| 6.4 | `GET /profiles/{sim_id}/imsis/{new_imsi}` | 200, apn_ips correct |
| 6.5 | `DELETE /profiles/{sim_id}/imsis/{new_imsi}` | 204 |
| 6.6 | `GET /lookup` after IMSI deleted | 404 |
| 6.7 | `POST /profiles/{sim_id}/imsis` — IMSI already on another SIM | 409 `imsi_conflict` |
| 6.8 | `DELETE` last IMSI on a profile | 400 (must keep at least 1 IMSI) |

---

### test_07_dynamic_alloc.py — First-Connection Allocation (Single-IMSI Baseline)

**APIs validated:** `GET /lookup` (triggers inline allocation) · `GET /pools/{id}/stats` ·
`GET /profiles` (verify auto-created profile) · `POST /range-configs`

Allocation is transparent: the caller always uses `GET /lookup`. When no profile exists
for the IMSI, the lookup service calls the provisioning API to allocate an IP from the
range config's pool and creates the profile atomically. Tests idempotency, pool exhaustion,
concurrent allocation for 10 simultaneous first-connection IMSIs, and suspended ranges.

| # | Test | Expected |
|---|---|---|
| 7.1 | Setup: pool + active range config covering IMSI range | — |
| 7.2 | IMSI in range, no profile → `GET /lookup?imsi={imsi}&apn=internet.operator.com` | 200, IP allocated; profile created |
| 7.3 | Same IMSI again → `GET /lookup` | 200, same IP (no re-allocation) |
| 7.4 | `GET /pools/{pool_id}/stats` after allocation | `allocated` +1, `available` -1 |
| 7.5 | `GET /profiles?imsi={imsi}` — verify auto-created profile | 200, ip_resolution=imsi, iccid=null |
| 7.6 | IMSI not in any range config → `GET /lookup` | 404 `{"error":"not_found"}` |
| 7.7 | IMSI in a suspended range config → `GET /lookup` | 404 (suspended range ignored) |
| 7.8 | Pool exhausted → `GET /lookup` for next new IMSI | 503 `{"error":"pool_exhausted"}` |
| 7.9 | 10 concurrent `GET /lookup` for 10 distinct first-connection IMSIs in same pool | all 200, 10 distinct IPs, 0 duplicates |

---

### test_07b_dynamic_alloc_modes.py — First-Connection All Allocation Modes

**APIs validated:** `GET /lookup` (all ip_resolution modes) · `GET /profiles/{sim_id}` ·
`GET /pools/{id}/stats` · `POST /range-configs` (with ip_resolution and pool_id variants)

Tests all seven allocation mode combinations that a range config can produce at
first-connection time. Single-SIM modes (S2–S4) cover one IMSI per SIM. Multi-IMSI modes
(M1–M4) exercise SIM cards with multiple IMSI slots where sibling slots are
pre-provisioned when the first slot connects.

#### TestS2SingleImsiApn — ip_resolution=imsi_apn (single IMSI)

| # | Test | Expected |
|---|---|---|
| 7b.S2.1 | First connection for IMSI, APN=internet → allocates APN-specific IP | 200, IP from pool |
| 7b.S2.2 | GET profile — both APNs (internet + ims) are provisioned | 2 apn_ips entries |
| 7b.S2.3 | Same IMSI + same APN again | same IP (idempotent) |
| 7b.S2.4 | Second APN first-connection | same IP (idempotent) |

#### TestS3SingleIccid — ip_resolution=iccid (single IMSI)

| # | Test | Expected |
|---|---|---|
| 7b.S3.1 | First connection → allocates card-level IP (stored in sim_apn_ips) | 200 |
| 7b.S3.2 | GET profile — ip_resolution=iccid | card-level iccid_ips populated |
| 7b.S3.3 | Different APN, same IMSI → same card IP returned | 200, same IP |

#### TestS4SingleIccidApn — ip_resolution=iccid_apn (single IMSI)

| # | Test | Expected |
|---|---|---|
| 7b.S4.1 | First connection for IMSI + APN → APN-specific IP at card level | 200 |
| 7b.S4.2 | Both APNs provisioned at card level | 2 entries in iccid_ips |
| 7b.S4.3 | ims APN second connection | same IP (idempotent) |

#### TestM1MultiImsi — ip_resolution=imsi (multi-IMSI SIM card)

| # | Test | Expected |
|---|---|---|
| 7b.M1.1 | First slot connects → 201; sibling slot 2 is pre-provisioned in same call | 200 |
| 7b.M1.2 | Slot 2 already has a profile and a distinct IP | profile exists, IP ≠ slot 1 IP |
| 7b.M1.3 | Slot 2 connects → idempotent, same IP | 200, same IP as pre-provisioned |
| 7b.M1.4 | Each slot has a distinct IP | slot 1 IP ≠ slot 2 IP |

#### TestM2MultiImsiApn — ip_resolution=imsi_apn (multi-IMSI SIM card)

| # | Test | Expected |
|---|---|---|
| 7b.M2.1 | Slot 1 first connection → 201; both APNs provisioned for slot 1 | 2 apn_ips |
| 7b.M2.2 | Slot 1 has both APNs provisioned | internet + ims entries |
| 7b.M2.3 | Slot 2 pre-provisioned with both APNs | 2 apn_ips, distinct IPs from slot 1 |
| 7b.M2.4 | Total IPs allocated = 4 (2 slots × 2 APNs) | pool stats: allocated=4 |

#### TestM3MultiIccid — ip_resolution=iccid (multi-IMSI SIM card)

| # | Test | Expected |
|---|---|---|
| 7b.M3.1 | Slot 1 first connection → creates card-level profile with shared IP | 200 |
| 7b.M3.2 | Slot 2 shares the same SIM card profile and IP | same sim_id, same IP |
| 7b.M3.3 | Pool allocates exactly 1 IP for all slots on the same card | allocated=1 |

#### TestM4MultiIccidApn — ip_resolution=iccid_apn (multi-IMSI SIM card)

| # | Test | Expected |
|---|---|---|
| 7b.M4.1 | Slot 1 first connection for internet APN → card-level IP | 200 |
| 7b.M4.2 | Both APNs at card level | iccid_ips has internet + ims |
| 7b.M4.3 | Slot 2 shares same card IPs | same sim_id, same IP as slot 1 |
| 7b.M4.4 | ims APN also shared across slots | same ims IP for both slots |

---

### test_07c_release_ips.py — IP Release & IMSI Detach

**APIs validated:** `POST /profiles/{sim_id}/release-ips` · `DELETE /profiles/{sim_id}/imsis/{imsi}` ·
`GET /pools/{id}/stats` · `POST /profiles/first-connection`

Covers two operations that return pool-managed IPs back to the available set:

- **`POST /release-ips`** — clears all IP allocations for a SIM (both `imsi_apn_ips` and
  `sim_apn_ips`). The profile and its IMSI bindings are preserved; next first-connection
  re-allocates fresh IPs (re-allocation path in first-connection code).
- **`DELETE /imsis/{imsi}`** — removes a single IMSI from a profile and returns its IPs.

> **IMSI range:** `278773075000001` – `278773075000099`

| # | Test | Expected |
|---|---|---|
| 7c.1 | Pool + range config reachable; ≤1 stale allocated IP tolerated from previous run | pool stats verified |
| 7c.2 | First-connection → allocate IP; `POST /release-ips` | 200, `released_count=1`; IP returned to pool; profile still active, `apn_ips=[]` |
| 7c.3 | `POST /release-ips` on SIM with no IPs (idempotent) | 200, `released_count=0`, `ips_released=[]` |
| 7c.4 | First-connection on same IMSI after release → fresh IP allocated | 200/201, new IP; pool allocated count back up |
| 7c.5 | `POST /release-ips` on unknown `sim_id` | 404 |
| 7c.6 | First-connection for IMSI_DEL1; `DELETE /imsis/{imsi}` | 204; pool `available` +1 |
| 7c.7 | `POST /profiles` with IMSI_DEL2; delete IMSI; re-add to new profile | 201 on both creates; no `imsi_conflict` after deletion |

---

### test_08_bulk.py — Bulk Upsert

**APIs validated:** `POST /profiles/bulk` · `GET /jobs/{job_id}` · `GET /profiles/{sim_id}` ·
`GET /lookup` · `POST /profiles/bulk` (multipart CSV upload)

Verifies the async bulk import pipeline: job submission, polling until completion,
spot-checking results via both provisioning and lookup APIs. Also tests partial failure
handling (one invalid record), idempotency on repeated submission, and CSV file upload.

| # | Test | Expected |
|---|---|---|
| 8.1 | `POST /profiles/bulk` with 500 Profile-A + 500 Profile-B + 500 Profile-C | 202, `job_id` returned |
| 8.2 | Poll `GET /jobs/{job_id}` until status=completed | `processed=1500`, `failed=0` |
| 8.3 | Spot-check 10 random sim_ids → `GET /profiles/{sim_id}` | 200, profile fields correct |
| 8.4 | `GET /lookup` for 10 random IMSIs from the batch | 200, all return correct static_ip |
| 8.5 | `POST /profiles/bulk` with 1 valid + 1 invalid IMSI (14 digits) | 202; completed with `failed=1`, `processed=1` |
| 8.6 | `GET /jobs/{job_id}` errors array | error row present with field=imsi details |
| 8.7 | Bulk upsert same sim_id twice (idempotency) | second upsert updates; profile count unchanged |
| 8.8 | `POST /profiles/bulk` with CSV file upload (multipart/form-data) | 202, same job flow |

---

### test_10_errors.py — Validation & Error Handling

**APIs validated:** `POST /profiles` · `GET /profiles/{sim_id}` · `DELETE /profiles/{sim_id}` ·
`PATCH /profiles/{sim_id}` · `GET /lookup`

Exhaustively covers all 400/404/409 error paths and validates that field-level error
detail is returned. Also covers ip_resolution change constraints (e.g., switching from
`imsi` to `imsi_apn` requires APN fields to be present).

| # | Test | Expected |
|---|---|---|
| 10.1 | `POST /profiles` — IMSI 14 digits | 400, field=imsi |
| 10.2 | `POST /profiles` — ICCID 10 digits | 400, field=iccid |
| 10.3 | `POST /profiles` — missing ip_resolution | 400 |
| 10.4 | `POST /profiles` — ip_resolution=bogus_value | 400 |
| 10.5 | `POST /profiles` — duplicate ICCID | 409 `iccid_conflict` |
| 10.6 | `POST /profiles` — duplicate IMSI | 409 `imsi_conflict` |
| 10.7 | `GET /profiles/{unknown_uuid}` | 404 |
| 10.8 | `DELETE` then `GET` same profile | 204 then 200 with status=terminated |
| 10.9 | `PATCH /profiles/{sim_id}` — ICCID already used by another profile | 409 |
| 10.10 | `GET /lookup` — suspended SIM | 403 `{"error":"suspended"}` |
| 10.11 | `PATCH` ip_resolution imsi→imsi_apn without providing apn fields | 400 validation_failed |
| 10.12 | `PATCH` ip_resolution imsi→iccid; supply valid iccid_ips; verify old apn_ips cleared | 200; GET /lookup returns iccid_static_ip |
| 10.13 | `GET /lookup` — missing apn param *(no `use_case_id` — intentional boundary test)* | 400 |
| 10.14 | `GET /lookup` — missing imsi param *(no `use_case_id` — intentional boundary test)* | 400 |
| 10.15 | Any endpoint with invalid / missing JWT (`@pytest.mark.noauth`) | 401 on both provision API and lookup service |
| 10.16 | `GET /lookup` without `use_case_id` | 200, correct IP — `use_case_id` is optional |
| 10.17 | `POST /first-connection` without `use_case_id` then with it; `GET /lookup` same pair | Both calls return identical IP — parameter is optional end-to-end |

---

### test_12_radius.py — End-to-End RADIUS Authentication

**APIs validated (indirectly via RADIUS):** `GET /lookup` (Stage 1) · `POST /first-connection` (Stage 2)
**Direct APIs:** `POST /profiles` · `PATCH /profiles/{sim_id}` · `POST /range-configs`

Sends real **UDP RADIUS Access-Request packets** to `aaa-radius-server` and validates the
two-stage AAA flow end-to-end:

- **Stage 1:** aaa-radius-server calls `GET /lookup?imsi=&apn=[&use_case_id=]` on aaa-lookup-service.
  - 200 → Access-Accept + Framed-IP-Address
  - 403 → Access-Reject (subscriber suspended)
  - 404 → falls through to Stage 2
- **Stage 2:** aaa-radius-server calls `POST /v1/first-connection {imsi, apn, imei[, use_case_id]}`.
  - 200 → Access-Accept + allocated Framed-IP-Address
  - 404/503 → Access-Reject

> **Requires** `RADIUS_HOST`, `RADIUS_PORT`, `RADIUS_SECRET` env vars.
> Suite auto-skips the entire class if `RADIUS_HOST` is empty or unreachable.
> In `values-dev.yaml` RADIUS is pre-configured: `host: "aaa-platform-aaa-radius-server"`.

| # | Test | Expected |
|---|---|---|
| 12.1 | Pre-conditions: profile exists; `GET /lookup` resolves; lookup also accepts optional `use_case_id` | 200 both calls |
| 12.2 | RADIUS Access-Request for known IMSI → Stage 1 hit | Access-Accept (code=2) |
| 12.3 | Framed-IP-Address in Accept = provisioned static_ip | IP matches profile |
| 12.4 | `PATCH` status=suspended → RADIUS request | Access-Reject (code=3) |
| 12.5 | `PATCH` status=active → RADIUS request | Access-Accept; same Framed-IP as before |
| 12.6 | First-connection IMSI (no profile) → Stage 1 miss → Stage 2 allocates | Access-Accept + new IP; profile created |
| 12.7 | Same IMSI again → Stage 1 hits existing profile | Access-Accept; same IP (idempotent) |
| 12.8 | IMSI outside all range configs → Stage 1 404 + Stage 2 404 | Access-Reject |
| 12.9 | Response Authenticator (RFC 2865 §3) is valid | MD5 digest verifies against shared secret |
| 12.10 | Access-Reject must NOT contain Framed-IP-Address (attr 8) | No IP in Reject response |
| 12.11 | Full 3GPP AVP packet (all standard + VSA attributes from a real PGW) | Access-Accept; correct Framed-IP |
| 12.12 | `User-Name` (attr 1) carries garbage IMSI; `3GPP-IMSI` VSA carries real IMSI | Server uses VSA → Accept; if User-Name used → would Reject |
| 12.13 | `3GPP-Charging-Characteristics` forwarded as `use_case_id` in Stage 1 call | Accept; lookup with use_case_id also returns correct IP |
| 12.14 | `3GPP-Charging-Characteristics` forwarded as `use_case_id` in Stage 2 body | First-connection Accept; lookup verifies post-allocation |

---

### test_13_export_and_ip_search.py — Export CSV + IP Filter + Terminated SIM Visibility

**APIs validated:** `GET /profiles/export` · `GET /profiles?ip=` · `GET /profiles/{sim_id}` ·
`GET /profiles` (no default status filter)

Covers three new behaviours introduced together:

1. **Export endpoint** — `GET /profiles/export` returns one row per IMSI (imsi mode) or one row
   per IMSI×APN pair (imsi_apn mode), in the same 9-column format used by the CSV bulk import
   (`sim_id, iccid, account_name, status, ip_resolution, imsi, apn, static_ip, pool_id`).

2. **IP address search** — `GET /profiles?ip=<addr>` and `GET /profiles/export?ip=<addr>` perform
   an exact `::inet` match across both `imsi_apn_ips` (per-IMSI/APN) and `sim_apn_ips`
   (card-level). Multiple SIMs may share an IP; all matches are returned.

3. **Terminated SIM visibility** — `DELETE /profiles/{sim_id}` soft-deletes (status=terminated).
   `GET /profiles/{sim_id}` now returns **200** with `status=terminated` (not 404).
   `GET /profiles` with no status filter includes terminated SIMs in the default list.

**Fixture layout:**

| Fixture | Mode | IMSIs | IPs |
|---|---|---|---|
| sim_a | imsi | IMSI1 → IP_UNIQUE, IMSI2 → IP_SHARED | 2 per-IMSI IPs |
| sim_b | imsi_apn | IMSI3 → APN1: IP_APN, APN2: IP_SHARED | 2 per-IMSI×APN IPs |
| sim_card | iccid | IMSI4 → IP_CARD (card-level) | 1 card-level IP |
| sim_term | imsi | IMSI5 → IP_TERM | terminated during test 13.11 |

| # | Test | Expected |
|---|---|---|
| 13.1 | `GET /profiles/export?account_name=X` — every row has exactly the 9 import-format keys | `set(row.keys()) == {"sim_id","iccid","account_name","status","ip_resolution","imsi","apn","static_ip","pool_id"}` |
| 13.2 | Export for sim_a (imsi mode, 2 IMSIs) | 2 rows; one per IMSI |
| 13.3 | Export for sim_b (imsi_apn mode, 1 IMSI × 2 APNs) | 2 rows; one per IMSI×APN pair |
| 13.4 | `GET /profiles/export?account_name=X` — only rows for that account | all rows have correct account_name; all 4 test SIMs present |
| 13.5 | `GET /profiles/export?ip=IP_UNIQUE` — unique IP held by sim_a only | rows belong only to sim_a |
| 13.6 | `GET /profiles/export?ip=IP_SHARED` — shared IP held by sim_a and sim_b | rows from both sim_a and sim_b |
| 13.7 | `GET /profiles?ip=IP_UNIQUE` | total=1; item is sim_a |
| 13.8 | `GET /profiles?ip=IP_SHARED` | total≥2; both sim_a and sim_b in results |
| 13.9 | `GET /profiles?ip=IP_CARD` — card-level IP (sim_apn_ips table) | sim_card in results |
| 13.10 | `GET /profiles?ip=1.2.3.4` (nonexistent) | total=0 |
| 13.11 | `DELETE /profiles/{sim_term_id}` → 204; `GET /profiles/{sim_term_id}` | **200**, `status=terminated`, `imsis=[]` |
| 13.12 | `GET /profiles?account_name=X` (no status filter) | sim_term_id appears in list |
| 13.13 | `GET /profiles?status=terminated&account_name=X` | all items have status=terminated; sim_term_id present |

---

### test_14_export_delete_reprovision.py — Export → Delete → Bulk Re-import

**APIs validated:** `GET /profiles/export` · `DELETE /profiles/{sim_id}` ·
`POST /profiles/bulk` · `GET /jobs/{job_id}` · `GET /lookup`

Exercises the full SIM lifecycle used by the UI export-and-reprovision workflow:

1. Provision 4 SIMs of a given type via API.
2. Export them via `GET /profiles/export` (the same endpoint the UI uses).
3. Delete each via `DELETE /profiles/{sim_id}`.
4. Convert the flat export rows back to bulk JSON and reprovision via `POST /profiles/bulk`.
5. Verify profiles are active and `GET /lookup` returns the correct IPs.

Repeated for all four `ip_resolution` modes — one pytest class per type, 4 tests each
= **16 tests total**.

> **IMSI prefix:** `27877140` (module 14)

| # | Test | SIM type | Expected |
|---|---|---|---|
| 14.A.1 | Export 4 `iccid` SIMs; every row has non-null `static_ip` | iccid | Validates iccid export fix |
| 14.A.2 | `DELETE` all 4 `sim_id`s; GET confirms `status=terminated` | iccid | 204 × 4 |
| 14.A.3 | `POST /profiles/bulk` from exported rows | iccid | job completed, `processed=4`, `failed=0` |
| 14.A.4 | `GET /lookup` for one IMSI per SIM | iccid | 200, IP matches original |
| 14.B.1–4 | Same flow for `imsi` type (1 IP per IMSI, APN-agnostic) | imsi | — |
| 14.C.1–4 | Same flow for `imsi_apn` type (1 IP per IMSI×APN pair) | imsi_apn | — |
| 14.D.1–4 | Same flow for `iccid_apn` type (card-level per-APN IPs) | iccid_apn | — |

> **`iccid`/`imsi` lookup note:** the `/lookup` endpoint always requires an `apn` parameter
> even though it is ignored in APN-agnostic modes. Tests pass `apn="any"` as a placeholder.

---

## Run Order & Teardown

```
1. conftest.py setup_session: DB flush (delete from sim_profiles, ip_pools, etc.)
2. Run test_01 → test_14 sequentially (pytest -v --junitxml=/app/results/results.xml)
3. Each module:  setup_class → tests → teardown_class
4. run_all.sh pushes JUnit totals to Prometheus Pushgateway (non-fatal if push fails)

Result (full suite, RADIUS enabled):
  159 passed · 0 failed · 0 skipped · ~80 s
```

### Profile Visibility After a Run

**Static-provisioning modules** (test_03–test_06, test_08, test_10, test_12–test_14) delete
their fixtures in `teardown_class` as usual — the test data is not meaningful to inspect
after the run.

**Dynamic-allocation modules** (test_07, test_07b, test_07c) follow a different lifecycle:

| Phase | Action |
|---|---|
| `setup_class` | Calls `cleanup_stale_profiles(client, *imsi_prefixes)` to soft-delete (`status→terminated`) any active profiles left by a previous interrupted run |
| Tests | First-connection and manual `POST /profiles` calls create profiles normally |
| `teardown_class` | Deletes only **infrastructure** (range configs + pools); **profiles are left active** |

After a successful run you can run:

```
GET /profiles/export?status=active&account_name=TestAccount
```

and see every SIM that was auto-provisioned during the suite — with its allocated IP,
`ip_resolution` mode, and pool. This is useful for verifying the allocation results
end-to-end without needing to re-run the tests.

The next run's `setup_class` will terminate those profiles before re-creating the
infrastructure, so no manual cleanup is needed between runs.

---

## Environment Variables

| Variable | Default | Required by |
|---|---|---|
| `PROVISION_URL` | `http://localhost:8080/v1` | All modules |
| `LOOKUP_URL` | `http://localhost:8081/v1` | test_03–07b, test_12 |
| `TEST_JWT` | `dev-skip-verify` | All modules |
| `DB_URL` | `postgres://aaa_app:devpassword@localhost:5432/aaa` | conftest DB flush |
| `PUSHGATEWAY_URL` | `http://localhost:9091` | run_all.sh metrics push |
| `RADIUS_HOST` | `""` (skips test_12) | test_12 only |
| `RADIUS_PORT` | `1812` | test_12 only |
| `RADIUS_SECRET` | `""` | test_12 only |

In `values-dev.yaml` the RADIUS variables are pre-configured for in-cluster use:

```yaml
aaa-regression-tester:
  radius:
    host:       "aaa-platform-aaa-radius-server"
    port:       1812
    secretName: "aaa-radius-secret"   # created by: make radius-secret
```

---

## Kubernetes Deployment

The tester runs as a **Kubernetes Job** (not a Deployment) — it executes the full suite,
pushes metrics, then exits. Managed via the `aaa-regression-tester` sub-chart in the
`aaa-platform` umbrella chart.

### Run via make (preferred)

```bash
make test          # full suite including RADIUS
make test PCAP=true  # same + tcpdump sidecar captures all traffic to test.pcap
```

### Run via kubectl (fallback when make/helm unavailable)

```bash
kubectl delete job aaa-regression-tester -n aaa-platform --ignore-not-found
kubectl apply -f aaa-regression-tester-job.yaml
kubectl wait --for=condition=complete job/aaa-regression-tester -n aaa-platform --timeout=900s
kubectl logs -n aaa-platform -l app.kubernetes.io/name=aaa-regression-tester -c regression-tester
```

The `aaa-regression-tester-job.yaml` at the repo root is the raw Job manifest (no helm templating)
with `RADIUS_HOST`, `RADIUS_PORT`, and `RADIUS_SECRET` pre-configured for the dev cluster.

### PCAP sidecar

When `make test PCAP=true` is used, a `tcpdump` sidecar is added to the pod. It captures all
pod traffic to `/captures/test.pcap` for the lifetime of the test run. Retrieve with:

```bash
make pcap-get   # kubectl cp from a helper pod
```

---

## Prometheus Metrics (via Pushgateway)

After the test run, `run_all.sh` pushes the following metrics:

| Metric | Type | Description |
|---|---|---|
| `regression_test_passed_total` | Gauge | Tests passed (labelled by module) |
| `regression_test_failed_total` | Gauge | Tests failed (labelled by module) |
| `regression_test_skipped_total` | Gauge | Tests skipped (labelled by module) |
| `regression_test_duration_seconds` | Gauge | Wall-clock duration per module |
| `regression_suite_duration_seconds` | Gauge | Total suite duration |
| `regression_last_run_timestamp` | Gauge | Unix timestamp of last run |
| `regression_suite_exit_code` | Gauge | 0=all passed · 1=failures |

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
        run: docker compose -f aaa-regression-tester/docker-compose.test.yml up -d
      - name: Run tests
        run: |
          pip install -r aaa-regression-tester/requirements.txt
          cd aaa-regression-tester && pytest --junitxml=results.xml
      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: junit-results
          path: aaa-regression-tester/results.xml
```
