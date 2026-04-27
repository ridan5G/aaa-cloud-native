# Test Suite 02 — IMSI Range Config CRUD

## What this test suite validates
This suite verifies the full lifecycle of IMSI range configurations — the rules that map a contiguous block of IMSI numbers to a specific IP pool and define how IPs are resolved for that block. It covers creating, reading, listing, updating, suspending, and deleting range configs, as well as validating that malformed inputs are rejected.

## Pre-conditions (Setup)
1. The subscriber-profile-api service is running and reachable.
2. Two IP pools are created before the tests begin:
   - Pool 1: subnet `100.65.130.0/24`, named `rc-pool-1`, for account `Melita`
   - Pool 2: subnet `100.65.131.0/24`, named `rc-pool-2`, for account `Melita`
3. Both pools are reused across all tests in the suite. If either already exists (from a previous run), the existing pool is reused.
4. Tests 2.1 through 2.6 share a single range config and must run in order.

---

## Test 2.1 — Create a new range config

**Goal:** Confirm that a range config covering a valid IMSI range can be created successfully.

1. Send a request to create a range config for account `Melita`, covering IMSIs `278773020000001` through `278773020000999`, linked to Pool 1, with IP resolution mode `imsi`.
2. Verify the response is HTTP 201 (created).
3. Verify the response body contains an `id` field.
4. Save the `id` for use in subsequent tests.

---

## Test 2.2 — Retrieve the range config by ID

**Goal:** Confirm that the newly created range config can be fetched and all its fields are correct.

1. Send a GET request for the range config using the `id` saved in test 2.1.
2. Verify the response is HTTP 200 (success).
3. Verify `f_imsi` equals `278773020000001`.
4. Verify `t_imsi` equals `278773020000999`.
5. Verify `pool_id` matches Pool 1's ID.
6. Verify `ip_resolution` equals `imsi`.
7. Verify `status` equals `active`.

---

## Test 2.3 — List range configs filtered by account name

**Goal:** Confirm that filtering range configs by account name returns the expected config.

1. Send a request to list all range configs for account `Melita`.
2. Verify the response is HTTP 200 (success).
3. Verify the range config created in test 2.1 appears in the returned list.

---

## Test 2.4 — Update the pool and IP resolution mode

**Goal:** Confirm that a range config's linked pool and IP resolution mode can both be changed in a single PATCH request.

1. Send a PATCH request for the range config, updating `pool_id` to Pool 2's ID and `ip_resolution` to `imsi_apn`.
2. Verify the response is HTTP 200 (success).
3. Retrieve the range config and verify `pool_id` now equals Pool 2's ID.
4. Verify `ip_resolution` now equals `imsi_apn`.

---

## Test 2.5 — Suspend a range config

**Goal:** Confirm that a range config can be suspended, which would prevent new subscriber allocations from being made against it.

1. Send a PATCH request to set the range config's `status` to `suspended`.
2. Verify the response is HTTP 200 (success).
3. Retrieve the range config and verify `status` equals `suspended`.

---

## Test 2.6 — Delete a range config

**Goal:** Confirm that a range config can be deleted.

1. Send a DELETE request for the range config.
2. Verify the response is HTTP 204 (deleted successfully).

---

## Test 2.7 — Reject an inverted IMSI range

**Goal:** Confirm that a range config where the start IMSI is greater than the end IMSI is rejected as invalid input.

1. Send a request to create a range config where `f_imsi` is set to `278773020000999` (the larger number) and `t_imsi` is set to `278773020000001` (the smaller number) — an inverted range.
2. Verify the response is HTTP 400 (bad request).
3. Verify the response body contains `error: validation_failed`.

---

## Test 2.8 — Reject a non-15-digit IMSI

**Goal:** Confirm that IMSI values that do not conform to the standard 15-digit format are rejected.

1. Send a request to create a range config using `f_imsi` value `27877302000000` (only 14 digits).
2. Verify the response is HTTP 400 (bad request).
3. Verify the response body contains `error: validation_failed`.

---

## Post-conditions (Teardown)
1. After all tests complete, any remaining range config is deleted.
2. Both IP pools (Pool 1 and Pool 2) created during setup are deleted.
