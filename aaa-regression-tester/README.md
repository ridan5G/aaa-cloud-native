# AAA Regression Tester

## Overview

A standalone test suite that exercises every REST API endpoint across both services
and verifies correct behaviour for all IP resolution modes, dynamic first-connection
allocation, multi-IMSI SIM cards (with and without an ICCID range), IMSI-only SIM
groups, RADIUS authentication, bulk operations, export/search, routing domains, CIDR
finder, Grafana metrics, and failure scenarios.

**Technology:** Python 3.11 · `pytest` · `httpx` (sync client, class-scoped fixtures)
**Target environments:**
- In-cluster: Kubernetes Job via `make test` (primary)
- Local: Docker Compose (`docker-compose.test.yml`) against the same containers

**Output:** JUnit XML (`/app/results/results.xml`) · console pass/fail summary · Prometheus Pushgateway metrics

**Current suite result: 443 passed · 0 failed · 0 skipped · ~110 s**

---

## Repository Layout

```
aaa-regression-tester/
├── conftest.py                           # base URLs, JWT/RADIUS env, shared fixtures & helpers
├── pytest.ini                            # markers, timeout=60, test path config
├── requirements.txt                      # pytest, httpx, pytest-asyncio, pytest-timeout
├── run_all.sh                            # executes full suite, pushes metrics to Pushgateway
├── push_metrics.py                       # Prometheus Pushgateway metric push helper
├── Dockerfile                            # container image for in-cluster Job
├── docker-compose.test.yml               # local stack: PostgreSQL 15 + both services
│
├── fixtures/
│   ├── pools.py                          # create_pool / delete_pool / get_pool_stats helpers
│   ├── range_configs.py                  # create_range_config / create_iccid_range_config /
│   │                                     #   add_imsi_slot / add_imsi_slot_apn_pool helpers
│   ├── profiles.py                       # create_profile_imsi / _imsi_apn / _iccid / delete_profile
│   └── radius.py                         # RadiusClient, build_access_request, parse_response
│
├── test_01_pools.py                      # IP pool CRUD + stats                                [16 tests]
├── test_01b_radius_warmup.py             # Single RADIUS packet to seed Prometheus early        [ 1 test ]
├── test_01c_routing_domains.py           # Routing domain CRUD + suggest-cidr                  [17 tests]
├── test_01d_free_cidr_finder.py          # Free CIDR finder end-to-end workflow                [ 7 tests]
├── test_02_range_configs.py              # IMSI range config CRUD                              [ 8 tests]
├── test_03_iccid_profile.py              # ip_resolution=iccid                                [10 tests]
├── test_04_imsi_profile.py               # ip_resolution=imsi                                 [10 tests]
├── test_05_imsi_apn_profile.py           # ip_resolution=imsi_apn                             [10 tests]
├── test_06_imsi_ops.py                   # Add / remove IMSI, per-IMSI suspend                [ 8 tests]
├── test_07_dynamic_alloc.py              # First-connection single-IMSI baseline               [ 9 tests]
├── test_07b_dynamic_alloc_modes.py       # First-connection all allocation modes               [25 tests]
├── test_07c_release_ips.py               # IP release / IMSI detach + IP return               [ 8 tests]
├── test_07e_release_reconnect_all_modes.py  # Release + re-allocate across all 4 modes        [ 5 tests]
├── test_08_iccid_apn_profile.py          # ip_resolution=iccid_apn                            [17 tests]
├── test_09_migration.py                  # Migration output validation (skipped unless pre-seeded) [ 7 tests]
├── test_10_errors.py                     # Validation, 404, 409, 503, auth errors             [17 tests]
├── test_11_performance.py                # Latency assertions under load (skipped unless dataset) [ 7 tests]
├── test_12_radius.py                     # End-to-end RADIUS authentication (imsi mode)       [15 tests]
├── test_12_grafana_metrics.py            # Grafana dashboard metric presence                  [15 tests]
├── test_12b_radius_modes.py              # RADIUS end-to-end for all 4 ip_resolution modes    [13 tests]
├── test_13_export_and_ip_search.py       # Export CSV + IP filter + terminated SIM visibility [19 tests]
├── test_14_export_delete_reprovision.py  # Export → delete → bulk re-import (4 SIM types)    [16 tests]
├── test_15_bulk.py                       # Bulk upsert via POST /profiles/bulk                [ 8 tests]
├── test_15b_bulk_actions.py              # Bulk IP release + bulk IMSI delete                 [ 8 tests]
├── test_16_lookup_fast_path.py           # Fast-path gaps + cross-mode suspend                [13 tests]
├── test_17_immediate_provisioning.py     # Immediate provisioning for single-IMSI range configs [13 tests]
├── test_18_nullable_slot_pool.py         # Nullable slot pool_id + per-slot APN-pool routing  [22 tests]
├── test_19_validation_and_mgmt.py        # ICCID range config validation + IMSI-only skip mode [37 tests]
├── test_20_imsi_only_immediate.py        # IMSI-only SIM groups: immediate bulk provisioning   [51 tests]
└── test_21_imsi_only_first_connect.py    # IMSI-only SIM groups: first_connect provisioning   [31 tests]
```

---

## Environment & Configuration

