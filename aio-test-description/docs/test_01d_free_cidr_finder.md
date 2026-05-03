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

## Test 1d.5 — Requested size maps to the correct prefix length (full boundary table)

**Goal:** Confirm that the suggestion engine selects the smallest CIDR block that still fits the requested number of hosts, across the full boundary table from `/30` up to `/22`.

1. For each row in the boundary table, run the same sub-scenario. The table walks both the exact power-of-two boundary (e.g. size=6 → `/29` with usable=6) and one host past it (size=7 → `/28` with usable=14):

   | Size | Expected prefix | Usable hosts (`2^(32-p) - 2`) |
   |---:|:---:|---:|
   | 1, 2 | `/30` | 2 |
   | 3, 6 | `/29` | 6 |
   | 7, 14 | `/28` | 14 |
   | 15 | `/27` | 30 |
   | 31 | `/26` | 62 |
   | 63 | `/25` | 126 |
   | 127, 254 | `/24` | 254 |
   | 255, 510 | `/23` | 510 |
   | 511 | `/22` | 1022 |

2. For each case: create a fresh routing domain with allowed prefix `10.88.0.0/16`.
3. Send a `suggest-cidr` request with the given `size`.
4. Verify `prefix_len` matches the expected value.
5. Verify `usable_hosts == 2^(32-p) - 2` exactly.
6. Verify `usable_hosts >= size`.
7. Verify the returned `suggested_cidr` is `subnet_of` the allowed prefix `10.88.0.0/16`.
8. (Teardown) Delete each domain after its sub-scenario completes.

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

## Test 1d.8 — Smallest-fitting prefix invariant for in-between sizes

**Goal:** When the requested size doesn't exactly match a power-of-two boundary, the suggester must return the **smallest** prefix that still fits — never a larger prefix than necessary. The test also asserts that the next-smaller prefix (one bit longer) genuinely cannot accommodate the request, validating the case definition itself.

1. For each `(size, expected_smallest_p)` row:
   - `size=10` → expect `/28` (14 fits; 6 does not)
   - `size=20` → expect `/27` (30 fits; 14 does not)
   - `size=100` → expect `/25` (126 fits; 62 does not)
   - `size=200` → expect `/24` (254 fits; 126 does not)
2. For each case: create a fresh routing domain with allowed prefix `10.88.0.0/16`.
3. Send a `suggest-cidr` request with the given `size`.
4. Verify the response is HTTP 200.
5. Verify `prefix_len == expected_smallest_p`.
6. Verify `usable_hosts >= size`.
7. (Teardown) Delete the domain.

---

## Test 1d.9 — Two consecutive `size=14` suggestions return non-overlapping `/28`s

**Goal:** Confirm the suggestion engine accounts for an existing pool when a follow-up suggestion of the same size is requested in the same domain — each suggestion must avoid the previously-allocated block.

1. Create a routing domain with allowed prefix `10.88.0.0/16`.
2. Send `suggest-cidr` with `size=14`. Record the returned CIDR (call it `A`); verify `prefix_len == 28`.
3. Create a pool with subnet `A` assigned to the domain.
4. Send `suggest-cidr` with `size=14` again. Record the returned CIDR (call it `B`); verify `prefix_len == 28`.
5. Verify `B != A`.
6. Verify the two `/28` networks do not overlap (`net_a.overlaps(net_b)` is false).
7. Verify both suggestions are `subnet_of` `10.88.0.0/16`.
8. Create a second pool with subnet `B` to confirm it is genuinely free.
9. Verify both pool creations returned HTTP 201.
10. (Teardown) Delete both pools, then the domain.

---

## Post-conditions (Teardown)
1. Each test cleans up its own pools and routing domains inside `finally` blocks.
2. No persistent state is left behind after the suite completes.
