# Test Suite 19 — ICCID/IMSI Range Config Validation and APN-Pool Management

## What this test suite validates

This suite verifies input validation and management operations for ICCID range configurations and their associated IMSI slots. It is organized into five groups: (A) validation of ICCID range creation fields, (B) validation of IMSI slot inputs including cardinality enforcement, (C) full CRUD lifecycle for APN-pool overrides on a slot, (D) the "skip-ICCID" mode where a range config is created without ICCID bounds, and (E) enforcement that all slots share the same cardinality as the ICCID range.

## Pre-conditions (Setup)

**Group A (ICCID Range validation):** No database resources required — all requests are rejected before any writes.

**Group B (IMSI Slot validation):**
1. Create a pool (`t19b-pool`) in subnet `100.65.220.0/28`.
2. Create a 10-card ICCID range config (ICCID `8944501190000000001` to `8944501190000000010`, `imsi_count=1`).

**Group C (APN Pool management):**
1. Create two pools: `t19c-internet` in subnet `100.65.220.16/28` and `t19c-ims` in `100.65.220.32/28`.
2. Create a 5-card ICCID range config (`imsi_count=1`, `ip_resolution="imsi_apn"`).
3. Add slot 1 with 5 IMSIs (matching the 5-card cardinality).

**Group D (Skip-ICCID mode):**
1. Create a pool (`t19d-pool`) in subnet `100.65.220.48/28`.

**Group E (Size alignment):**
1. Create a pool (`t19e-pool`) in subnet `100.65.220.64/28`.
2. Create a 5-card ICCID range config (`imsi_count=2`).
3. Add slot 1 with exactly 5 IMSIs.

---

## Group A — ICCID Range Creation Validation

### Test 19.A.1 — Inverted ICCID range is rejected

**Goal:** Confirm that submitting a range where the start ICCID is greater than the end ICCID fails validation.

1. Send a request to `POST /iccid-range-configs` where `f_iccid` is `8944501190000000010` and `t_iccid` is `8944501190000000001` (reversed).
2. Verify the response is HTTP 400 (bad request).
3. Verify the response contains `"error": "validation_failed"`.

### Test 19.A.2 — ICCID with too few digits (18) is rejected

**Goal:** Confirm that ICCIDs must be exactly 19 digits.

1. Send a request to `POST /iccid-range-configs` with an 18-digit `f_iccid`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.A.3 — ICCID with too many digits (21) is rejected

**Goal:** Confirm the upper bound on ICCID length.

1. Send a request to `POST /iccid-range-configs` with a 21-digit `t_iccid`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.A.4 — Non-numeric ICCID is rejected

**Goal:** Confirm that ICCIDs must contain only digits.

1. Send a request to `POST /iccid-range-configs` with an `f_iccid` that contains letters (e.g. `ABCDE01190000000001`).
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.A.5 — Providing only one ICCID bound is rejected

**Goal:** Confirm that both `f_iccid` and `t_iccid` are required together.

1. Send a request to `POST /iccid-range-configs` with `f_iccid` but no `t_iccid`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.A.6 — imsi_count of zero is rejected

**Goal:** Confirm that the IMSI slot count must be at least 1.

1. Send a request to `POST /iccid-range-configs` with `imsi_count=0`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.A.7 — imsi_count above the maximum (11) is rejected

**Goal:** Confirm the upper limit on IMSI slots per card.

1. Send a request to `POST /iccid-range-configs` with `imsi_count=11`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.A.8 — Unknown ip_resolution value is rejected

**Goal:** Confirm that only the four supported IP resolution modes are accepted.

1. Send a request to `POST /iccid-range-configs` with `ip_resolution="foobar"`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

---

## Group B — IMSI Slot Validation

### Test 19.B.1 — Inverted IMSI range is rejected

**Goal:** Confirm that the start IMSI must be less than the end IMSI.

1. Send a request to add a slot where `f_imsi` is greater than `t_imsi`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.B.2 — IMSI with too few digits (14) is rejected

**Goal:** Confirm IMSIs must be exactly 15 digits.

1. Send a request to add a slot with a 14-digit `f_imsi`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.B.3 — IMSI with too many digits (16) is rejected

**Goal:** Confirm the upper bound on IMSI length.