```python
# conftest.py — key env vars

PROVISION_BASE = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
LOOKUP_BASE    = os.getenv("LOOKUP_URL",    "http://localhost:8081/v1")
JWT_TOKEN      = os.getenv("TEST_JWT",      "dev-skip-verify")

# RADIUS (test_12 / test_12b only — suite auto-skips if RADIUS_HOST is empty)
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
All `GET /lookup` and `POST /first-connection` calls pass `use_case_id=USE_CASE_ID`.
Two intentional exceptions:
- **test_10 tests 10.13 / 10.14** — boundary tests for missing required params; adding `use_case_id` would not change the expected 400 but would obscure the intent.
- **test_12 pre-condition 404 checks** — raw lookups for IMSIs that do not yet exist; explicit "with vs without" coverage is already provided by tests 10.16 / 10.17.

**Run order is sequential** (test_01 → test_21). Each module is self-contained: it creates
its own fixtures in `setup_class`, runs its cases, then tears down in `teardown_class`.
No shared mutable state between modules.

---

## Test Cases by Module

---

### [test_01_pools.py](../aio%20test%20description/test_01_pools.md) — IP Pool CRUD + Stats

**APIs validated:** `POST /pools` · `GET /pools/{id}` · `GET /pools/{id}/stats` ·
`PATCH /pools/{id}` · `GET /pools` · `DELETE /pools/{id}`

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

### [test_01b_radius_warmup.py](../aio%20test%20description/test_01b_radius_warmup.md) — RADIUS Warmup

Sends a single RADIUS Access-Request immediately after test_01_pools so that
`radius_requests_total` and `radius_request_duration_ms` timeseries appear in
Prometheus from the very start of the run (useful for Grafana metric tests).

---

### [test_01c_routing_domains.py](../aio%20test%20description/test_01c_routing_domains.md) — Routing Domain CRUD + suggest-cidr

**APIs validated:** `POST /routing-domains` · `GET /routing-domains/{id}` ·
`PATCH /routing-domains/{id}` · `DELETE /routing-domains/{id}` ·
`POST /routing-domains/{id}/suggest-cidr` · `GET /pools` (routing_domain_id filter)

| # | Test | Expected |
|---|---|---|
| 1c.1 | Create routing domain → 201 with id and name | UUID returned |
| 1c.2 | GET routing domain → 200, fields correct | |
| 1c.3 | PATCH name + allowed_prefixes → 200 | GET confirms update |
| 1c.4–1c.6 | suggest-cidr returns non-overlapping CIDR within allowed_prefixes | 200, CIDR within prefix |
| 1c.7 | suggest-cidr conflict with existing pool | returns next available block |
| 1c.8–1c.10 | Pool created inside domain; GET /pools?routing_domain_id=… | list includes pool |
| 1c.11–1c.13 | suggest-cidr with explicit prefix_len | correct size block returned |
| 1c.14–1c.17 | DELETE domain blocked when pools exist; 204 after pool deleted | 409 then 204 |

---

### [test_01d_free_cidr_finder.py](../aio%20test%20description/test_01d_free_cidr_finder.md) — Free CIDR Finder

**APIs validated:** `POST /routing-domains/{id}/suggest-cidr` · `POST /pools`

Full operator workflow: configure `allowed_prefixes` on a routing domain →
call `suggest-cidr` → create pool with the returned CIDR.

| # | Test | Expected |
|---|---|---|
| 1d.1 | suggest-cidr on empty domain | valid CIDR within prefix returned |
| 1d.2 | Create pool from suggestion | 201 |
| 1d.3 | suggest-cidr again → different block (no overlap) | non-overlapping CIDR |
| 1d.4 | suggest-cidr with /28 prefix_len | 14 usable hosts |
| 1d.5 | suggest-cidr prefix_len out of range | 400 |
| 1d.6 | suggest-cidr on domain with full prefix space | 503 `no_cidr_available` |
| 1d.7 | Cleanup — all pools and domain deleted | 204 |

---

### [test_02_range_configs.py](../aio%20test%20description/test_02_range_configs.md) — IMSI Range Config CRUD

**APIs validated:** `POST /range-configs` · `GET /range-configs/{id}` · `GET /range-configs` ·
`PATCH /range-configs/{id}` · `DELETE /range-configs/{id}`

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

### [test_03_iccid_profile.py](../aio%20test%20description/test_03_iccid_profile.md) — `ip_resolution = "iccid"`

In `iccid` mode the APN is ignored — all IMSIs on the SIM card share a single card-level
static IP.

| # | Test | Expected |
|---|---|---|
| 3.1 | `POST /profiles` — iccid mode, 2 IMSIs, 1 iccid_ip | 201, `sim_id` returned |
| 3.2 | `GET /profiles/{sim_id}` | 200, `iccid_ips[0].static_ip` = 100.65.140.5 |
| 3.3 | `GET /lookup?imsi=IMSI1&apn=internet.operator.com` | 200, IP returned |
| 3.4 | `GET /lookup?imsi=IMSI2&apn=ims.operator.com` | 200, same IP (different IMSI, APN ignored) |
| 3.5 | `GET /lookup?imsi=IMSI1&apn=any.garbage.apn` | 200, same IP (APN irrelevant) |
| 3.6 | `PATCH /profiles/{sim_id}` — status=suspended | 200 |
| 3.7 | `GET /lookup` after suspended | 403 `{"error":"suspended"}` |
| 3.8 | `PATCH` status=active; `GET /lookup` | 200, IP resolves again |
| 3.9 | `DELETE /profiles/{sim_id}` → 204; subsequent `GET` | 200 with `status=terminated` |
| 3.10 | `GET /lookup?imsi=IMSI2&apn=internet.operator.com` | 200, STATIC_IP (APN ignored — matrix outcome 12) |

---

### [test_04_imsi_profile.py](../aio%20test%20description/test_04_imsi_profile.md) — `ip_resolution = "imsi"`

In `imsi` mode each IMSI has its own static IP and APN is ignored.

| # | Test | Expected |
|---|---|---|
| 4.1 | `POST /profiles` — imsi mode, iccid=null, 2 IMSIs with distinct IPs | 201 |
| 4.2 | `GET /lookup?imsi=IMSI1` | 200, IP_A |
| 4.3 | `GET /lookup?imsi=IMSI1&apn=ims` | 200, same IP (APN ignored) |
| 4.4 | `GET /lookup?imsi=IMSI2` | 200, IP_B |
| 4.5 | `PATCH /profiles/{sim_id}` — set real iccid | 200; GET shows iccid populated |
| 4.6 | `PATCH /profiles/{sim_id}/imsis/{imsi1}` — suspend IMSI #1 | 200 |
| 4.7 | `GET /lookup?imsi=IMSI1` | 403 `{"error":"suspended"}` |
| 4.8 | `GET /lookup?imsi=IMSI2` | 200, IMSI #2 still resolves |
| 4.9 | `PATCH /profiles/{sim_id}/imsis/{imsi1}` — update static_ip | 200; GET /lookup returns new IP |
| 4.10 | `GET /lookup?imsi=IMSI2&apn=ims` | 200, IP_B (APN ignored — matrix outcome 4) |

---

### [test_05_imsi_apn_profile.py](../aio%20test%20description/test_05_imsi_apn_profile.md) — `ip_resolution = "imsi_apn"`

In `imsi_apn` mode each IMSI×APN pair has its own static IP.

| # | Test | Expected |
|---|---|---|
| 5.1 | `POST /profiles` — imsi_apn mode; IMSI1→[smf1→IP_A, smf2→IP_B]; IMSI2→[smf3→IP_C, smf4→IP_E] | 201 |
| 5.2 | `GET /lookup?imsi=IMSI1&apn=smf1` | 200, IP_A |
| 5.3 | `GET /lookup?imsi=IMSI1&apn=smf2` | 200, IP_B |
| 5.4 | `GET /lookup?imsi=IMSI2&apn=smf3` | 200, IP_C |
| 5.5 | `GET /lookup?imsi=IMSI1&apn=smf9` (no match, no wildcard) | 404 `apn_not_found` |
| 5.6 | Add `{apn:null, ip:IP_D}` wildcard | 200 |
| 5.7 | `GET /lookup?imsi=IMSI1&apn=smf9` | 200, IP_D (wildcard fires) |
| 5.8 | `GET /lookup?imsi=IMSI1&apn=smf1` after wildcard added | 200, IP_A (exact wins) |
| 5.9 | Two concurrent lookups for smf1 + smf2 same IMSI | both return their respective IPs |
| 5.10 | `GET /lookup?imsi=IMSI2&apn=smf4` | 200, IP_E (exact match — matrix outcome 8) |

---

### [test_06_imsi_ops.py](../aio%20test%20description/test_06_imsi_ops.md) — IMSI Add / Remove

**APIs validated:** `GET /profiles/{sim_id}/imsis` · `POST /profiles/{sim_id}/imsis` ·
`DELETE /profiles/{sim_id}/imsis/{imsi}` · `GET /lookup`

| # | Test | Expected |
|---|---|---|
| 6.1 | `GET /profiles/{sim_id}/imsis` | 200, list contains current IMSIs |
| 6.2 | `POST /profiles/{sim_id}/imsis` — add new IMSI | 201 |
| 6.3 | `GET /lookup?imsi={new_imsi}` | 200, resolves |
| 6.4 | `GET /profiles/{sim_id}/imsis/{new_imsi}` | 200, apn_ips correct |
| 6.5 | `DELETE /profiles/{sim_id}/imsis/{new_imsi}` | 204 |
| 6.6 | `GET /lookup` after IMSI deleted | 404 |
| 6.7 | Add IMSI already on another SIM | 409 `imsi_conflict` |
| 6.8 | `DELETE` last IMSI on a profile | 400 |

---

### [test_07_dynamic_alloc.py](../aio%20test%20description/test_07_dynamic_alloc.md) — First-Connection Allocation (Single-IMSI Baseline)

Allocation is transparent: `GET /lookup` triggers inline allocation when no profile
exists for the IMSI. Tests idempotency, pool exhaustion, concurrent allocation,
and suspended ranges.

| # | Test | Expected |
|---|---|---|
| 7.1 | Setup: pool + active range config | — |
| 7.2 | IMSI in range, no profile → `GET /lookup` | 200, IP allocated; profile created |
| 7.3 | Same IMSI again | 200, same IP (no re-allocation) |
| 7.4 | `GET /pools/{pool_id}/stats` after allocation | `allocated` +1 |
| 7.5 | `GET /profiles?imsi={imsi}` — verify auto-created profile | 200 |
| 7.6 | IMSI not in any range config | 404 `not_found` |
| 7.7 | IMSI in a suspended range config | 404 |
| 7.8 | Pool exhausted → next new IMSI | 503 `pool_exhausted` |
| 7.9 | 10 concurrent first-connection IMSIs | all 200, 10 distinct IPs, 0 duplicates |

---

### [test_07b_dynamic_alloc_modes.py](../aio%20test%20description/test_07b_dynamic_alloc_modes.md) — First-Connection All Allocation Modes

Tests all seven allocation mode combinations at first-connection time — four
single-IMSI modes (S1–S4) and four multi-IMSI modes (M1–M4).

#### TestS2SingleImsiApn — ip_resolution=imsi_apn (single IMSI)
| # | Test | Expected |
|---|---|---|
| S2.1 | First connection, APN=internet | 200, IP from pool |
| S2.2 | GET profile — both APNs provisioned | 2 apn_ips entries |
| S2.3 | Same IMSI + same APN again | same IP (idempotent) |
| S2.4 | Second APN first-connection | same IP (idempotent) |

#### TestS3SingleIccid — ip_resolution=iccid (single IMSI)
| # | Test | Expected |
|---|---|---|
| S3.1 | First connection → card-level IP | 200 |
| S3.2 | GET profile — iccid_ips populated | |
| S3.3 | Different APN, same IMSI → same card IP | 200, same IP |

#### TestS4SingleIccidApn — ip_resolution=iccid_apn (single IMSI)
| # | Test | Expected |
|---|---|---|
| S4.1 | First connection + APN → APN-specific card-level IP | 200 |
| S4.2 | Both APNs provisioned at card level | 2 entries in iccid_ips |
| S4.3 | ims APN second connection | same IP (idempotent) |

#### TestM1MultiImsi — ip_resolution=imsi (multi-IMSI SIM card)
| # | Test | Expected |
|---|---|---|
| M1.1 | Slot 1 connects → sibling slot 2 pre-provisioned | 200 |
| M1.2 | Slot 2 already has a distinct IP | profile exists |
| M1.3 | Slot 2 connects → same IP as pre-provisioned | 200 |
| M1.4 | Each slot has a distinct IP | slot 1 IP ≠ slot 2 IP |

#### TestM2MultiImsiApn — ip_resolution=imsi_apn (multi-IMSI SIM card)
| # | Test | Expected |
|---|---|---|
| M2.1 | Slot 1 first connection → both APNs provisioned | 2 apn_ips |
| M2.2 | Slot 1 has internet + ims entries | |
| M2.3 | Slot 2 pre-provisioned with both APNs | distinct IPs from slot 1 |
| M2.4 | Total IPs allocated = 4 (2 slots × 2 APNs) | pool stats: allocated=4 |

#### TestM3MultiIccid — ip_resolution=iccid (multi-IMSI SIM card)
| # | Test | Expected |
|---|---|---|
| M3.1 | Slot 1 first connection → card-level profile with shared IP | 200 |
| M3.2 | Slot 2 shares same sim_id and IP | same sim_id |
| M3.3 | Pool allocates exactly 1 IP for all slots | allocated=1 |

#### TestM4MultiIccidApn — ip_resolution=iccid_apn (multi-IMSI SIM card)
| # | Test | Expected |
|---|---|---|
| M4.1 | Slot 1 first connection for internet APN → card-level IP | 200 |
| M4.2 | Both APNs at card level | iccid_ips has internet + ims |
| M4.3 | Slot 2 shares same card IPs | same sim_id, same IP as slot 1 |
| M4.4 | ims APN also shared across slots | same ims IP for both slots |

---

### [test_07c_release_ips.py](../aio%20test%20description/test_07c_release_ips.md) — IP Release & IMSI Detach

**APIs validated:** `POST /profiles/{sim_id}/release-ips` · `DELETE /profiles/{sim_id}/imsis/{imsi}` ·
`GET /pools/{id}/stats`

| # | Test | Expected |
|---|---|---|
| 7c.1 | Pool + range config reachable | — |
| 7c.2 | First-connection → `POST /release-ips` | 200, `released_count=1`; IP returned; profile still active |
| 7c.3 | `POST /release-ips` on SIM with no IPs | 200, `released_count=0` |
| 7c.4 | First-connection after release → fresh IP allocated | new IP; pool count back up |
| 7c.5 | `POST /release-ips` on unknown sim_id | 404 |
| 7c.6 | First-connection for IMSI_DEL1; `DELETE /imsis/{imsi}` | 204; pool `available` +1 |
| 7c.7 | Delete IMSI; re-add to new profile | no `imsi_conflict` after deletion |
| 7c.8 | Idempotent re-allocation after release | same pool, fresh IP |

---

### [test_07e_release_reconnect_all_modes.py](../aio%20test%20description/test_07e_release_reconnect_all_modes.md) — Release + Re-allocate (All Modes)

Guards against a regression where `release-ips` + `first-connection` produced
duplicate or incorrect IPs across all four `ip_resolution` modes.

| # | Test | Expected |
|---|---|---|
| 7e.1 | imsi mode: release → reconnect → new IP | 200 |
| 7e.2 | imsi_apn mode: release → reconnect → new per-APN IPs | 200 |
| 7e.3 | iccid mode: release → reconnect → new card-level IP | 200 |
| 7e.4 | iccid_apn mode: release → reconnect → new card-level per-APN IPs | 200 |
| 7e.5 | No IP duplicates across all re-allocations | pool stats consistent |

---

### [test_08_iccid_apn_profile.py](../aio%20test%20description/test_08_iccid_apn_profile.md) — `ip_resolution = "iccid_apn"`

All IMSIs on a physical SIM card share a set of card-level IPs, one per APN.
APN resolution follows lookup order: exact match → wildcard → 404.

| # | Test | Expected |
|---|---|---|
| 8.1 | `POST /profiles` — iccid_apn mode; 2 IMSIs; 2 card-level APNs | 201 |
| 8.2–8.4 | Lookup for each IMSI × each APN | 200, correct card-level IP |
| 8.5 | Lookup for unknown APN (no wildcard) | 404 `apn_not_found` |
| 8.6 | Add wildcard iccid_ip (`apn=null`) | 200 |
| 8.7 | Lookup for unknown APN after wildcard added | 200, wildcard IP |
| 8.8 | Lookup for known APN → exact match wins over wildcard | 200, original IP |
| 8.9–8.17 | Suspend/resume, per-IMSI suspend, PATCH ip, delete, terminated visibility | as per other profile types |

---

### [test_09_migration.py](../aio%20test%20description/test_09_migration.md) — Migration Validation

Validates migration output via subscriber-profile-api. Runs **only** when a
pre-migrated DB is available (skipped otherwise).

---

### [test_10_errors.py](../aio%20test%20description/test_10_errors.md) — Validation & Error Handling

Exhaustively covers all 400/404/409/503 error paths and validates field-level
error detail.

| # | Test | Expected |
|---|---|---|
| 10.1 | `POST /profiles` — IMSI 14 digits | 400, field=imsi |
| 10.2 | `POST /profiles` — ICCID 10 digits | 400, field=iccid |
| 10.3 | Missing ip_resolution | 400 |
| 10.4 | ip_resolution=bogus_value | 400 |
| 10.5 | Duplicate ICCID | 409 `iccid_conflict` |
| 10.6 | Duplicate IMSI | 409 `imsi_conflict` |
| 10.7 | `GET /profiles/{unknown}` | 404 |
| 10.8 | `DELETE` then `GET` | 204 then 200 `status=terminated` |
| 10.9 | PATCH ICCID already on another profile | 409 |
| 10.10 | `GET /lookup` — suspended SIM | 403 `suspended` |
| 10.11 | PATCH ip_resolution imsi→imsi_apn without apn fields | 400 |
| 10.12 | PATCH ip_resolution imsi→iccid; supply valid iccid_ips | 200 |
| 10.13 | `GET /lookup` — missing apn param | 400 |
| 10.14 | `GET /lookup` — missing imsi param | 400 |
| 10.15 | Invalid / missing JWT | 401 on both APIs |
| 10.16 | `GET /lookup` without `use_case_id` | 200 (optional param) |
| 10.17 | `POST /first-connection` without then with `use_case_id` | identical IP both calls |

---

### [test_11_performance.py](../aio%20test%20description/test_11_performance.md) — Latency Under Load

Runs **only** when a pre-seeded dataset of ≥300 000 profiles is present (skipped otherwise).
Asserts p99 lookup latency under concurrent load.

---

### [test_12_radius.py](../aio%20test%20description/test_12_radius.md) — End-to-End RADIUS (imsi mode)

Sends real UDP RADIUS Access-Request packets to `aaa-radius-server` and validates
the two-stage AAA flow:

- **Stage 1:** lookup → 200 Access-Accept, 403 Access-Reject, 404 falls through to Stage 2
- **Stage 2:** first-connection → 200 Access-Accept, 404/503 Access-Reject

> Auto-skips if `RADIUS_HOST` is empty.

| # | Test | Expected |
|---|---|---|
| 12.1 | Pre-conditions: profile exists; lookup resolves | 200 |
| 12.2 | RADIUS for known IMSI → Stage 1 hit | Access-Accept (code=2) |
| 12.3 | Framed-IP-Address = provisioned static_ip | IP matches profile |
| 12.4 | Suspend → RADIUS | Access-Reject (code=3) |
| 12.5 | Reactivate → RADIUS | Access-Accept; same Framed-IP |
| 12.6 | First-connection IMSI → Stage 2 allocates | Access-Accept + new IP |
| 12.7 | Same IMSI again → Stage 1 hits | same IP (idempotent) |
| 12.8 | IMSI outside all range configs → Stage 2 404 | Access-Reject |
| 12.9 | Response Authenticator valid (RFC 2865 §3) | MD5 digest verifies |
| 12.10 | Access-Reject has no Framed-IP-Address | No attr 8 in Reject |
| 12.11 | Full 3GPP AVP packet | Access-Accept; correct IP |
| 12.12 | `User-Name` garbage; `3GPP-IMSI` VSA real IMSI | Server uses VSA → Accept |
| 12.13 | `3GPP-Charging-Characteristics` forwarded as `use_case_id` (Stage 1) | Accept |
| 12.14 | `3GPP-Charging-Characteristics` forwarded as `use_case_id` (Stage 2) | Accept |
| 12.15 | Warmup lookup also accepts optional `use_case_id` | 200 both calls |

---

### [test_12_grafana_metrics.py](../aio%20test%20description/test_12_grafana_metrics.md) — Grafana Dashboard Metric Presence

Verifies that every metric panel in the Grafana "Platform Overview" dashboard is fed by
a real counter/gauge/histogram emitted by the services. Queries Prometheus directly and
asserts all expected series exist with non-zero samples.

---

### [test_12b_radius_modes.py](../aio%20test%20description/test_12b_radius_modes.md) — RADIUS End-to-End (All 4 ip_resolution Modes)

Extends test_12_radius.py. Sends real RADIUS packets for all four resolution modes
and verifies correct Framed-IP-Address in Accept responses.

| # | Test | Expected |
|---|---|---|
| 12b.1–3 | imsi mode: pre-provisioned + first-connection | Accept + correct IP |
| 12b.4–6 | imsi_apn mode: APN-specific IP in Accept | Accept |
| 12b.7–9 | iccid mode: card-level IP | Accept |
| 12b.10–13 | iccid_apn mode: card-level per-APN IP | Accept |

---

### [test_13_export_and_ip_search.py](../aio%20test%20description/test_13_export_and_ip_search.md) — Export CSV + IP Filter + Terminated SIM Visibility

Covers three behaviours:
1. **Export** — `GET /profiles/export` returns one row per IMSI or IMSI×APN pair in the 9-column bulk import format.
2. **IP search** — `GET /profiles?ip=` and `GET /profiles/export?ip=` match across both `imsi_apn_ips` and `sim_apn_ips`.
3. **Terminated visibility** — `DELETE` soft-deletes; `GET` returns 200 `status=terminated`.

| # | Test | Expected |
|---|---|---|
| 13.1 | Export schema — every row has exactly the 9 import-format keys | ✓ |
| 13.2 | Export sim_a (imsi, 2 IMSIs) | 2 rows |
| 13.3 | Export sim_b (imsi_apn, 1 IMSI × 2 APNs) | 2 rows |
| 13.4 | Export by account_name | all 4 test SIMs present |
| 13.5 | Export `?ip=IP_UNIQUE` | rows belong only to sim_a |
| 13.6 | Export `?ip=IP_SHARED` | rows from sim_a + sim_b |
| 13.7 | `GET /profiles?ip=IP_UNIQUE` | total=1 |
| 13.8 | `GET /profiles?ip=IP_SHARED` | total≥2 |
| 13.9 | `GET /profiles?ip=IP_CARD` (sim_apn_ips table) | sim_card in results |
| 13.10 | `GET /profiles?ip=1.2.3.4` (nonexistent) | total=0 |
| 13.11 | `DELETE` → 204; `GET` | 200 `status=terminated` |
| 13.12 | `GET /profiles?account_name=X` (no status filter) | terminated SIM in list |
| 13.13 | `GET /profiles?status=terminated` | all items terminated |

---

### [test_14_export_delete_reprovision.py](../aio%20test%20description/test_14_export_delete_reprovision.md) — Export → Delete → Bulk Re-import

Full SIM lifecycle for all four `ip_resolution` modes (one pytest class per type,
4 tests each = 16 tests):

1. Provision 4 SIMs via API → Export → Delete → Bulk re-import → Verify lookup.

| # | Class | Mode | Expected |
|---|---|---|---|
| 14.A.1–4 | TestReprovisionIccid | iccid | export non-null static_ip; re-import; lookup OK |
| 14.B.1–4 | TestReprovisionImsi | imsi | 1 IP per IMSI; re-import; lookup OK |
| 14.C.1–4 | TestReprovisionImsiApn | imsi_apn | 1 IP per IMSI×APN; re-import; lookup OK |
| 14.D.1–4 | TestReprovisionIccidApn | iccid_apn | card-level per-APN IPs; re-import; lookup OK |

---

### [test_15_bulk.py](../aio%20test%20description/test_15_bulk.md) — Bulk Upsert

**APIs validated:** `POST /profiles/bulk` · `GET /jobs/{job_id}` · `GET /profiles/{sim_id}` · `GET /lookup`

| # | Test | Expected |
|---|---|---|
| 15.1 | `POST /profiles/bulk` with 1 500 profiles (500 A + 500 B + 500 C) | 202, `job_id` |
| 15.2 | Poll until status=completed | `processed=1500`, `failed=0` |
| 15.3 | Spot-check 10 random sim_ids | 200, fields correct |
| 15.4 | `GET /lookup` for 10 random IMSIs | 200, correct static_ip |
| 15.5 | 1 valid + 1 invalid IMSI (14 digits) | 202; `failed=1`, `processed=1` |
| 15.6 | errors array has field=imsi detail | ✓ |
| 15.7 | Bulk upsert same sim_id twice | second updates; profile count unchanged |
| 15.8 | CSV file upload (multipart/form-data) | 202, same job flow |

---

### [test_15b_bulk_actions.py](../aio%20test%20description/test_15b_bulk_actions.md) — Bulk IP Release + Bulk IMSI Delete

**APIs validated:** `POST /profiles/bulk-release-ips` · `POST /profiles/bulk-delete-imsis`

| # | Test | Expected |
|---|---|---|
| 15b.1–4 | Bulk release IPs by list of sim_ids | IPs returned to pool |
| 15b.5–8 | Bulk IMSI delete by filter | IMSIs removed; pool stats updated |

---

### [test_16_lookup_fast_path.py](../aio%20test%20description/test_16_lookup_fast_path.md) — Lookup Fast-Path & Cross-Mode Suspend

Covers gaps not addressed by existing profile-type tests: fast-path cache invalidation
on suspend/resume, and cross-mode suspend behaviour.

| # | Test | Expected |
|---|---|---|
| 16.1–5 | Fast-path cache invalidated on PATCH status=suspended | 403 immediately after patch |
| 16.6–10 | Fast-path cache invalidated on PATCH status=active | 200 immediately after reactivation |
| 16.11–13 | Cross-mode: suspend in one ip_resolution does not affect other modes | ✓ |

---

### [test_17_immediate_provisioning.py](../aio%20test%20description/test_17_immediate_provisioning.md) — Immediate Provisioning Mode

Verifies that `POST /range-configs` with `provisioning_mode="immediate"` triggers
bulk pre-provisioning of all IMSIs in the range, and that subsequent lookups
return pre-allocated IPs without invoking first-connection.

| # | Test | Expected |
|---|---|---|
| 17.1 | `POST /range-configs` immediate mode → 202 + `job_id` | job started |
| 17.2 | Poll job until completed | `processed=N`, `failed=0` |
| 17.3–6 | `GET /lookup` for IMSIs across the range | 200, pre-allocated IP (no first-connection) |
| 17.7–9 | Pool stats reflect all pre-allocated IPs | allocated=N |
| 17.10–13 | `DELETE /range-configs` releases all IPs back to pool | pool stats restored |

---

### [test_18_nullable_slot_pool.py](../aio%20test%20description/test_18_nullable_slot_pool.md) — Nullable Slot pool_id + Per-Slot APN Pool Routing

**APIs validated:** `POST /iccid-range-configs` · `POST .../imsi-slots` ·
`POST .../imsi-slots/{slot}/apn-pools` · `POST /first-connection`

Covers a production bug where a multi-IMSI ICCID range with `imsi_apn` mode and
per-slot APN pools (no default `pool_id` on the slot) caused a `500
NotNullViolationError` when the sibling pre-provisioning loop tried to INSERT an
`imsi_range_configs` row with `pool_id=NULL`.

| Class | Scenario | Tests |
|---|---|---|
| TestM5_ImsiApn_NullSlotPool | `imsi_apn` — slot has no pool_id; APN pools carry the pool | 5 |
| TestM5b_SiblingNoApnConfig | Sibling slot has no APN config at all → 422 `missing_apn_config` | 4 |
| TestM6_Iccid_NullSlotPool | `iccid` — slot has no pool_id; card-level IP from parent pool | 4 |
| TestM7_IccidApn_NullSlotPool | `iccid_apn` — slot has no pool_id; per-APN pools on slot-1 | 5 |
| TestM8_Immediate_MissingApnConfig | Immediate mode job fails gracefully when APN config absent | 4 |

---

### [test_19_validation_and_mgmt.py](../aio%20test%20description/test_19_validation_and_mgmt.md) — ICCID Range Config Validation & Management

**APIs validated:** `POST /iccid-range-configs` · `POST .../imsi-slots` ·
`POST .../imsi-slots/{slot}/apn-pools` · `DELETE .../apn-pools/{apn}` ·
`GET .../apn-pools` · `PATCH /iccid-range-configs/{id}`

Covers field validation, duplicate-slot enforcement, cardinality checks, APN pool
CRUD for IMSI slots, and the IMSI-only (skip-ICCID) mode.

| Class | Scenario | Tests |
|---|---|---|
| TestIccidRangeValidation | ICCID range creation errors (bad f_iccid, t_iccid, f/t mismatch, pool not found) | 7 |
| TestImsiSlotValidation | Slot errors: bad IMSI, duplicate slot, cardinality mismatch, ip_resolution conflict | 9 |
| TestApnPoolManagement | Slot APN pool CRUD: create / list / delete / duplicate APN rejection | 8 |
| TestSkipIccidRange | IMSI-only (no f_iccid/t_iccid): config created with null ICCID fields; GET returns null | 6 |
| TestSizeAlignment | All 4 ip_resolution types with ICCID range, cardinality alignment across slots | 7 |

---

### [test_20_imsi_only_immediate.py](../aio%20test%20description/test_20_imsi_only_immediate.md) — IMSI-Only SIM Groups: Immediate Bulk Provisioning

**APIs validated:** `POST /iccid-range-configs` · `POST .../imsi-slots` ·
`POST .../imsi-slots/{slot}/apn-pools` · `GET /jobs/{job_id}` · `GET /lookup` ·
`DELETE /iccid-range-configs/{id}`

Verifies that ICCID range configs created without `f_iccid`/`t_iccid` and
`provisioning_mode="immediate"` trigger the `_run_provision_imsi_job` background
task. Profiles are created with `iccid=NULL`; IPs are pre-allocated for all four
resolution modes. DELETE fully cleans up provisioned data.

| Class | ip_resolution | Slots | Cards | IPs | Tests |
|---|---|---|---|---|---|
| TestImsiOnlyImmediate_IMSI | `imsi` | 3 | 5 | 15 | 9 |
| TestImsiOnlyImmediate_IMSI_APN | `imsi_apn` | 3 | 5 | 15 per APN pool | 11 |
| TestImsiOnlyImmediate_ICCID | `iccid` | 3 | 5 | 5 (card-level) | 8 |
| TestImsiOnlyImmediate_ICCID_APN | `iccid_apn` | 3 | 5 | 5 per APN pool | 11 |
| TestImsiOnlyImmediateDeletion | `imsi` | 3 | 5 | — | 8 |
| TestImsiOnlyImmediateValidation | cross-slot cardinality mismatch → 400 | — | — | — | 4 |

Key assertions:
- Background job reaches `status=completed` with `failed=0`
- `GET /lookup` returns allocated IP without any first-connection call
- `DELETE /iccid-range-configs/{id}` returns all IPs to pool (verified via `GET /pools/{id}/stats`)
- DB direct checks (when `DB_URL` is set): sim_profiles/imsi2sim/imsi_apn_ips/sim_apn_ips all cleaned up

---

### [test_21_imsi_only_first_connect.py](../aio%20test%20description/test_21_imsi_only_first_connect.md) — IMSI-Only SIM Groups: First-Connect Provisioning

**APIs validated:** `POST /iccid-range-configs` · `POST .../imsi-slots` ·
`POST .../imsi-slots/{slot}/apn-pools` · `POST /first-connection` ·
`GET /iccid-range-configs/{id}` · `GET /pools/{id}/stats`

Exercises the fix for a latent crash in `first_connection.py` where the multi-IMSI
path tried to compute `len(f_iccid)` on an empty string (stored as `''` for IMSI-only
configs), raising `ValueError` for any `first_connect`-mode IMSI-only group.

Now `f_iccid`/`t_iccid` are stored as `NULL`; the first-connection handler branches
on `f_iccid IS NULL`, identifies the card by slot-1's IMSI at the same offset, and
creates `sim_profiles` with `iccid=NULL`.

| Class | ip_resolution | Slots | Cards | Tests | Key assertions |
|---|---|---|---|---|---|
| TestFirstConnectIMSIOnly_IMSI | `imsi` | 2 | 3 | 7 | Each slot on same card gets a distinct IP; slot-2 pre-provisioned on slot-1 connect |
| TestFirstConnectIMSIOnly_IMSI_APN | `imsi_apn` | 2 | 1 | 6 | Both APNs provisioned in one transaction; slot-2 pre-provisioned |
| TestFirstConnectIMSIOnly_ICCID | `iccid` | 2 | 2 | 7 | All slots on same card share one IP; pool allocates 1 IP per card |
| TestFirstConnectIMSIOnly_ICCID_APN | `iccid_apn` | 2 | 1 | 7 | Card-level per-APN IP shared by all slots |
| TestFirstConnectIMSIOnly_EdgeCases | error paths | — | — | 4 | `f_iccid=null` in GET response; `422 missing_slot1` when slot-1 absent |

---

## Run Order & Teardown

```
1. conftest.py setup_session: DB flush (delete from sim_profiles, ip_pools, etc.)
2. Run test_01 → test_21 sequentially (pytest -v --junitxml=/app/results/results.xml)
3. Each module:  setup_class → tests → teardown_class
4. run_all.sh pushes JUnit totals to Prometheus Pushgateway (non-fatal if push fails)

