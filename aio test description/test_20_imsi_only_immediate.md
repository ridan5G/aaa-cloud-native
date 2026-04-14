# Test Suite 20 — IMSI-Only Immediate Provisioning (All IP Resolution Modes)

## What this test suite validates

This suite verifies that "skip-ICCID" range configurations (created without ICCID bounds) work correctly in `provisioning_mode="immediate"` across all four IP resolution types: `imsi`, `imsi_apn`, `iccid`, and `iccid_apn`. When all required IMSI slots have been added, the system triggers a background job that provisions every virtual card in the group, allocates IPs, and makes the SIMs immediately reachable via the lookup service without any first-connection handshake. The suite also verifies clean deletion and cross-slot cardinality validation.

## Pre-conditions (Setup)

Each of the six groups (A–F) sets up its own pools and clears stale profiles. All subnets are in the `100.73.230.x`–`100.73.237.x` range. Each group uses 5 virtual cards (CARDS = 5) and varies the number of slots and APNs depending on the resolution type.

---

## Group A — ip_resolution="imsi" (per-IMSI IP allocation, 3 slots, 5 cards)

**Setup:** Create pool `t20a-pool` (subnet `100.73.230.0/24`). Force-clear any stale profiles for all three slot ranges.

### Test 20.A.1 — Create IMSI-only immediate config without ICCID bounds

**Goal:** Confirm the config is created without immediately triggering a job (provisioning waits for all slots).

1. Send a request to `POST /iccid-range-configs` with `ip_resolution="imsi"`, `imsi_count=3`, `provisioning_mode="immediate"`, and no `f_iccid`/`t_iccid`.
2. Verify the response contains an `id`.
3. Verify the response does NOT contain a `job_id` (job fires only after the last slot is added).

### Test 20.A.2 — Adding slot 1 of 3 does not trigger provisioning

**Goal:** Confirm the job is not triggered until all slots are present.

1. Send a request to add slot 1 with the appropriate IMSI range (5 cards).
2. Verify the response does NOT contain a `job_id`.

### Test 20.A.3 — Adding slot 2 of 3 still does not trigger provisioning

**Goal:** Confirm provisioning waits for the last slot.

1. Send a request to add slot 2.
2. Verify the response does NOT contain a `job_id`.
3. Verify the pool still shows `allocated = 0`.

### Test 20.A.4 — Adding the last slot (3 of 3) triggers the provisioning job

**Goal:** Confirm that adding the final slot fires the background job.

1. Send a request to add slot 3.
2. Verify the response contains a `job_id`.

### Test 20.A.5 — The provisioning job completes with correct counts and the config is marked "provisioned"

**Goal:** Confirm the job runs to completion and updates the range config status.

1. Poll `GET /jobs/{job_id}` until the status is terminal.
2. Verify `status = "completed"`, `processed = 5` (5 cards), `failed = 0`.
3. Verify the job response links back to the range config via `range_config_id`.
4. Send a request to `GET /iccid-range-configs/{id}`.
5. Verify the range config's `status = "provisioned"`.

### Test 20.A.6 — Pool shows the correct number of allocated IPs

**Goal:** Confirm the pool tracking reflects all provisioned slots and cards.

1. Send a request to `GET /pools/{pool_id}/stats`.
2. Verify `allocated >= 15` (5 cards × 3 slots = 15 per-IMSI IPs).

### Tests 20.A.7–20.A.9 — Lookup for each slot returns a valid IP (no first-connection needed)

**Goal:** Confirm all three slots are reachable from the lookup service without a first-connection step.

1. For slot 1: send `GET /lookup?imsi={first_imsi_of_slot1}&apn=internet.operator.com&use_case_id=...`; verify HTTP 200 (success) with a non-null `static_ip`.
2. For slot 2: send the equivalent lookup; verify HTTP 200 with a non-null IP.
3. For slot 3: send the equivalent lookup; verify HTTP 200 with a non-null IP.

---

## Group B — ip_resolution="imsi_apn" (per-IMSI per-APN IPs, 4 slots, 5 cards, 2 APNs per slot)

**Setup:** Create two pools: `t20b-internet` and `t20b-ims`. Four slots are used (`imsi_count=4`) so that slots 1–3 are fully configured with APN pools before slot 4 triggers the background job, avoiding a race condition where the job might run before APN pool entries are committed.

### Tests 20.B.1–20.B.7 — Sequential slot and APN pool configuration, then trigger

**Goal:** Confirm each step of the multi-slot setup works and the job fires only on the last slot.

