# Test Suite 17 — Immediate Provisioning Mode

## What this test suite validates

This suite verifies the "immediate" provisioning mode for range configurations, where the system automatically allocates IPs to every SIM in the range as soon as the configuration is created (for plain IMSI ranges) or as soon as the last IMSI slot is added (for ICCID ranges). It also confirms that the lookup service can serve those SIMs immediately without requiring a first-connection call, that first-connection is safely idempotent for already-provisioned SIMs, and that invalid configuration inputs are properly rejected.

## Pre-conditions (Setup)

**Group 1 — Single-IMSI immediate provisioning:**
1. Force-delete any leftover terminated profiles for the test IMSI range (`278771700000001` to `278771700000005`).
2. Create an IP pool (`pool-imm17-imsi`) in subnet `100.65.195.0/24`.

**Group 2 — ICCID range immediate provisioning:**
1. Force-delete any leftover terminated profiles for both IMSI slot ranges (slot 1 and slot 2).
2. Create an IP pool (`pool-imm17-iccid`) in subnet `100.65.196.0/24`.

## Test 17.1 — Creating a range config with immediate mode returns a job ID

**Goal:** Confirm that submitting a range configuration with `provisioning_mode="immediate"` triggers an asynchronous provisioning job immediately.

1. Send a request to `POST /range-configs` with IMSI range `278771700000001` to `278771700000005`, using `ip_resolution="imsi"` and `provisioning_mode="immediate"`.
2. Verify the response contains both an `id` (the range config ID) and a `job_id`.

## Test 17.2 — The provisioning job completes and processes all 5 SIMs

**Goal:** Confirm the background job successfully provisions all 5 SIMs in the range.

1. Repeatedly check `GET /jobs/{job_id}` until the job status is `completed` or `failed` (up to 5 minutes).
2. Verify the final status is `completed`.
3. Verify `processed = 5` and `failed = 0`.

## Test 17.3 — Pool statistics show 5 IPs allocated after the job completes

**Goal:** Confirm that the pool tracking reflects the provisioning.

1. Send a request to `GET /pools/{pool_id}/stats`.
2. Verify `allocated >= 5`.

## Test 17.4 — Lookup returns an IP for a provisioned IMSI without a prior first-connection call

**Goal:** Confirm that SIMs provisioned via immediate mode are immediately reachable via the lookup service — no first-connection handshake is needed.

1. Send a request to `GET /lookup?imsi={F_IMSI}&apn=internet.operator.com&use_case_id=...`.
2. Verify the response is HTTP 200 (success).
3. Verify the returned `static_ip` is non-null.

## Test 17.5 — First-connection for an already-provisioned SIM is idempotent

**Goal:** Confirm that calling first-connection for a SIM that was already provisioned via immediate mode returns success without re-allocating a new IP.

1. Send a request to `POST /first-connection` with the same IMSI used in test 17.4.
2. Verify the response is HTTP 200 (success) — not HTTP 201 (meaning no new profile was created).
3. Verify the response contains a non-null `static_ip`.

## Test 17.6 — Deleting the range config removes profiles and returns IPs to the pool

**Goal:** Confirm that deleting the range configuration hard-deletes all provisioned profiles and releases their IPs.

1. Send a `DELETE /range-configs/{id}` request.
2. Send a `POST /first-connection` request for the same IMSI.
3. Verify the response is HTTP 404 (not found) — confirming the profile was hard-deleted.
4. Send a request to `GET /pools/{pool_id}/stats`.
5. Verify `allocated = 0` — all IPs have been returned to the pool.

## Test 17.7 — An unrecognised provisioning mode is rejected with a validation error

**Goal:** Confirm that submitting a range config with an invalid `provisioning_mode` value is rejected before any database writes occur.

1. Send a request to `POST /range-configs` with `provisioning_mode="batch"` (not a valid value).
2. Verify the response is HTTP 400 (bad request / validation error).
3. Verify the response body contains `"error": "validation_failed"`.

## Test 17.8 — Immediate provisioning is blocked when the pool has insufficient capacity

**Goal:** Confirm that the system prevents creating an immediate-mode range config when the target pool cannot hold all the required IPs.

1. Create a tiny IP pool (`pool-imm17-tiny`) in subnet `100.65.197.0/30` (only 2 usable IPs).
2. Send a request to `POST /range-configs` with an IMSI range of 5 SIMs, using the tiny pool and `provisioning_mode="immediate"`.
3. Verify the response is HTTP 503 (service unavailable / pool exhausted).
4. Verify the response body contains `"error": "pool_exhausted"`.
5. Send a request to `GET /range-configs` and confirm that no range config was created for this IMSI range (the transaction was rolled back).
6. Delete the tiny pool.

## Test 17.9 — Creating an ICCID range config with immediate mode does not trigger provisioning yet

**Goal:** Confirm that creating the parent ICCID range config alone (without any IMSI slots) does not start provisioning.

1. Send a request to `POST /iccid-range-configs` with ICCID range `8944501170000000001` to `8944501170000000003`, `imsi_count=2`, and `provisioning_mode="immediate"`.
2. Verify the response contains an `id`.
3. Verify the response does NOT contain a `job_id` (provisioning only fires when the last slot is added).

## Test 17.10 — Adding the first IMSI slot (of 2) does not trigger provisioning

**Goal:** Confirm that provisioning does not start until all required IMSI slots are present.

1. Send a request to `POST /iccid-range-configs/{id}/imsi-slots` for slot 1 (IMSI range for slot 1, 3 cards).
2. Verify the response does NOT contain a `job_id`.
3. Send a request to `GET /pools/{pool_id}/stats`.
4. Verify `allocated = 0` — no IPs have been allocated yet.

## Test 17.11 — Adding the last IMSI slot triggers provisioning and the job completes

**Goal:** Confirm that adding the final required IMSI slot triggers the background provisioning job.

1. Send a request to `POST /iccid-range-configs/{id}/imsi-slots` for slot 2 (the last required slot).
2. Verify the response contains a `job_id`.
3. Poll `GET /jobs/{job_id}` until the job completes.
4. Verify the final job status is `completed`.
5. Send a `POST /first-connection` for the first IMSI of slot 1.
6. Verify the response is HTTP 200 (idempotent) with a non-null `static_ip`, confirming that SIM was already provisioned.

## Test 17.12 — Lookup works for ICCID-range SIMs without a first-connection call

**Goal:** Confirm that SIMs provisioned via an ICCID range with immediate mode are reachable from the lookup service directly.

1. Send a request to `GET /lookup?imsi={F_IMSI_S1}&apn=internet.operator.com&use_case_id=...`.
2. Verify the response is HTTP 200 (success).
3. Verify the returned `static_ip` is non-null.

## Test 17.13 — Deleting the ICCID range config removes all profiles and frees IPs

**Goal:** Confirm that deleting the ICCID range config cleans up all provisioned data.

1. Send a `DELETE /iccid-range-configs/{id}` request.
2. Send a `POST /first-connection` for the first IMSI of slot 1.
3. Verify the response is HTTP 404 (not found) — the profile was hard-deleted.
4. Send a request to `GET /pools/{pool_id}/stats`.
5. Verify `allocated = 0`.

## Post-conditions (Teardown)

**Group 1:**
1. Delete the range config (if it still exists).
2. Delete the `pool-imm17-imsi` pool.

**Group 2:**
1. Delete the ICCID range config (if it still exists).
2. Delete the `pool-imm17-iccid` pool.
