# Test Suite 16 — Lookup Fast-Path: Input Validation and Suspend/Reactivate (All Four Modes)

## What this test suite validates

This is the dedicated fast-path test file for `aaa-lookup-service`. It covers five areas: (1) the lookup service's validation of the IMSI format before any database access, (2) SIM-level suspend / reactivate in `imsi` mode, (3) SIM-level + per-IMSI suspend, reactivate, and concurrent lookups in `imsi_apn` mode, (4) the same scenarios in `iccid` mode (card-level shared IP, APN ignored), and (5) the same scenarios in `iccid_apn` mode (per-APN card-level IPs with wildcard fallback). The four mode classes give the file parallel coverage across every `ip_resolution` value, so `pytest -m fastpath` exercises all branches of the C++ resolver in one place.

## Pre-conditions (Setup)

**Group 1 — Parameter validation:** No database records are required.

**Group 2 — `imsi` mode suspend tests:**
1. Clean up any existing profiles whose IMSIs start with the module-16 prefix.
2. Force-delete any leftover terminated profiles for the test IMSI range.
3. Create an IP pool (`pool-fp16-imsi`) in subnet `100.65.180.0/24`.
4. Create a single SIM profile in `imsi` mode with two IMSIs:
   - IMSI_A (`278771600000001`) assigned IP `100.65.180.1`
   - IMSI_B (`278771600000002`) assigned IP `100.65.180.2`

**Group 3 — `imsi_apn` mode suspend tests:**
1. Clean up any existing profiles and force-delete terminated profiles for the test IMSI range.
2. Create an IP pool (`pool-fp16-iapn`) in subnet `100.65.181.0/24`.
3. Create a single SIM profile in `imsi_apn` mode with two IMSIs, each configured for two APNs:
   - IMSI_A (`278771600000011`): internet APN → IP `100.65.181.1`, IMS APN → IP `100.65.181.2`
   - IMSI_B (`278771600000012`): internet APN → IP `100.65.181.3`, IMS APN → IP `100.65.181.4`

**Group 4 — `iccid` mode suspend tests:**
1. Clean up any existing profiles and force-delete terminated profiles for the test IMSI range.
2. Create an IP pool (`pool-fp16-iccid`) in subnet `100.65.182.0/24`.
3. Create a single card-level SIM profile in `iccid` mode (ICCID `make_iccid(16, 21)`) with two IMSIs sharing one IP:
   - IMSI_A (`278771600000021`) and IMSI_B (`278771600000022`) both → card IP `100.65.182.1`

**Group 5 — `iccid_apn` mode suspend tests:**
1. Clean up any existing profiles and force-delete terminated profiles for the test IMSI range.
2. Create an IP pool (`pool-fp16-icapn`) in subnet `100.65.183.0/24`.
3. Create a single card-level SIM profile in `iccid_apn` mode (ICCID `make_iccid(16, 31)`) with two IMSIs sharing per-APN IPs:
   - Both IMSIs (`278771600000031`, `278771600000032`) share: internet APN → IP `100.65.183.1`, IMS APN → IP `100.65.183.2`

## Test 16.1 — 14-digit IMSI is rejected before database access

**Goal:** Confirm the lookup service rejects an IMSI that is too short (14 digits instead of the required 15).

1. Send a request to `GET /lookup?imsi=27877160000001&apn=internet.operator.com` (14-digit IMSI).
2. Verify the response is HTTP 400 (bad request).

## Test 16.2 — 16-digit IMSI is rejected before database access

**Goal:** Confirm the lookup service rejects an IMSI that is too long (16 digits).

1. Send a request to `GET /lookup?imsi=2787716000000001&apn=internet.operator.com` (16-digit IMSI).
2. Verify the response is HTTP 400 (bad request).

## Test 16.3 — IMSI containing non-digit characters is rejected

**Goal:** Confirm the lookup service rejects an IMSI containing letters.

1. Send a request to `GET /lookup?imsi=2787716ABCDE001&apn=internet.operator.com` (15 characters, contains letters).
2. Verify the response is HTTP 400 (bad request).

## Test 16.4 — Empty IMSI string is rejected

**Goal:** Confirm the lookup service treats an empty IMSI parameter the same as a missing one.

1. Send a request to `GET /lookup?imsi=&apn=internet.operator.com` (empty IMSI).
2. Verify the response is HTTP 400 (bad request).

## Test 16.5 — Valid IMSI that is not registered returns "unqualified" (pre-qualification short-circuit)

**Goal:** Confirm that a correctly formatted IMSI that was never provisioned and is not bracketed by any active range config is rejected by the lookup-service pre-qualification short-circuit (`PREQUALIFY_SQL`). The lookup service must return 404 directly without calling `subscriber-profile-api`. The full pre-qualification contract is covered by [test suite 18](test_18_lookup_prequalify.md).

1. Send `GET /lookup?imsi={valid_unregistered_imsi}&apn=internet.operator.com&use_case_id=...` using a correctly formatted 15-digit IMSI never provisioned and outside every range config.
2. Verify the response is HTTP 404.
3. Verify the response body contains `"error": "unqualified"`.