Result (full suite, RADIUS enabled):
  443 passed · 0 failed · 0 skipped · ~110 s
```

### Profile Visibility After a Run

**Static-provisioning modules** (test_03–test_06, test_08, test_10, test_12–test_15b)
delete their fixtures in `teardown_class`.

**Dynamic-allocation modules** (test_07, test_07b, test_07c, test_07e, test_17–test_21)
leave profiles active after teardown. After a run:

```
GET /profiles/export?status=active&account_name=TestAccount
```

shows every auto-provisioned SIM with its allocated IP, `ip_resolution` mode, and pool.
The next run's `setup_class` terminates those profiles before recreating infrastructure.

---

## Resolution Scenario Reference — ICCID Dual-IMSI (16 outcomes)

This section is the canonical lookup-resolution reference for the test suite. It uses
the same DB layout that the profile-type and dynamic-allocation tests share, so each cell
maps directly to one or more test cases.

### Scenario: DB layout

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

The hot-path SQL anchors on the incoming IMSI (`WHERE si.imsi = $1`). For an IMSI-A
request the result rows are:

**`imsi` mode** — 1 row (1 `imsi_apn_ips` row × 0 `sim_apn_ips` rows; absent side → NULLs)

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
NULL      100.65.1.10     NULL       NULL
```

