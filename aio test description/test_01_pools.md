# Test Suite 01 — IP Pool CRUD, Stats, and Routing Domain Overlap Enforcement

## What this test suite validates
This suite confirms that IP address pools can be created, read, renamed, listed, and deleted through the provisioning API. It also verifies that the system correctly prevents conflicting IP ranges from being assigned to the same routing domain, and that the routing domain field behaves as read-only after pool creation.

## Pre-conditions (Setup)
1. The subscriber-profile-api service is running and reachable.
2. No pre-created pools or routing domains are required — each test creates its own data.
3. Tests 1.1 through 1.6 share a single pool created in test 1.1; they must run in order.

---

## Test 1.1 — Create a new IP pool

**Goal:** Confirm that submitting a valid subnet creates a pool and returns a unique pool identifier.

1. Send a request to create a pool with subnet `100.65.120.0/24`, named `test-pool-01`, for account `Melita`.
2. Verify the response indicates success (HTTP 201 Created).
3. Verify the response body contains a `pool_id` field that is a valid UUID (36-character string).
4. Save the `pool_id` for use in subsequent tests.

---

## Test 1.2 — Retrieve the pool by ID

**Goal:** Confirm that the newly created pool can be retrieved and its IP range details are correct.

1. Send a request to fetch the pool using the `pool_id` saved in test 1.1.
2. Verify the response is HTTP 200 (success).
3. Verify the returned `subnet` matches `100.65.120.0/24`.
4. Verify both `start_ip` and `end_ip` begin with `100.65.120.`, confirming they fall within the correct subnet.

---

## Test 1.3 — Check pool stats immediately after creation

**Goal:** Confirm that a brand-new pool shows zero allocated addresses and 253 available addresses.

1. Send a request for the pool's usage statistics.
2. Verify `allocated` equals 0.
3. Verify `available` equals 253 (the number of usable host addresses in a /24 subnet, excluding network, broadcast, and gateway).

---

## Test 1.4 — Rename the pool

**Goal:** Confirm that a pool's name can be updated and the change is immediately reflected.

1. Send a PATCH request to rename the pool to `renamed-pool`.
2. Verify the response is HTTP 200 (success).
3. Send a GET request to retrieve the pool.
4. Verify the pool's `name` field now reads `renamed-pool`.

---

## Test 1.5 — List pools filtered by account name

**Goal:** Confirm that filtering pools by account name returns the correct pool.

1. Send a request to list all pools for account `Melita`.
2. Verify the response is HTTP 200 (success).
3. Verify the pool created in test 1.1 appears in the returned list.

---

## Test 1.6 — Delete a pool with no active IP allocations

**Goal:** Confirm that an empty pool can be deleted successfully.

1. Send a DELETE request for the pool created in test 1.1.
2. Verify the response is HTTP 204 (no content — deleted successfully).

---

## Test 1.7 — Attempt to delete a pool that has an IP in use

**Goal:** Confirm that the system blocks deletion of a pool that still has active subscriber IP allocations.

1. Create a new pool with subnet `100.65.121.0/24`, named `pool-with-alloc`.
2. Create a subscriber profile that assigns static IP `100.65.121.5` from this pool.
3. Send a DELETE request to remove the pool.
4. Verify the response is HTTP 409 (conflict).
5. Verify the response body contains `error: pool_in_use`.
6. (Teardown) Delete the subscriber profile, then delete the pool.

---

## Test 1.8 — Attempt to create a pool with an invalid subnet

**Goal:** Confirm that submitting a non-CIDR value as the subnet is rejected with a clear validation error.

1. Send a request to create a pool with the subnet set to the string `not-a-cidr`.
2. Verify the response is HTTP 400 (bad request).
3. Verify the response body contains `error: validation_failed`.

---

## Test 1.9 — Pool creation includes routing domain in response

**Goal:** Confirm that when a pool is created with a routing domain name, the response and subsequent GET both include the routing domain name and a routing domain UUID.

1. Create a pool with subnet `100.65.201.0/24` and routing domain `rd-test-domain-alpha`.
2. Send a GET request to retrieve the pool.
3. Verify the response is HTTP 200 (success).
4. Verify `routing_domain` equals `rd-test-domain-alpha`.
5. Verify `routing_domain_id` is present and is a valid UUID.
6. (Teardown) Delete the pool.