1. Send a request to add a slot with a 16-digit `t_imsi`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.B.4 — Slot number of zero is rejected

**Goal:** Confirm that IMSI slots must be numbered starting from 1.

1. Send a request to add a slot with `imsi_slot=0`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.B.5 — Slot number above the maximum (11) is rejected

**Goal:** Confirm the upper limit on slot numbers.

1. Send a request to add a slot with `imsi_slot=11`.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.B.6 — IMSI range with one extra IMSI (cardinality too high) is rejected

**Goal:** Confirm that the number of IMSIs in a slot must exactly match the number of ICCIDs in the range.

1. The ICCID range has 10 cards. Send a request to add a slot with 11 IMSIs (one too many).
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.
3. Verify the error message contains the word "cardinality".

### Test 19.B.7 — IMSI range with one fewer IMSI (cardinality too low) is rejected

**Goal:** Confirm cardinality checking also catches under-counts.

1. Send a request to add a slot with 9 IMSIs (one too few) for a 10-card range.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.B.8 — A correctly sized slot is accepted

**Goal:** Confirm that a slot with exactly the right number of IMSIs is created successfully.

1. Send a request to add slot 1 with exactly 10 IMSIs for the 10-card ICCID range.
2. Verify the response is HTTP 201 (created) and contains a `range_config_id`.

### Test 19.B.9 — Submitting the same slot number again is rejected as a duplicate

**Goal:** Confirm that each slot number can only be registered once per ICCID range config.

1. Send a second request to add slot 1 with the same IMSI range as in test B.8.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.
3. Verify the error message contains the word "already exists".

---

## Group C — APN Pool Management (CRUD)

### Test 19.C.1 — Newly created slot has no APN pool entries

**Goal:** Confirm that the APN pool list for a fresh slot is empty.

1. Send a request to `GET /iccid-range-configs/{id}/imsi-slots/{slot}/apn-pools`.
2. Verify the response is HTTP 200 (success) with `items = []`.

### Test 19.C.2 — Adding an internet APN pool entry succeeds

**Goal:** Confirm an APN-pool mapping can be added to a slot.

1. Send a request to `POST .../apn-pools` with `apn="internet.operator.com"` and the internet pool ID.
2. Verify the response is HTTP 201 (created).
3. Verify the response body contains the correct `apn` and `pool_id`.

### Test 19.C.3 — The APN pool list now includes the internet APN

**Goal:** Confirm the list reflects the newly added entry.

1. Send a request to `GET .../apn-pools`.
2. Verify the response is HTTP 200 (success) and `items` has exactly 1 entry with `apn="internet.operator.com"`.

### Test 19.C.4 — Adding an IMS APN pool entry succeeds

**Goal:** Confirm a second APN entry can be added to the same slot.

1. Send a request to `POST .../apn-pools` with `apn="ims.operator.com"` and the IMS pool ID.
2. Verify the response is HTTP 201 (created).

### Test 19.C.5 — The APN pool list now has two entries

**Goal:** Confirm both APN entries are returned by the list.

1. Send a request to `GET .../apn-pools`.
2. Verify the response is HTTP 200 (success) and `items` has exactly 2 entries.
3. Verify both `internet.operator.com` and `ims.operator.com` are present.

### Test 19.C.6 — Registering the same APN a second time is rejected

**Goal:** Confirm duplicate APN entries are not allowed on the same slot.

1. Send a request to `POST .../apn-pools` with `apn="internet.operator.com"` again.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.
3. Verify the error message contains the word "already".

### Test 19.C.7 — Referencing a non-existent pool ID is rejected

**Goal:** Confirm that APN entries must reference a valid, existing pool.

1. Send a request to `POST .../apn-pools` with a made-up pool UUID.
2. Verify the response is HTTP 400 (bad request) with `"error": "validation_failed"`.

### Test 19.C.8 — Deleting an APN entry succeeds

**Goal:** Confirm an APN-pool mapping can be removed.

1. Send a request to `DELETE .../apn-pools/internet.operator.com`.
2. Verify the response is HTTP 204 (no content / success).

### Test 19.C.9 — After deletion, only the IMS APN remains in the list

**Goal:** Confirm the list correctly reflects the deletion.

1. Send a request to `GET .../apn-pools`.
2. Verify `items` has exactly 1 entry with `apn="ims.operator.com"`.

