# Test Suite 01c — Routing Domain CRUD, CIDR Suggestion, and Allowed Prefix Enforcement

## What this test suite validates
This suite covers the full lifecycle of routing domains as standalone objects managed through their own API endpoints. It validates creation, retrieval, renaming, deletion, and conflict rules. It also tests the `suggest-cidr` feature that recommends the next available IP block within a domain, and the `allowed_prefixes` enforcement that restricts which subnets may be added to a domain.

## Pre-conditions (Setup)
1. The subscriber-profile-api service is running and reachable.
2. Before the CRUD tests run, the system performs a cleanup pass to remove any routing domains named `test-rd-1c-alpha`, `test-rd-1c-beta`, or `test-rd-1c-alpha-renamed` that may have been left behind by a previous interrupted run.
3. No IP pools need to be pre-created — individual tests create and delete their own pools as needed.

---

## Test 1c.1 — Create a routing domain

**Goal:** Confirm that submitting a valid name creates a routing domain and returns a UUID identifier.

1. Send a request to create a routing domain named `test-rd-1c-alpha` with description `test domain alpha`.
2. Verify the response is HTTP 201 (created).
3. Verify the response body contains an `id` field that is a valid UUID (36 characters).
4. Verify the `name` field matches the submitted name.
5. (Teardown) Delete the domain.

---

## Test 1c.2 — Reject a duplicate routing domain name

**Goal:** Confirm that creating two routing domains with the same name is blocked.

1. Create a routing domain named `test-rd-1c-alpha`.
2. Attempt to create a second routing domain with the same name.
3. Verify the second request returns HTTP 409 (conflict).
4. Verify the response body contains `error: domain_name_conflict`.
5. (Teardown) Delete the first domain.

---

## Test 1c.3 — Retrieve a routing domain by ID

**Goal:** Confirm that a routing domain can be fetched by ID and all its fields are returned correctly.

1. Create a routing domain named `test-rd-1c-alpha` with description `desc` and allowed prefix `10.99.0.0/16`.
2. Send a GET request using the domain's ID.
3. Verify the response is HTTP 200 (success).
4. Verify `id`, `name`, and `description` match what was submitted.
5. Verify `allowed_prefixes` contains `10.99.0.0/16`.
6. Verify a `pool_count` field is present in the response.
7. (Teardown) Delete the domain.

---

## Test 1c.4 — Retrieve a non-existent routing domain

**Goal:** Confirm that looking up a routing domain with a random UUID that does not exist returns a clear not-found error.

1. Send a GET request for routing domain ID `00000000-0000-0000-0000-000000000000`.
2. Verify the response is HTTP 404 (not found).
3. Verify the response body contains `error: not_found`.

---

## Test 1c.5 — Rename a routing domain

**Goal:** Confirm that a routing domain's name can be changed and the change is immediately visible.

1. Create a routing domain named `test-rd-1c-alpha`.
2. Send a PATCH request to rename it to `test-rd-1c-alpha-renamed`.
3. Verify the response is HTTP 200 (success).
4. Send a GET request and verify the `name` field now reads the new name.
5. (Teardown) Delete the domain.

---

## Test 1c.6 — Update the allowed prefixes on a routing domain

**Goal:** Confirm that the `allowed_prefixes` list on a routing domain can be updated and the change is persisted.

1. Create a routing domain named `test-rd-1c-alpha` with no initial allowed prefixes.
2. Send a PATCH request to set `allowed_prefixes` to `["10.99.0.0/16", "172.16.0.0/12"]`.
3. Verify the response is HTTP 200 (success).
4. Send a GET request and verify both `10.99.0.0/16` and `172.16.0.0/12` appear in `allowed_prefixes`.
5. (Teardown) Delete the domain.

---

## Test 1c.7 — Delete an empty routing domain

**Goal:** Confirm that a routing domain with no associated pools can be deleted.

1. Create a routing domain named `test-rd-1c-alpha`.
2. Send a DELETE request for the domain.
3. Verify the response is HTTP 204 (deleted successfully).
4. Send a GET request for the same domain and verify it now returns HTTP 404 (not found).

---

## Test 1c.8 — Reject deletion of a routing domain that has pools

**Goal:** Confirm that a routing domain cannot be deleted while it still contains IP pools.

1. Create a routing domain named `test-rd-1c-alpha`.
2. Create an IP pool (`10.200.0.0/24`) assigned to that domain.
3. Attempt to delete the routing domain.
4. Verify the response is HTTP 409 (conflict).
5. Verify the response body contains `error: domain_in_use` and a `pool_count` of at least 1.
6. (Teardown) Delete the pool first, then the domain.

---

## Test 1c.9 — suggest-cidr fails when no allowed prefixes are set

**Goal:** Confirm that requesting a CIDR suggestion on a domain with no allowed prefixes returns a clear error.

