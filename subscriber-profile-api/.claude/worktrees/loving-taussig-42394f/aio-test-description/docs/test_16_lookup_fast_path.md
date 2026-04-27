# Test Suite 16 — Lookup Fast-Path: Input Validation and Suspend/Reactivate

## What this test suite validates

This suite covers three areas not addressed by earlier tests: (1) the lookup service's validation of the IMSI format before it touches the database, (2) SIM-level suspend and reactivate in IMSI mode (where all IMSIs on a profile are blocked or unblocked together), and (3) SIM-level suspend, reactivate, per-IMSI suspend, and concurrent lookups in IMSI-APN mode. These tests confirm that the suspend state is enforced correctly and that releasing a suspension restores full lookup capability.

## Pre-conditions (Setup)

**Group 1 — Parameter validation:** No database records are required.

**Group 2 — IMSI-mode suspend tests:**
1. Clean up any existing profiles whose IMSIs start with the module-16 prefix.
2. Force-delete any leftover terminated profiles for the test IMSI range.
3. Create an IP pool (`pool-fp16-imsi`) in subnet `100.65.180.0/24`.
4. Create a single SIM profile in `imsi` mode with two IMSIs:
   - IMSI_A (`278771600000001`) assigned IP `100.65.180.1`
   - IMSI_B (`278771600000002`) assigned IP `100.65.180.2`

**Group 3 — IMSI-APN-mode suspend tests:**
1. Clean up any existing profiles and force-delete terminated profiles for the test IMSI range.
2. Create an IP pool (`pool-fp16-iapn`) in subnet `100.65.181.0/24`.
3. Create a single SIM profile in `imsi_apn` mode with two IMSIs, each configured for two APNs:
   - IMSI_A (`278771600000011`): internet APN → IP `100.65.181.1`, IMS APN → IP `100.65.181.2`
   - IMSI_B (`278771600000012`): internet APN → IP `100.65.181.3`, IMS APN → IP `100.65.181.4`

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

## Test 16.5 — Valid IMSI that is not registered returns "not found"

**Goal:** Confirm that a correctly formatted IMSI that was never provisioned returns a 404 response, not a server error.

1. Send a request to `GET /lookup?imsi={valid_unregistered_imsi}&apn=internet.operator.com&use_case_id=...` using a correctly formatted 15-digit IMSI that was never provisioned.
2. Verify the response is HTTP 404 (not found).
3. Verify the response body contains `"error": "not_found"`.

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

## Post-conditions (Teardown)

**Group 2 (IMSI mode):**
1. Delete the SIM profile.
2. Delete the `pool-fp16-imsi` IP pool.

**Group 3 (IMSI-APN mode):**
1. Delete the SIM profile.
2. Delete the `pool-fp16-iapn` IP pool.
