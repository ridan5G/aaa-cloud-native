# Test Suite 07c — IP Release and IMSI Deletion

## What this test suite validates

This suite verifies that allocated IP addresses can be returned to the pool in two different ways: by calling the "release-ips" operation on a subscriber profile, and by deleting an individual IMSI from a profile. It confirms that released IPs are immediately available for reuse, that the subscriber profile and IMSI binding are preserved after a release, and that a subsequent first-connection correctly allocates a fresh IP rather than returning null — which was a real regression this suite guards against.

## Pre-conditions (Setup)

1. Any stale subscriber profiles left from a previous interrupted test run are cleaned up (profiles whose IMSI prefix matches the test module's range).
2. A small IP pool is created: subnet `100.65.195.0/29`, which provides exactly 6 usable IP addresses (.1 through .6).
3. A range configuration is registered mapping the test IMSI range to this pool, using `imsi` resolution mode (one IP per IMSI).

---

## Test 7c.1 — Setup verified: pool is healthy before release tests begin

**Goal:** Confirm the pool has enough available IPs before any release tests run, so that failures in later tests cannot be blamed on a dirty initial state.

1. Send a request to retrieve pool statistics for the test pool.
2. Confirm the response is HTTP 200 (success).
3. Confirm the pool has at least 5 available IPs (allowing for at most 1 stale allocation from a previous run).
4. Confirm the pool has at most 1 already-allocated IP.

---

## Test 7c.2 — Release-ips returns the IP to the pool; profile and IMSI binding remain

**Goal:** After a first-connection allocates an IP, calling release-ips returns that IP to the pool. The subscriber profile and IMSI record must still exist, but the IP association is cleared.

1. Send a first-connection request for test IMSI #1 — confirm HTTP 201 and record the allocated IP and `sim_id`.
2. Read pool statistics and confirm at least 1 IP is allocated.
3. Send a release-ips request for the profile.
4. Confirm the response is HTTP 200 with `released_count` = 1, and the released IP matches what was allocated in step 1.
5. Read pool statistics again and confirm the available count has increased by exactly 1.
6. Retrieve the subscriber profile — confirm it still exists.
7. Confirm the IMSI is still listed on the profile.
8. Confirm the IMSI's `apn_ips` list is now empty (no IP assigned).

---

## Test 7c.3 — Calling release-ips on a profile with no IPs is safe (idempotency)

**Goal:** Calling release-ips when no IP is currently allocated must succeed silently with a count of zero — it must not raise an error.

1. Look up the `sim_id` for test IMSI #1 (which was released in test 7c.2).
2. Send a release-ips request for that profile.
3. Confirm the response is HTTP 200 with `released_count` = 0 and an empty `ips_released` list.

---

## Test 7c.4 — First-connection after release allocates a fresh IP (not null)

**Goal:** This is the core regression guard: after release-ips, the next first-connection must actually allocate a new IP and return it — not return null.

1. Send a first-connection request for the same IMSI #1 that was released.
2. Confirm the response is HTTP 200 or 201 (success).
3. Confirm the `static_ip` in the response is not null.
4. Read pool statistics — confirm the allocated count has gone back up by at least 1.

---

## Test 7c.4b — Full release-then-reconnect cycle on a fresh IMSI (end-to-end regression)

**Goal:** Runs the complete release → reconnect cycle on a second IMSI to prove the fix works consistently, not just for the IMSI used in tests 7c.2–7c.4.

1. Send a first-connection for test IMSI #2 — confirm HTTP 201 and a non-null IP.
2. Record pool statistics (allocated count before release).
3. Send release-ips for that profile — confirm HTTP 200 with `released_count` = 1.
4. Read pool statistics and confirm the available count increased by 1 (IP returned to pool).
5. Send first-connection for the same IMSI #2 again.
6. Confirm HTTP 200 or 201 and a non-null `static_ip` — this is the key regression assertion.
7. Read pool statistics and confirm the allocated count went back up.

---

## Test 7c.5 — Release-ips on an unknown profile returns HTTP 404 (not found)

**Goal:** Calling release-ips with a non-existent profile ID must return HTTP 404, not crash.

1. Send a release-ips request using a made-up UUID that does not correspond to any profile.
2. Confirm the response is HTTP 404 (not found).

---

## Test 7c.6 — Deleting an IMSI from a profile returns its IP to the pool

**Goal:** When an individual IMSI is removed from a profile, the IP address it held is automatically returned to the pool.

1. Send a first-connection for test IMSI #10 — confirm HTTP 201.
2. Record pool statistics (available count before deletion).
3. Send a delete-IMSI request to remove IMSI #10 from its profile.
4. Confirm the response is HTTP 204 (no content / success).
5. Read pool statistics again and confirm the available count increased by exactly 1.

---

## Test 7c.7 — A deleted IMSI can be re-added to a new profile without a conflict error

**Goal:** After deleting an IMSI from one profile, that IMSI must be free to be assigned to another profile — no uniqueness conflict should remain.

1. Send a first-connection for test IMSI #11 — confirm HTTP 201.
2. Delete IMSI #11 from that profile — confirm HTTP 204.
3. Create a new subscriber profile and include IMSI #11 in it.
4. Confirm the new profile is created with HTTP 201 (no conflict error).

---

## Post-conditions (Teardown)

1. The range configuration created during setup is deleted.
2. The IP pool created during setup is deleted.
3. Subscriber profiles are intentionally left in the database so they remain visible for post-run inspection.
