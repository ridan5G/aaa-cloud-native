# Test Suite 11 — Performance and Latency

## What this test suite validates

This suite measures the end-to-end response latency of the lookup service and provisioning API under various load conditions, using a pre-seeded dataset of 300,000 subscriber profiles. It verifies that the system meets specific latency thresholds (p99 = 99th-percentile response time) for sequential lookups, concurrent lookups at 50 and 200 simultaneous users, bulk import jobs running in parallel, concurrent first-connection requests with no duplicate IP allocation, pool statistics queries at scale, and individual profile retrieval.

**Note:** This test suite is tagged for optional execution. It is excluded from the default CI run and must be enabled explicitly (e.g., `pytest -m slow`). The dataset seed step takes approximately 3 minutes and is preserved between runs to avoid repeated seeding costs.

## Pre-conditions (Setup)

1. The system checks whether the 300,000-profile dataset is already present (by checking if the first seed IMSI has a profile).
2. If the dataset is not present:
   - A large IP pool is created: subnet `100.68.0.0/14`, which provides over 260,000 usable addresses.
   - 300,000 subscriber profiles are inserted in batches of 1,000 using the bulk import API.
   - Each batch is submitted as an async job and polled to completion before the next batch starts.
3. If the dataset is already present, setup skips seeding and reuses the existing data.

---

## Test 11.1 — Sequential lookup p99 latency ≤ 15 ms

**Goal:** Confirm that 100 back-to-back lookup requests, each targeting a different pre-seeded IMSI, complete within the latency threshold at the 99th percentile.

1. Send 100 sequential lookup requests, each for a different IMSI from the seeded dataset, with the internet APN.
2. Confirm each request returns HTTP 200 (success).
3. Record the response time for each request.
4. Calculate the p99 latency (99th-percentile response time).
5. Confirm p99 ≤ 15 ms.

---

## Test 11.2 — 50 concurrent lookups: p99 ≤ 15 ms, zero errors

**Goal:** When 50 lookup requests are fired simultaneously, latency stays within the threshold and all requests succeed.

1. Prepare 50 lookup requests, each for a different IMSI in the seeded dataset.
2. Fire all 50 requests concurrently.
3. Collect the status code and latency for each response.
4. Confirm zero errors (all responses are HTTP 200).
5. Calculate p99 across all 50 latency samples.
6. Confirm p99 ≤ 15 ms.

---

## Test 11.3 — 200 concurrent lookups (stress): p99 ≤ 30 ms, zero errors

**Goal:** Under a heavier simultaneous load of 200 requests, latency is allowed to be up to 30 ms at p99, and all requests must still succeed.

1. Prepare 200 lookup requests, each for a different IMSI.
2. Fire all 200 requests concurrently.
3. Confirm zero errors (all HTTP 200).
4. Calculate p99 across all 200 latency samples.
5. Confirm p99 ≤ 30 ms.

---

## Test 11.4 — 10 concurrent bulk import jobs all complete successfully

**Goal:** The bulk import API can handle 10 simultaneous jobs (100 profiles each) without any failures.

1. Simultaneously submit 10 bulk import jobs, each containing 100 new subscriber profiles with unique IMSIs and IPs.
2. Confirm all 10 submissions return HTTP 202 (accepted), yielding 10 job IDs.
3. Poll each job to completion (waiting up to 5 minutes per job).
4. Confirm every job finishes with `status = "completed"` and `failed = 0`.

---

## Test 11.5 — 10 concurrent first-connection requests: all succeed, no duplicate IPs

**Goal:** When multiple devices connect simultaneously for the first time, each gets a unique IP — the system's IP allocation must be concurrency-safe.

1. Create a fresh small pool (subnet `100.67.0.0/28`, 14 usable IPs) and a range configuration for 10 new test IMSIs.
2. Fire 10 first-connection requests simultaneously (one per IMSI, all different).
3. Confirm no thread-level exceptions occurred.
4. Collect all allocated IPs.
5. Confirm all IPs in the list are unique (no two connections got the same IP).

---

## Test 11.6 — Pool statistics with 300,000 allocated IPs respond within 200 ms

**Goal:** Even with a very large number of allocated addresses, the pool stats endpoint must remain fast.

1. Send a request to retrieve statistics for the large seeded pool.
2. Confirm HTTP 200.
3. Confirm at least 1,000 IPs are shown as allocated (partial check that seeding was effective).
4. Confirm the response time is ≤ 200 ms.

---

## Test 11.7 — Individual profile retrieval: p99 ≤ 50 ms

**Goal:** Fetching a single profile by its `sim_id` must be fast even against a large database.

1. Find a valid `sim_id` from the seeded dataset.
2. Send 20 sequential GET-profile requests for that profile.
3. Record the response time for each.
4. Calculate p99 across the 20 samples.
5. Confirm p99 ≤ 50 ms.

---

## Post-conditions (Teardown)

None. The 300,000-profile seed dataset and pool are intentionally preserved between test runs to avoid the 3-minute re-seeding cost. Manual cleanup instructions are noted in the test code if needed.