1. Create a routing domain named `test-rd-1c-alpha` with no `allowed_prefixes`.
2. Send a request to `suggest-cidr` with `size=10`.
3. Verify the response is HTTP 422 (unprocessable — precondition not met).
4. Verify the response body contains `error: no_allowed_prefixes`.
5. (Teardown) Delete the domain.

---

## Test 1c.10 — suggest-cidr returns a valid free IP block

**Goal:** Confirm that the CIDR suggestion endpoint returns an appropriately sized, valid IP block within the domain's allowed prefixes.

1. Create a routing domain with allowed prefix `10.99.0.0/16`.
2. Send a request to `suggest-cidr` with `size=50` (requesting enough space for 50 hosts).
3. Verify the response is HTTP 200 (success).
4. Verify the response contains `suggested_cidr`, `prefix_len`, and `usable_hosts` fields.
5. Verify `usable_hosts` is at least 50.
6. Verify `routing_domain_id` matches the domain's ID.
7. Verify the suggested CIDR starts with `10.99.` (falls within the allowed prefix).
8. (Teardown) Delete the domain.

---

## Test 1c.11 — suggest-cidr skips blocks already used by existing pools

**Goal:** Confirm that the CIDR suggestion engine does not suggest an IP range that overlaps with a pool that already exists in the domain.

1. Create a routing domain with allowed prefix `10.99.0.0/16`.
2. Create a pool using subnet `10.99.0.0/24` (occupying the first /24 block of the prefix).
3. Send a request to `suggest-cidr` with `size=50`.
4. Verify the response is HTTP 200 (success).
5. Verify the suggested CIDR is not `10.99.0.0/24` (the occupied block).
6. Verify the suggested CIDR still begins with `10.99.` (stays within the allowed prefix).
7. (Teardown) Delete the pool, then the domain.

---

## Test 1c.12 — suggest-cidr for an unknown domain returns not found

**Goal:** Confirm that requesting a CIDR suggestion for a routing domain that does not exist returns a clear not-found error.

1. Send a `suggest-cidr` request for domain ID `00000000-0000-0000-0000-000000000000` with `size=10`.
2. Verify the response is HTTP 404 (not found).
3. Verify the response body contains `error: not_found`.

---

## Test 1c.13 — Reject a pool whose subnet is outside the domain's allowed prefixes

**Goal:** Confirm that the system blocks creation of a pool if its subnet falls outside the routing domain's declared allowed IP ranges.

1. Create a routing domain with allowed prefix `10.99.0.0/16`.
2. Attempt to create a pool with subnet `192.168.55.0/24` (which is outside `10.99.0.0/16`) assigned to that domain.
3. Verify the response is HTTP 409 (conflict).
4. Verify the response body contains `error: subnet_outside_allowed_prefixes` and an `allowed_prefixes` field.
5. (Teardown) Delete the domain.

---

## Test 1c.14 — Accept a pool whose subnet is inside the domain's allowed prefixes

**Goal:** Confirm that creating a pool with a subnet that falls within the routing domain's allowed prefix succeeds.

1. Create a routing domain with allowed prefix `10.99.0.0/16`.
2. Create a pool with subnet `10.99.0.0/24` (which is inside `10.99.0.0/16`) assigned to that domain.
3. Verify the response is HTTP 201 (created).
4. (Teardown) Delete the pool, then the domain.

---

## Test 1c.15 — Create a pool referencing the routing domain by its UUID

**Goal:** Confirm that a pool can be linked to a routing domain using the domain's UUID directly (rather than its name), and that both the UUID and name are visible on the resulting pool.

1. Create a routing domain named `test-rd-1c-alpha`.
2. Create a pool with subnet `10.200.1.0/24` using `routing_domain_id` (the domain UUID) instead of the domain name.
3. Verify the pool creation returns HTTP 201 (created).
4. Retrieve the pool and verify `routing_domain_id` matches the domain UUID.
5. Verify `routing_domain` (the name) matches `test-rd-1c-alpha`.
6. (Teardown) Delete the pool, then the domain.

---

## Test 1c.16 — Reject a routing domain with an empty name

**Goal:** Confirm that attempting to create a routing domain with a blank name is rejected with a validation error.

1. Send a request to create a routing domain with `name` set to an empty string.
2. Verify the response is HTTP 400 (bad request).
3. Verify the response body contains `error: validation_failed`.

---

## Test 1c.17 — Reject a routing domain with an invalid CIDR in allowed prefixes

**Goal:** Confirm that submitting a malformed CIDR string in the `allowed_prefixes` list is rejected.

1. Send a request to create a routing domain with `allowed_prefixes` containing the string `not-a-cidr`.
2. Verify the response is HTTP 400 (bad request).
3. Verify the response body contains `error: validation_failed`.

---

## Post-conditions (Teardown)
1. Each test cleans up the routing domains and pools it created inside `finally` blocks, so no persistent data remains after the suite completes.
2. The class-level setup performs a pre-run cleanup to remove stale domains from previous interrupted runs.
