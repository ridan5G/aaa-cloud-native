# Test Suite 07 — First-Connection Dynamic IP Allocation

## What this test suite validates
This suite validates the automatic IP allocation path ("first-connection") where a subscriber device connects for the first time without a pre-provisioned profile. The lookup service detects the unknown IMSI, consults the matching range configuration, allocates a free IP from the pool on the fly, creates the profile automatically, and returns the IP — all within a single lookup call. The suite also tests pool exhaustion, suspended range configs, IMSI ranges that are not covered by any config, and concurrent allocations that must produce unique IPs with no duplicates.

## Pre-conditions (Setup)
1. The subscriber-profile-api and the aaa-lookup-service are both running and reachable.
2. Before creating any data, the setup cleans up any subscriber profiles from a previous interrupted run whose IMSIs start with `278773070` or `278773071`, so the pool and range config start from a known clean state.
3. One IP pool is created: subnet `100.65.190.0/29` (a /29 gives exactly 6 usable host addresses), named `pool-dyn-07`, for account `TestAccount`. If it already exists, it is reused.
4. One range config is created covering IMSIs `278773070000001` through `278773070000099`, linked to the pool, with `imsi` resolution mode.

---

## Test 7.1 — Verify setup is in a good state before allocation tests begin

**Goal:** Confirm that the pool and range config created during setup are reachable and active before proceeding.

1. Send a GET request for the pool.
2. Verify the response is HTTP 200 (success).
3. Send a GET request for the range config.
4. Verify the response is HTTP 200 (success) and the `status` field equals `active`.

---

## Test 7.2 — First-connection automatically creates a profile and allocates an IP

**Goal:** Confirm that a lookup for an IMSI with no existing profile triggers automatic profile creation and IP allocation, and that a second lookup for the same IMSI returns the same IP from the now-cached profile.

1. Confirm IMSI `278773070000001` has no existing profile (send a search request and verify the result is empty).
2. Send a lookup request with IMSI `278773070000001` and APN `internet.operator.com`.
3. Verify the response is HTTP 200 (success). (Internally, the lookup service called first-connection, which allocated a free IP and created the profile.)
4. Verify the response contains a `static_ip` field.
5. Send a second lookup for the same IMSI and APN.
6. Verify the response is HTTP 200 (success) and the `static_ip` is identical to the one returned in step 4 (the profile is now cached — no re-allocation).

---

## Test 7.3 — Repeated first-connection call is idempotent

**Goal:** Confirm that calling first-connection a second time for an already-provisioned IMSI does not allocate a new IP — it returns the existing one.

1. Send a lookup request for IMSI `278773070000001` and record the current IP.
2. Send a direct first-connection request (POST to `/profiles/first-connection`) for the same IMSI and APN.
3. Verify the response is HTTP 200 or 201 (success).
4. Verify the returned `static_ip` matches the IP from step 1 (no new allocation was made).

---

## Test 7.4 — Pool statistics reflect the allocation

**Goal:** Confirm that after one IP has been allocated, the pool stats show at least one allocated address and fewer available addresses.

1. Send a request for the pool's usage statistics.
2. Verify `allocated` is at least 1.
3. Verify `available` is less than 6 (the total usable capacity of the /29 pool).

---

## Test 7.5 — Auto-created profile has the correct structure

**Goal:** Confirm that the profile automatically created during first-connection has the expected field values.

1. Send a request to search profiles by IMSI `278773070000001`.
2. Verify the response is HTTP 200 (success) and at least one profile is returned.
3. Verify the profile's `ip_resolution` equals `imsi`.
4. Verify the profile's `iccid` is null (first-connection profiles have no ICCID).

---

## Test 7.6 — Lookup for an IMSI outside any range config returns not found

**Goal:** Confirm that a lookup for an IMSI that falls outside every configured range does not allocate an IP and returns a clear not-found error.

1. Send a lookup request with IMSI `278773079999999` (well outside the configured range `278773070000001–278773070000099`) and APN `internet.operator.com`.
2. Verify the response is HTTP 404 (not found).
3. Verify the response body contains an error such as `not_found`, `no_range_config`, or `apn_not_found`.

---

## Test 7.7 — Suspended range config blocks first-connection and lookup

**Goal:** Confirm that suspending a range config prevents any new IMSIs within that range from being auto-provisioned.

1. Send a PATCH request to set the range config's `status` to `suspended`.
2. Verify the response is HTTP 200 (success).
3. Send a direct first-connection request for IMSI `278773070000010` (a fresh IMSI within the range) and APN `internet.operator.com`.
4. Verify the response is a failure code (HTTP 404, 422, or 503 — the allocation was blocked).
5. Send a lookup request for the same IMSI and APN.
6. Verify the lookup also returns HTTP 404 (the lookup service propagates the failure because no profile was created).
7. Send a PATCH request to re-activate the range config (`status: active`) so subsequent tests can proceed.

---

## Test 7.8 — Exhausting the pool returns service unavailable

**Goal:** Confirm that once all usable IPs in the pool are allocated, the next allocation attempt returns a pool-exhausted error.

1. Send first-connection requests for additional IMSIs within the range, filling the remaining 5 IP slots in the /29 pool (IMSI `278773070000001` already used one slot in test 7.2).
2. After the pool is full, send one more first-connection request for a new IMSI.
3. Verify the response is HTTP 503 (service unavailable).
4. Verify the response body contains `error: pool_exhausted` or `error: no_available_ip`.

---

## Test 7.9 — Ten concurrent first-connection calls produce unique IPs

**Goal:** Confirm that simultaneous allocation requests for ten different IMSIs each receive a distinct IP — no two subscribers share the same address.

1. Create a fresh pool with subnet `100.65.191.0/28` (a /28 gives 14 usable host addresses), named `pool-dyn-07-conc`.
2. Create a fresh range config covering IMSIs `278773071000001` through `278773071000099`, linked to the new pool.
3. Launch 10 simultaneous first-connection requests, one for each of IMSIs `278773071000001` through `278773071000010`.
4. Wait for all 10 requests to complete.
5. Verify no thread exceptions occurred.
6. Collect all successfully allocated IPs from the responses.
7. Verify that all allocated IPs are unique — no duplicates in the list.
8. (Teardown) Delete the secondary range config, then the secondary pool.

---

## Post-conditions (Teardown)
1. The range config created during setup is deleted.
2. The primary pool is deleted.
3. Subscriber profiles created during the tests are intentionally left in place after the run so they can be inspected via the profiles export endpoint. They will be cleaned up at the start of the next test run by the setup step.
