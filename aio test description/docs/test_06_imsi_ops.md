# Test Suite 06 — IMSI-Level Operations: Add, Remove, and Conflict Detection

## What this test suite validates
This suite validates operations that modify the individual IMSI entries within an existing subscriber profile, independent of the profile as a whole. It covers listing IMSIs, adding a new IMSI to a profile, confirming the new IMSI resolves correctly via lookup, retrieving the new IMSI's details, removing an IMSI, and detecting conflicts when an IMSI already belongs to another profile. It also documents the system's behaviour when the last IMSI on a profile is deleted.

## Pre-conditions (Setup)
1. The subscriber-profile-api and the aaa-lookup-service are both running and reachable.
2. One IP pool is created: subnet `100.65.170.0/24`, named `pool-ops-06`, for account `TestAccount`. If it already exists, it is reused.
3. Two subscriber profiles are created before the tests begin:
   - **Primary profile** (`sim_id`): IMSI mode, two IMSIs:
     - IMSI `278773060000001` → IP `100.65.170.1`
     - IMSI `278773060000002` → IP `100.65.170.2`
   - **Secondary profile** (`sim_id2`): IMSI mode, one IMSI:
     - IMSI `278773060000004` → IP `100.65.170.20`
     - This profile is used exclusively to set up a conflict scenario in test 6.7.
4. Tests 6.1 through 6.8 depend on the state built up by the setup and must run in order.

---

## Test 6.1 — List IMSIs on the primary profile

**Goal:** Confirm that the IMSI list endpoint returns the correct IMSIs for a given profile.

1. Send a GET request to list all IMSIs on the primary profile.
2. Verify the response is HTTP 200 (success).
3. Verify IMSI `278773060000001` appears in the list.
4. Verify IMSI `278773060000002` appears in the list.

---

## Test 6.2 — Add a new IMSI to the primary profile

**Goal:** Confirm that an additional IMSI can be added to an existing profile via the IMSI-level POST endpoint.

1. Send a POST request to add IMSI `278773060000003` to the primary profile, with static IP `100.65.170.10` from the pool.
2. Verify the response is HTTP 201 (created).

---

## Test 6.3 — Lookup for the newly added IMSI resolves correctly

**Goal:** Confirm that the newly added IMSI is immediately active and returns the expected IP during lookup.

1. Send a lookup request with IMSI `278773060000003` and APN `internet.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `100.65.170.10`.

---

## Test 6.4 — Retrieve the detail of the newly added IMSI

**Goal:** Confirm that the new IMSI's record can be fetched individually and shows the correct IP assignment.

1. Send a GET request to the IMSI-level detail endpoint for IMSI `278773060000003` on the primary profile.
2. Verify the response is HTTP 200 (success).
3. Verify the returned `imsi` field equals `278773060000003`.
4. Verify the `apn_ips` list contains an entry with `static_ip` equal to `100.65.170.10`.

---

## Test 6.5 — Remove the newly added IMSI from the profile

**Goal:** Confirm that an individual IMSI can be removed from a profile.

1. Send a DELETE request to the IMSI-level endpoint for IMSI `278773060000003` on the primary profile.
2. Verify the response is HTTP 204 (deleted successfully).

---

## Test 6.6 — Lookup for the deleted IMSI returns not found

**Goal:** Confirm that after removal, the deleted IMSI no longer resolves during lookup.

1. Send a lookup request with IMSI `278773060000003` and APN `internet.operator.com`.
2. Verify the response is HTTP 404 (not found).

---

## Test 6.7 — Adding an IMSI already owned by another profile returns a conflict

**Goal:** Confirm that the system prevents the same IMSI from being assigned to two different subscriber profiles simultaneously.

1. Attempt to add IMSI `278773060000004` to the primary profile. This IMSI already belongs to the secondary profile created during setup.
2. Send a POST request with IMSI `278773060000004` and a new IP.
3. Verify the response is HTTP 409 (conflict).
4. Verify the response body contains an error indicating an IMSI conflict (`imsi_conflict` or `conflict`).

---

## Test 6.8 — Attempt to delete the last IMSI on a profile

**Goal:** Document the system's behaviour when the final IMSI on a profile is deleted. The test accepts either of two valid outcomes.

1. The secondary profile (`sim_id2`) currently has only one IMSI: `278773060000004`.
2. Send a DELETE request to remove this last IMSI.
3. Verify the response is either:
   - HTTP 204 (success — the system allows a profile to become IMSI-less), or
   - HTTP 400 (bad request — the system enforces a minimum of one IMSI per profile).
4. Either outcome is considered acceptable and documents the API's design choice. A 400 response is the recommended safeguard.

---

## Post-conditions (Teardown)
1. The secondary profile (`sim_id2`) is deleted.
2. The primary profile (`sim_id`) is deleted.
3. The IP pool is deleted.