**`imsi_apn` mode** — 2 rows (2 `imsi_apn_ips` rows × 0 `sim_apn_ips` rows)

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
apn1.net  100.65.1.11     NULL       NULL
apn2.net  100.65.1.12     NULL       NULL
```

**`iccid` mode** — 1 row (0 `imsi_apn_ips` rows → 1 base row with NULLs × 1 `sim_apn_ips` row)

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
NULL      NULL            NULL       100.65.3.10
```

**`iccid_apn` mode** — 2 rows (0 `imsi_apn_ips` rows → 1 base row with NULLs × 2 `sim_apn_ips` rows)

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
NULL      NULL            apn1.net   100.65.3.11
NULL      NULL            apn2.net   100.65.3.12
```

### 16-outcome matrix

| Request | `imsi` | `imsi_apn` | `iccid` | `iccid_apn` |
|---|---|---|---|---|
| IMSI-A, apn1.net | 200 `100.65.1.10` (APN ignored) | 200 `100.65.1.11` (exact match) | 200 `100.65.3.10` (APN ignored) | 200 `100.65.3.11` (exact match) |
| IMSI-A, apn2.net | 200 `100.65.1.10` (APN ignored) | 200 `100.65.1.12` (exact match) | 200 `100.65.3.10` (APN ignored) | 200 `100.65.3.12` (exact match) |
| IMSI-B, apn1.net | 200 `100.65.2.10` (APN ignored) | 200 `100.65.2.11` (exact match) | 200 `100.65.3.10` (APN ignored, same card) | 200 `100.65.3.11` (exact match, same card) |
| IMSI-B, apn2.net | 200 `100.65.2.10` (APN ignored) | 200 `100.65.2.12` (exact match) | 200 `100.65.3.10` (APN ignored, same card) | 200 `100.65.3.12` (exact match, same card) |

Key distinction: `imsi` / `imsi_apn` modes give **different** IPs to IMSI-A and IMSI-B
(each owns its own `imsi_apn_ips` rows). `iccid` / `iccid_apn` modes give the **same**
IP to both (they share the card's `sim_apn_ips` rows).

### Test coverage map

| Scenario | Static-provisioning tests | Dynamic first-connection tests |
|---|---|---|
| `imsi` mode, dual-IMSI | test_04_imsi_profile: 4.2–4.4, 4.10 | test_07b: M1.1–M1.4 |
| `imsi_apn` mode, dual-IMSI + dual-APN | test_05_imsi_apn_profile: 5.2–5.4, 5.7–5.8, 5.10 | test_07b: M2.1–M2.4 |
| `iccid` mode, dual-IMSI | test_03_iccid_profile: 3.3–3.5, 3.10 | test_07b: M3.1–M3.3 |
| `iccid_apn` mode, dual-IMSI + dual-APN | test_08_iccid_apn_profile: 8.2–8.8 | test_07b: M4.1–M4.4 |
| Fast-path cache invalidation (all modes) | test_16: 16.1–16.13 | — |
| RADIUS end-to-end (all modes) | test_12b: 12b.1–12b.13 | — |
| IMSI-only + immediate (all 4 modes) | test_20: A–F all classes | — |
| IMSI-only + first_connect (all 4 modes) | — | test_21: A–E all classes |
| Nullable slot pool_id + per-slot APN routing | test_18: M5–M8 | — |
| ICCID range validation + skip-ICCID mode | test_19: all classes | — |

---

## Environment Variables

| Variable | Default | Required by |
|---|---|---|
| `PROVISION_URL` | `http://localhost:8080/v1` | All modules |
| `LOOKUP_URL` | `http://localhost:8081/v1` | test_03–07e, test_12, test_16, test_17 |
| `TEST_JWT` | `dev-skip-verify` | All modules |
| `DB_URL` | `postgres://aaa_app:devpassword@localhost:5432/aaa` | conftest DB flush · test_20 deletion assertions (optional) · test_21 |
| `PUSHGATEWAY_URL` | `http://localhost:9091` | run_all.sh metrics push |
| `RADIUS_HOST` | `""` (skips test_12 / test_12b) | test_12, test_12b only |
| `RADIUS_PORT` | `1812` | test_12, test_12b only |
| `RADIUS_SECRET` | `""` | test_12, test_12b only |