### Test 19.C.10 — Deleting an already-removed APN returns "not found"

**Goal:** Confirm deleting a non-existent APN entry returns an appropriate error.

1. Send a request to `DELETE .../apn-pools/internet.operator.com` again.
2. Verify the response is HTTP 404 (not found) with `"error": "not_found"`.

### Test 19.C.11 — Requesting APN pools for a non-existent slot number returns "not found"

**Goal:** Confirm the API handles requests for slots that do not exist.

1. Send a request to `GET /iccid-range-configs/{id}/imsi-slots/99/apn-pools`.
2. Verify the response is HTTP 404 (not found) with `"error": "not_found"`.

---

## Group D — Skip-ICCID Mode (IMSI-Only Range Config)

### Test 19.D.1 — Creating a range config without ICCID bounds succeeds

**Goal:** Confirm that an ICCID range config can be created without providing `f_iccid` or `t_iccid`, acting as a pure IMSI grouping.

1. Send a request to `POST /iccid-range-configs` with `ip_resolution="imsi"` and `imsi_count=1`, but without `f_iccid` or `t_iccid`.
2. Verify the response is HTTP 201 (created) and contains an `id`.

### Test 19.D.2 — A slot added to a skip-ICCID config accepts any IMSI range size

**Goal:** Confirm that without an ICCID cardinality constraint, any number of IMSIs is valid.

1. Send a request to add slot 1 with 8 IMSIs (which would fail cardinality checks on a normal ICCID range, but is fine here).
2. Verify the response is HTTP 201 (created).

### Test 19.D.3 — First-connection by IMSI works on a skip-ICCID config

**Goal:** Confirm that SIMs in a skip-ICCID config can still connect and receive an IP via first-connection.

1. Send a `POST /first-connection` for an IMSI within the slot's range.
2. Verify the response is HTTP 201 (created) with a non-null `static_ip`.

---

## Group E — IMSI Slot Cardinality Alignment Enforcement

### Test 19.E.1 — Slot 2 with too few IMSIs is rejected

**Goal:** Every slot on a 5-card ICCID range must contain exactly 5 IMSIs.

1. Send a request to add slot 2 with 4 IMSIs (diff=3, but need diff=4 for 5 cards).
2. Verify the response is HTTP 400 (bad request) with a cardinality mismatch error.
3. Verify the error message references the number 4.

### Test 19.E.2 — Slot 2 with too many IMSIs is rejected

**Goal:** Confirm the upper cardinality bound is enforced.

1. Send a request to add slot 2 with 6 IMSIs (diff=5, but need diff=4 for 5 cards).
2. Verify the response is HTTP 400 (bad request) with a cardinality mismatch error.

### Test 19.E.3 — Slot 2 with the correct count is accepted

**Goal:** Confirm that exactly 5 IMSIs (matching the 5-card ICCID range) is accepted.

1. Send a request to add slot 2 with exactly 5 IMSIs.
2. Verify the response is HTTP 201 (created).

### Test 19.E.4 — Updating slot 1 with the wrong cardinality is rejected

**Goal:** Confirm that `PATCH` on an existing slot also enforces cardinality.

1. Send a request to `PATCH /iccid-range-configs/{id}/imsi-slots/1` with a 4-IMSI range.
2. Verify the response is HTTP 400 (bad request) with a cardinality mismatch error.

### Test 19.E.5 — Updating slot 1 with the correct cardinality succeeds

**Goal:** Confirm that a valid PATCH with the correct count is accepted.

1. Send a request to `PATCH /iccid-range-configs/{id}/imsi-slots/1` with exactly 5 IMSIs.
2. Verify the response is HTTP 200 (success).

### Test 19.E.6 — The slot list confirms all slots have matching cardinality

**Goal:** Confirm the final state: both registered slots have a cardinality equal to the ICCID range size.

1. Send a request to `GET /iccid-range-configs/{id}/imsi-slots`.
2. Verify the response is HTTP 200 (success) and `items` has 2 entries.
3. For each slot, verify that `t_imsi - f_imsi` equals `t_iccid - f_iccid` (i.e., both slots match the 5-card size).

## Post-conditions (Teardown)

Each group independently deletes its ICCID range config and any pools it created.
