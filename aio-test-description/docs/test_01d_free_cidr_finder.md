# Test Suite 01d — Free CIDR Finder End-to-End Workflow

## What this test suite validates
This suite exercises the complete operator workflow for automatically allocating a free IP subnet within a routing domain: configure allowed IP ranges on a domain, ask the system to suggest a free CIDR block of the required size, then create a pool using that suggestion. It confirms suggestions are valid, non-overlapping, and correctly sized — and that a large blocking pool does not prevent the system from finding free space elsewhere in the address range.

## Pre-conditions (Setup)
1. The subscriber-profile-api service is running and reachable.
2. Each test creates its own routing domain and cleans it up in a `finally` block, so no persistent state is required.
3. The IP space `10.88.0.0/16` is reserved for this test module and should not be used by other tests.

---

## Test 1d.1 — Full round-trip: suggest a CIDR and create a pool from it

**Goal:** Confirm the happy-path workflow from end to end — get a suggestion, create a pool from it, and verify the pool is successfully created.

1. Create a routing domain with allowed prefix `10.88.0.0/16`.
2. Send a `suggest-cidr` request with `size=50` (requesting space for at least 50 hosts).
3. Verify the response is HTTP 200 (success).
4. Verify the response contains `suggested_cidr`, `prefix_len`, and `usable_hosts` fields.
5. Verify `usable_hosts` is at least 50.
6. Verify `routing_domain_id` in the response matches the domain's ID.
7. Verify the suggested CIDR falls within the allowed prefix `10.88.0.0/16`.
8. Create a pool using the suggested CIDR in the same routing domain.
9. Verify the pool is created successfully (HTTP 201).
10. (Teardown) Delete the pool, then the domain.

---

## Test 1d.2 — Pool subnet matches the suggested CIDR

**Goal:** Confirm that after creating a pool from a suggestion, the pool record stores the exact subnet that was suggested.

1. Create a routing domain with allowed prefix `10.88.0.0/16`.
2. Send a `suggest-cidr` request with `size=50` and record the suggested CIDR.
3. Create a pool using the suggested CIDR.
4. Retrieve the pool and verify its `subnet` field matches the suggested CIDR (accounting for any normalisation differences in notation).
5. Verify the pool's `routing_domain_id` matches the domain's ID.
6. Verify the pool's `routing_domain` name matches the domain name.
7. (Teardown) Delete the pool, then the domain.

---

## Test 1d.3 — Two sequential suggestions produce non-overlapping CIDRs

**Goal:** Confirm that after the first suggestion is used to create a pool, the second suggestion does not overlap with it.

1. Create a routing domain with allowed prefix `10.88.0.0/16`.
2. Send a first `suggest-cidr` request with `size=50` and record the result as CIDR-1.
3. Create a pool using CIDR-1.
4. Send a second `suggest-cidr` request with `size=50` and record the result as CIDR-2.
5. Verify CIDR-2 is different from CIDR-1.
6. Verify CIDR-1 and CIDR-2 do not overlap.
7. Create a pool using CIDR-2 and verify it succeeds (HTTP 201 — no overlap conflict).
8. (Teardown) Delete both pools, then the domain.

---

## Test 1d.4 — Adding allowed prefixes unlocks suggest-cidr

**Goal:** Confirm that a domain with no allowed prefixes blocks the suggestion endpoint, and that adding a prefix via PATCH immediately makes suggestions available.

1. Create a routing domain with no `allowed_prefixes`.
2. Send a `suggest-cidr` request with `size=10`.
3. Verify the response is HTTP 422 (unprocessable) with `error: no_allowed_prefixes`.
4. Send a PATCH request to add `10.88.0.0/16` to the domain's `allowed_prefixes`.
5. Verify the PATCH response is HTTP 200 (success).
6. Send the `suggest-cidr` request again with `size=10`.
7. Verify the response is now HTTP 200 (success) with a valid suggestion.
8. Create a pool using the suggested CIDR and verify it is created successfully (HTTP 201).
9. (Teardown) Delete the pool, then the domain.

---

## Test 1d.5 — Requested size maps to the correct prefix length

**Goal:** Confirm that the suggestion engine selects the smallest CIDR block that still fits the requested number of hosts.

1. For each of the following size/prefix combinations, run the same sub-scenario:
   - Size 6 → expect prefix length /29 (6 usable hosts)
   - Size 14 → expect prefix length /28 (14 usable hosts)
   - Size 254 → expect prefix length /24 (254 usable hosts)
2. For each case: create a fresh routing domain with allowed prefix `10.88.0.0/16`.
3. Send a `suggest-cidr` request with the given `size`.
4. Verify `prefix_len` matches the expected value.
5. Verify `usable_hosts` equals the standard number of usable addresses for that prefix length (total addresses minus network and broadcast).
6. Verify `usable_hosts` is at least as large as the requested `size`.
7. (Teardown) Delete each domain after its sub-scenario completes.

---

## Test 1d.6 — Create a pool referencing the routing domain by UUID

**Goal:** Confirm that the pool creation step of the workflow works when using the routing domain's UUID directly, rather than its name.

1. Create a routing domain with allowed prefix `10.88.0.0/16`.
2. Send a `suggest-cidr` request with `size=50` and record the suggested CIDR.
3. Create a pool using `routing_domain_id` (the UUID) and the suggested CIDR.
4. Verify the pool is created successfully (HTTP 201).
5. Retrieve the pool and verify `routing_domain_id` matches the domain UUID.
6. Verify `routing_domain` (the name) matches the domain name.
7. (Teardown) Delete the pool, then the domain.

---

## Test 1d.7 — Large blocking pool at the start of a prefix does not prevent suggestions

**Goal:** Regression test confirming that when the entire first half of an allowed prefix is occupied by a single large pool, the suggestion engine still finds free space in the second half rather than failing.

1. Create a routing domain with allowed prefix `10.88.0.0/16`.
2. Create a pool covering the entire first half (`10.88.0.0/17`) — this occupies all 128 /24 blocks and all 256 /25 blocks in that half.
3. Send a `suggest-cidr` request with `size=50`.
4. Verify the response is HTTP 200 (success). (An older algorithm would exhaust its candidate limit inside the occupied first half and falsely return not-found.)
5. Verify the suggested CIDR does not overlap `10.88.0.0/17` (the blocking pool).
6. Verify the suggested CIDR still falls within the allowed prefix `10.88.0.0/16`.
7. Verify the suggested CIDR falls in the free second half (`10.88.128.0/17`).
8. (Teardown) Delete the blocking pool, then the domain.

---

## Post-conditions (Teardown)
1. Each test cleans up its own pools and routing domains inside `finally` blocks.
2. No persistent state is left behind after the suite completes.
