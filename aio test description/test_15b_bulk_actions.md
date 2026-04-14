# Test Suite 15b — Bulk Actions (IP Release and IMSI Deletion)

## What this test suite validates

This suite verifies two bulk action APIs: `POST /profiles/bulk-release-ips` (which releases IP address allocations for multiple SIM profiles at once, returning those IPs to the pool for reuse) and `POST /imsis/bulk-delete` (which removes a batch of IMSIs from profiles and returns their IPs to the pool). Both JSON and CSV input formats are tested, along with validation error handling.

## Pre-conditions (Setup)

1. Create one IP address pool (`pool-bulk-08b`) in subnet `100.65.197.0/28` (14 usable IPs), scoped to account `BulkActionAccount`.
2. Create a range configuration covering IMSIs `278770760000001` through `278770760000099`, using `imsi` IP resolution, linked to the above pool.
3. Define three groups of test IMSIs (all within the pool's IMSI range):
   - **Release-by-list group** (4 IMSIs): used in tests 15b.2 and 15b.3.
   - **Release-by-filter group** (4 IMSIs): used in test 15b.4.
   - **IMSI-delete group** (4 IMSIs): used in tests 15b.6 and 15b.7.

## Test 15b.1 — Set up: allocate IPs for all 12 test IMSIs via first-connection

**Goal:** Establish a known starting state with all 12 test IMSIs having IPs allocated.

1. For each of the 12 test IMSIs (all three groups), send a `POST /first-connection` request with the IMSI and APN `internet.operator.com`.
2. Verify each request returns HTTP 201 (created) and a non-null IP address.
3. Send a request to `GET /pools/{pool_id}/stats`.
4. Verify `allocated = 12` (all 12 IPs consumed from the pool).

## Test 15b.2 — Bulk release IPs for an explicit list of SIM IDs

**Goal:** Confirm that specifying a list of SIM IDs releases their IPs and returns them to the pool, while the SIM profiles themselves remain intact.

1. For each IMSI in the release-by-list group (4 IMSIs), send a request to `GET /profiles?imsi={imsi}` and note the `sim_id`.
2. Record the pool's current `available` count.
3. Send a request to `POST /profiles/bulk-release-ips` with the body `{"sim_ids": [...4 IDs...]}`.
4. Verify the response is HTTP 202 (accepted), and that `submitted = 4`.
5. Poll `GET /jobs/{job_id}` until the job completes.
6. Verify `processed = 4`, `failed = 0`.
7. Send a request to `GET /pools/{pool_id}/stats`.
8. Verify `available` has increased by exactly 4 (the IPs were returned to the pool).
9. For each IMSI in the group, send a request to `GET /profiles?imsi={imsi}`.
10. Verify the profile still exists but has no IP bindings (`apn_ips` is empty).

## Test 15b.3 — Releasing already-released SIMs is safe (idempotent)

**Goal:** Confirm that trying to release IPs for SIMs that have already been released does not cause errors.

1. Send a request to `POST /profiles/bulk-release-ips` with the same 4 SIM IDs as in test 15b.2.
2. Verify the response is HTTP 202 (accepted).
3. Poll `GET /jobs/{job_id}` until the job completes.
4. Verify `status = "completed"`, `processed = 4`, `failed = 0`.

## Test 15b.4 — Bulk release by account-name filter releases all matching SIMs

**Goal:** Confirm that instead of providing explicit SIM IDs, a filter (account name) can be used to release IPs for all matching active SIMs.

1. Record the pool's current allocated and available counts.
2. Verify the release-by-filter group (4 IMSIs) still has IPs allocated.
3. Send a request to `POST /profiles/bulk-release-ips` with body `{"account_name": "BulkActionAccount"}`.
4. Verify the response is HTTP 202 (accepted), and that `submitted` is at least 4.
5. Poll `GET /jobs/{job_id}` until the job completes.
6. Verify `failed = 0`.
7. Send a request to `GET /pools/{pool_id}/stats`.
8. Verify `available` has increased by at least 4.

## Test 15b.5 — Bulk release validation: empty body rejected, unknown SIM ID recorded as failure

**Goal:** Confirm input validation works: no filters provided is rejected immediately, and an unknown SIM ID is recorded as a job failure rather than crashing.

1. Send a request to `POST /profiles/bulk-release-ips` with an empty JSON body `{}`.
2. Verify the response is HTTP 400 (bad request / validation error).
3. Send a request to `POST /profiles/bulk-release-ips` with a made-up SIM ID.
4. Verify the response is HTTP 202 (accepted).
5. Poll `GET /jobs/{job_id}` until the job completes.
6. Verify `failed = 1` and the error entry identifies the unknown SIM ID.

## Test 15b.6 — Bulk IMSI deletion via JSON removes IMSIs and returns IPs to the pool

**Goal:** Confirm that bulk-deleting IMSIs via a JSON list removes them from the system and frees their IPs.

1. Re-allocate IPs for the IMSI-delete group (4 IMSIs) by sending a `POST /first-connection` request for each.
2. Record the pool's current available count.
3. Send a request to `POST /imsis/bulk-delete` with body `{"imsis": [...4 IMSIs...]}`.
4. Verify the response is HTTP 202 (accepted) and `submitted = 4`.
5. Poll `GET /jobs/{job_id}` until the job completes.
6. Verify `processed = 4`, `failed = 0`.
7. Send a request to `GET /pools/{pool_id}/stats`.
8. Verify `available` has increased by exactly 4.
9. For each deleted IMSI, send a request to `GET /profiles?imsi={imsi}`.
10. Verify the response is HTTP 404 (not found) — the IMSI no longer exists.

## Test 15b.7 — Bulk IMSI deletion via CSV file produces the same result as JSON

**Goal:** Confirm that bulk IMSI deletion also works when the IMSI list is provided as a CSV file attachment.

1. Build a CSV file containing the 4 IMSIs from the release-by-list group (these were released but their IMSIs are still linked to profiles).
2. Send a `POST /imsis/bulk-delete` request with the CSV file as a multipart form-data attachment.
3. Verify the response is HTTP 202 (accepted) and `submitted = 4`.
4. Poll `GET /jobs/{job_id}` until the job completes.
5. Verify `processed = 4`, `failed = 0`.
6. For each IMSI in the CSV, send a request to `GET /profiles?imsi={imsi}`.
7. Verify the response is HTTP 404 (not found).

## Test 15b.8 — Bulk IMSI deletion validation: invalid format and unknown IMSI both fail, empty body is rejected

**Goal:** Confirm that badly formatted IMSIs and IMSIs not found in the database are recorded as failures, and that an empty request body is rejected outright.

1. Send a request to `POST /imsis/bulk-delete` with body `{"imsis": ["12345", "999999999999999"]}` (first is too short; second is validly formatted but not in the database).
2. Verify the response is HTTP 202 (accepted).
3. Poll `GET /jobs/{job_id}` until the job completes.
4. Verify `status = "completed"`, `failed = 2`, `processed = 0`.
5. Verify the error entries identify both of the invalid IMSIs.
6. Send a request to `POST /imsis/bulk-delete` with an empty body `{}`.
7. Verify the response is HTTP 400 (bad request).

## Post-conditions (Teardown)

1. Delete any remaining SIM profiles from all three test IMSI groups.
2. Delete the range configuration.
3. Delete the `pool-bulk-08b` IP address pool.