In `values-dev.yaml` RADIUS is pre-configured for in-cluster use:

```yaml
aaa-regression-tester:
  radius:
    host:       "aaa-platform-aaa-radius-server"
    port:       1812
    secretName: "aaa-radius-secret"   # created by: make radius-secret
```

---

## Kubernetes Deployment

The tester runs as a **Kubernetes Job** — executes the full suite, pushes metrics, then exits.
Managed via the `aaa-regression-tester` sub-chart in the `aaa-platform` umbrella chart.

### Run via make (preferred)

```bash
make test            # full suite including RADIUS
make test PCAP=true  # same + tcpdump sidecar captures all traffic to test.pcap
```

### Run via kubectl (fallback)

```bash
kubectl delete job aaa-regression-tester -n aaa-platform --ignore-not-found
kubectl apply -f aaa-regression-tester-job.yaml
kubectl wait --for=condition=complete job/aaa-regression-tester -n aaa-platform --timeout=900s
kubectl logs -n aaa-platform -l app.kubernetes.io/name=aaa-regression-tester -c regression-tester
```

### PCAP sidecar

When `make test PCAP=true` is used, a `tcpdump` sidecar captures all pod traffic to
`/captures/test.pcap`. Retrieve with:

```bash
make pcap-get   # kubectl cp from a helper pod
```

---

## Prometheus Metrics (via Pushgateway)

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