## Test 16.6 — Both IMSIs resolve correctly when the SIM is active (baseline)

**Goal:** Establish a known-good starting state before the suspend tests: both IMSIs on the profile return their correct IPs.

1. Send a request to `GET /lookup?imsi=278771600000001&apn=internet.operator.com&use_case_id=...` (IMSI_A).
2. Verify the response is HTTP 200 (success) and `static_ip = "100.65.180.1"`.
3. Send a request to `GET /lookup?imsi=278771600000002&apn=internet.operator.com&use_case_id=...` (IMSI_B).
4. Verify the response is HTTP 200 (success) and `static_ip = "100.65.180.2"`.

## Test 16.7 — Suspending the SIM profile blocks ALL its IMSIs

**Goal:** Confirm that suspending the SIM at the profile level (not per-IMSI) blocks every IMSI on that profile.

1. Send a request to `PATCH /profiles/{sim_id}` with body `{"status": "suspended"}`.
2. Verify the response is HTTP 200 (success).
3. Send a request to `GET /lookup?imsi=278771600000001&...` (IMSI_A).
4. Verify the response is HTTP 403 (forbidden / suspended) and `"error": "suspended"`.
5. Send a request to `GET /lookup?imsi=278771600000002&...` (IMSI_B).
6. Verify the response is also HTTP 403 (forbidden) and `"error": "suspended"`.

## Test 16.8 — Reactivating the SIM restores lookups for both IMSIs

**Goal:** Confirm the suspend/reactivate cycle is fully reversible and original IPs are preserved.

1. Send a request to `PATCH /profiles/{sim_id}` with body `{"status": "active"}`.
2. Verify the response is HTTP 200 (success).
3. Send a request to `GET /lookup` for IMSI_A.
4. Verify the response is HTTP 200 (success) and returns IP `100.65.180.1`.
5. Send a request to `GET /lookup` for IMSI_B.
6. Verify the response is HTTP 200 (success) and returns IP `100.65.180.2`.

## Test 16.9 — All IMSI-APN combinations resolve when SIM is active (baseline)

**Goal:** Establish a known-good state for the IMSI-APN mode before suspend tests.

1. Send lookup requests for all four IMSI+APN combinations:
   - IMSI_A + internet APN → expect IP `100.65.181.1`
   - IMSI_A + IMS APN → expect IP `100.65.181.2`
   - IMSI_B + internet APN → expect IP `100.65.181.3`
   - IMSI_B + IMS APN → expect IP `100.65.181.4`
2. Verify each returns HTTP 200 (success) with the expected IP.

## Test 16.10 — SIM-level suspend blocks all IMSI-APN combinations

**Goal:** Confirm that suspending the SIM profile in IMSI-APN mode blocks every IMSI and every APN combination.

1. Send a request to `PATCH /profiles/{sim_id}` with body `{"status": "suspended"}`.
2. Verify the response is HTTP 200 (success).
3. Send lookup requests for all four IMSI+APN combinations.
4. Verify each returns HTTP 403 (forbidden) with `"error": "suspended"`.

## Test 16.11 — Reactivating the SIM restores all IMSI-APN combinations

**Goal:** Confirm full recovery after SIM-level reactivation — all four combinations return correct IPs.

1. Send a request to `PATCH /profiles/{sim_id}` with body `{"status": "active"}`.
2. Verify the response is HTTP 200 (success).
3. Send lookup requests for all four IMSI+APN combinations.
4. Verify each returns HTTP 200 (success) with the original expected IP.

## Test 16.12 — Per-IMSI suspend blocks only that IMSI, leaving the sibling IMSI unaffected

**Goal:** Confirm that suspending a single IMSI (not the whole SIM) blocks only that IMSI's lookups, regardless of APN.

1. Send a request to `PATCH /profiles/{sim_id}/imsis/{IMSI_A}` with body `{"status": "suspended"}`.
2. Verify the response is HTTP 200 (success).
3. Send a lookup for IMSI_A + internet APN.
4. Verify the response is HTTP 403 (forbidden) with `"error": "suspended"`.
5. Send a lookup for IMSI_A + IMS APN.
6. Verify the response is also HTTP 403 (forbidden).
7. Send a lookup for IMSI_B + internet APN.
8. Verify the response is HTTP 200 (success) with IP `100.65.181.3`.
9. Send a lookup for IMSI_B + IMS APN.
10. Verify the response is HTTP 200 (success) with IP `100.65.181.4`.

## Test 16.13 — Concurrent lookups for two APNs of the same active IMSI return correct IPs

**Goal:** Confirm that the lookup service handles simultaneous requests without cross-contaminating results.

1. With IMSI_A still suspended (from test 16.12), send two lookup requests at the same time — one for IMSI_B + internet APN and one for IMSI_B + IMS APN — using two parallel threads.
2. Wait for both threads to complete.
3. Verify the result for IMSI_B + internet APN is HTTP 200 (success) with IP `100.65.181.3`.
4. Verify the result for IMSI_B + IMS APN is HTTP 200 (success) with IP `100.65.181.4`.