---

## Test 1.10 — Reject identical subnet in the same routing domain

**Goal:** Confirm that two pools with the exact same subnet cannot coexist in the same routing domain.

1. Create a pool with subnet `100.65.200.0/24` in routing domain `rd-test-domain-alpha`.
2. Attempt to create a second pool with the same subnet in the same routing domain.
3. Verify the second request returns HTTP 409 (conflict).
4. Verify the response body contains `error: pool_overlap` and identifies the conflicting pool's ID.
5. (Teardown) Delete the first pool.

---

## Test 1.11 — Reject overlapping subnet in the same routing domain

**Goal:** Confirm that a subnet which is a sub-range of an existing pool in the same routing domain is also blocked.

1. Create a pool with subnet `100.65.200.0/24` in routing domain `rd-test-domain-alpha`.
2. Attempt to create a second pool with subnet `100.65.200.0/25` (the lower half of the /24) in the same routing domain.
3. Verify the response is HTTP 409 (conflict) with `error: pool_overlap`.
4. Attempt to create a third pool with subnet `100.65.200.128/25` (the upper half) in the same routing domain.
5. Verify this also returns HTTP 409 (conflict) with `error: pool_overlap`.
6. (Teardown) Delete the first pool.

---

## Test 1.12 — Allow the same subnet in different routing domains

**Goal:** Confirm that the same IP subnet may be used in two separate routing domains without conflict.

1. Create pool A with subnet `100.65.202.0/24` in routing domain `rd-test-domain-alpha`.
2. Create pool B with subnet `100.65.202.0/24` in routing domain `rd-test-domain-beta`.
3. Verify both pools are created successfully and have different pool IDs.
4. Retrieve each pool and confirm the `routing_domain` field matches the expected domain.
5. (Teardown) Delete both pools.

---

## Test 1.13 — List pools filtered by routing domain

**Goal:** Confirm that the routing domain filter on the pool list endpoint correctly separates pools by domain.

1. Create pool A in routing domain `rd-test-domain-alpha`.
2. Create pool B in routing domain `rd-test-domain-beta`.
3. Request the pool list filtered to `rd-test-domain-alpha`.
4. Verify pool A appears and pool B does not.
5. Request the pool list filtered to `rd-test-domain-beta`.
6. Verify pool B appears and pool A does not.
7. (Teardown) Delete both pools.

---

## Test 1.14 — Routing domains endpoint returns known domains

**Goal:** Confirm that the routing domains list endpoint includes all domains that have been created through pool provisioning.

1. Create a pool in routing domain `rd-test-domain-alpha`.
2. Create a pool in routing domain `rd-test-domain-beta`.
3. Send a request to list all routing domains.
4. Verify the response is HTTP 200 (success).
5. Verify both `rd-test-domain-alpha` and `rd-test-domain-beta` appear in the returned list.
6. (Teardown) Delete both pools.

---

## Test 1.15 — Routing domain cannot be changed after creation

**Goal:** Confirm that attempting to change a pool's routing domain via a PATCH request is silently ignored — the domain is immutable.

1. Create a pool in routing domain `rd-test-domain-alpha`.
2. Send a PATCH request that includes a `routing_domain` field set to `rd-test-domain-beta`, along with a legitimate name change to `rd-immutable-renamed`.
3. Verify the response is HTTP 200 (success).
4. Retrieve the pool and verify the `name` has changed to `rd-immutable-renamed`.
5. Verify `routing_domain` still reads `rd-test-domain-alpha` (the domain change was ignored).
6. (Teardown) Delete the pool.

---

## Test 1.16 — Default routing domain assigned when none is specified

**Goal:** Confirm that a pool created without specifying a routing domain is automatically placed in the `default` routing domain.

1. Create a pool without specifying a routing domain.
2. Retrieve the pool.
3. Verify `routing_domain` equals `default`.
4. Verify `routing_domain_id` is present and is a valid UUID.
5. (Teardown) Delete the pool.

---

## Post-conditions (Teardown)
1. Each test in the routing domain section cleans up its own pools inside a `finally` block, so no persistent state is left behind.
2. Test 1.6 explicitly deletes the shared pool created in test 1.1.
3. Test 1.7 deletes the subscriber profile first, then the pool, regardless of test outcome.