1. Create the config with `imsi_count=4`.
2. Add slot 1; confirm no job triggered.
3. Add APN pool entries (internet, IMS) to slot 1.
4. Add slot 2; confirm no job triggered.
5. Add APN pool entries to slot 2.
6. Add slot 3 with APN pools; confirm no job triggered.
7. Add slot 4 (the last slot); verify the response contains a `job_id`.
8. Add APN pools to slot 4 (best effort — slots 1–3 guarantee correctness).

### Tests 20.B.8–20.B.10 — Job completes and pools show sufficient allocation

1. Poll `GET /jobs/{job_id}` until terminal.
2. Verify `status = "completed"`, `processed = 5`, `failed = 0`.
3. Verify `range_config_id` is set in the job and the config status is `"provisioned"`.
4. Verify the internet pool has at least 15 allocated IPs (5 cards × 3 race-free slots).
5. Verify the IMS pool has at least 15 allocated IPs.

### Tests 20.B.11–20.B.12 — Lookup returns correct per-APN IPs

1. Send `GET /lookup` for slot-1's IMSI with the internet APN; verify HTTP 200 with a non-null IP.
2. Send `GET /lookup` for slot-1's IMSI with the IMS APN; verify HTTP 200 with a different IP.

---

## Group C — ip_resolution="iccid" (card-level shared IP, 3 slots, 5 cards)

**Setup:** Create pool `t20c-pool`. In `iccid` mode, only slot 1 drives IP allocation; all slots share the same card-level IP.

### Tests 20.C.1–20.C.N — Config creation, slot addition, job completion, lookup

1. Create the config with `ip_resolution="iccid"`, `imsi_count=3`, `provisioning_mode="immediate"`.
2. Add slots 1, 2, and 3 (last slot triggers job).
3. Verify the job completes with `processed = 5`, `failed = 0`.
4. Verify the pool shows exactly 5 allocated IPs (one per card, not per slot).
5. Verify lookup for slot-1's IMSI returns a valid IP.
6. Verify lookup for slot-2's IMSI returns the same card-level IP as slot 1.

---

## Group D — ip_resolution="iccid_apn" (card-level per-APN IPs, 3 slots, 5 cards, 2 APNs on slot 1)

**Setup:** Create two pools (`t20d-internet` and `t20d-ims`). In `iccid_apn` mode, APN pools on slot 1 drive card-level IP allocation.

### Tests 20.D.1–20.D.N — Config creation, APN configuration on slot 1, job completion, lookup

1. Create the config with `ip_resolution="iccid_apn"`, `imsi_count=3`, `provisioning_mode="immediate"`.
2. Add slot 1 with APN pools for internet and IMS.
3. Add slots 2 and 3 (last slot triggers job).
4. Verify the job completes with `processed = 5`, `failed = 0`.
5. Verify the internet pool shows 5 allocated IPs (one per card).
6. Verify the IMS pool shows 5 allocated IPs.
7. Verify lookup for slot-1's IMSI with internet APN returns a valid IP.
8. Verify lookup for the same IMSI with IMS APN returns a different IP.

---

## Group E — Deletion: IMSI-only immediate config is fully cleaned up

**Setup:** Create pool `t20e-pool`. Create a 3-slot `imsi` config and run it to completion (following the same steps as Group A).

### Tests 20.E.1–20.E.N — Delete the config and confirm cleanup

1. After provisioning completes, send a `DELETE /iccid-range-configs/{id}` request.
2. Send a `POST /first-connection` for a previously provisioned IMSI.
3. Verify the response is HTTP 404 (not found) — profiles were hard-deleted.
4. Send a request to `GET /pools/{pool_id}/stats`.
5. Verify `allocated = 0` — all IPs were returned to the pool.

---

## Group F — Validation: Cross-slot cardinality mismatch is rejected

**Setup:** No pool required; requests are expected to fail before any resource allocation.

### Test 20.F.1 — Adding a second slot with a different card count is rejected

**Goal:** Confirm that in IMSI-only mode (no ICCID cardinality from a physical range), the system still enforces that all slots have the same number of IMSIs.

1. Create a config without ICCID bounds, `imsi_count=2`.
2. Add slot 1 with 5 IMSIs (cards = 5).
3. Attempt to add slot 2 with 3 IMSIs (cards = 3 — a mismatch).
4. Verify the response is HTTP 400 (bad request) with a cardinality mismatch error.

## Post-conditions (Teardown)

Each group independently deletes its range config and pools.