## Test 16.14 — Both IMSIs return the same card-level IP in `iccid` mode (baseline)

**Goal:** In `iccid` mode the resolver returns a card-level IP (`apn IS NULL` row in `sim_apn_ips`) shared by every IMSI on the card.

1. Send `GET /lookup` for IMSI_A + any APN → HTTP 200 with `static_ip = 100.65.182.1`.
2. Send `GET /lookup` for IMSI_B + any APN → HTTP 200 with `static_ip = 100.65.182.1` (same IP).

## Test 16.15 — Garbage APN still resolves in `iccid` mode

**Goal:** APN is ignored in `iccid` mode — even an APN that does not appear anywhere returns the card IP.

1. Send `GET /lookup?imsi=278771600000021&apn=no.such.apn`.
2. Verify HTTP 200 with `static_ip = 100.65.182.1`.

## Test 16.16 — SIM-level suspend blocks both IMSIs in `iccid` mode

1. PATCH the SIM profile `status=suspended`.
2. Send lookups for IMSI_A and IMSI_B.
3. Verify both return HTTP 403 with `"error": "suspended"`.

## Test 16.17 — Reactivating the SIM in `iccid` mode restores the card IP

1. PATCH the SIM profile `status=active`.
2. Send lookups for both IMSIs.
3. Verify both return HTTP 200 with `static_ip = 100.65.182.1`.

## Test 16.18 — Per-IMSI suspend in `iccid` mode blocks only the suspended IMSI

**Goal:** Even though both IMSIs share the same card-level IP, per-IMSI suspend in `iccid` mode is enforced at the `imsi2sim.status` level — only the suspended IMSI's lookups are blocked.

1. PATCH `/profiles/{sim_id}/imsis/{IMSI_A}` with `{"status": "suspended"}`.
2. Send a lookup for IMSI_A → HTTP 403 with `"error": "suspended"`.
3. Send a lookup for IMSI_B → HTTP 200 with `static_ip = 100.65.182.1` (unaffected).

## Test 16.19 — All IMSI×APN combos resolve in `iccid_apn` mode (baseline)

**Goal:** In `iccid_apn` mode the resolver returns a card-level per-APN IP. Both IMSIs on the card share the same per-APN IP.

1. Send `GET /lookup` for all four combinations:
   - IMSI_A + internet → `100.65.183.1`
   - IMSI_A + IMS → `100.65.183.2`
   - IMSI_B + internet → `100.65.183.1`
   - IMSI_B + IMS → `100.65.183.2`
2. Verify each returns HTTP 200 with the expected card-level per-APN IP.

## Test 16.20 — Unknown APN with no wildcard returns `apn_not_found`

**Goal:** When the profile has specific APN entries but no wildcard (`apn IS NULL`), an unknown APN returns 404 with `apn_not_found` (not the generic `not_found`).

1. Send `GET /lookup?imsi=278771600000031&apn=no.such.apn`.
2. Verify HTTP 404 with `"error": "apn_not_found"`.

## Test 16.21 — SIM-level suspend blocks all IMSI×APN combos in `iccid_apn` mode

1. PATCH the SIM profile `status=suspended`.
2. Send lookups for all four IMSI×APN combos.
3. Verify each returns HTTP 403 with `"error": "suspended"`.

## Test 16.22 — Reactivating the SIM in `iccid_apn` mode restores all combos

1. PATCH the SIM profile `status=active`.
2. Send lookups for all four IMSI×APN combos.
3. Verify each returns HTTP 200 with the original card-level per-APN IP.

## Test 16.23 — Per-IMSI suspend in `iccid_apn` mode blocks only that IMSI's APNs

1. PATCH `/profiles/{sim_id}/imsis/{IMSI_A}` with `{"status": "suspended"}`.
2. Send lookups for IMSI_A + internet, IMSI_A + IMS → both HTTP 403 with `"error": "suspended"`.
3. Send lookups for IMSI_B + internet, IMSI_B + IMS → both HTTP 200 with the expected per-APN IPs.

## Test 16.24 — Concurrent lookups for IMSI_B's two APNs return correct IPs (`iccid_apn`)

1. With IMSI_A still suspended (from 16.23), send two parallel lookup threads — IMSI_B + internet and IMSI_B + IMS.
2. Verify each returns HTTP 200 with the expected per-APN IP (`100.65.183.1` and `100.65.183.2`).
3. Verify no thread cross-contamination occurred.

## Post-conditions (Teardown)

**Group 2 (`imsi` mode):**
1. Delete the SIM profile.
2. Delete the `pool-fp16-imsi` IP pool.

**Group 3 (`imsi_apn` mode):**
1. Delete the SIM profile.
2. Delete the `pool-fp16-iapn` IP pool.

**Group 4 (`iccid` mode):**
1. Delete the SIM profile.
2. Delete the `pool-fp16-iccid` IP pool.

**Group 5 (`iccid_apn` mode):**
1. Delete the SIM profile.
2. Delete the `pool-fp16-icapn` IP pool.
