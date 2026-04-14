# Test Suite 03 — ICCID-Mode Subscriber Profile (Card-Level IP Resolution)

## What this test suite validates
This suite validates subscriber profiles where IP resolution is based on the physical SIM card's ICCID number. In ICCID mode, all IMSI numbers associated with a card share a single IP address, and the APN is completely ignored during lookup — the same IP is always returned regardless of which APN the subscriber connects through. The suite also covers SIM suspension, reactivation, and deletion.

## Pre-conditions (Setup)
1. The subscriber-profile-api and the aaa-lookup-service are both running and reachable.
2. One IP pool is created before the tests begin:
   - Subnet `100.65.140.0/24`, named `pool-a-03`, for account `TestAccount`.
   - If the pool already exists from a previous run, it is reused.
3. Tests 3.1 through 3.9 share a single subscriber profile created in test 3.1 and must run in order.

---

## Test 3.1 — Create an ICCID-mode profile with two IMSIs

**Goal:** Confirm that a subscriber profile using ICCID-based IP resolution can be created, linking two IMSI numbers to one card and one static IP.

1. Send a request to create a profile in `iccid` mode for ICCID `8944501030000000001`, account `TestAccount`, with two IMSIs (`278773030000001` and `278773030000002`) and static IP `100.65.140.5` drawn from the pool.
2. Verify the response is HTTP 201 (created).
3. Verify the response body contains a `sim_id` field.
4. Save the `sim_id` for use in subsequent tests.

---

## Test 3.2 — Retrieve the profile and verify its details

**Goal:** Confirm that the profile record is stored correctly and can be retrieved.

1. Send a GET request for the profile using the `sim_id` saved in test 3.1.
2. Verify the response is HTTP 200 (success).
3. Verify `iccid` equals `8944501030000000001`.
4. Verify `ip_resolution` equals `iccid`.
5. Verify the `iccid_ips` list contains an entry with `static_ip` equal to `100.65.140.5`.

---

## Test 3.3 — Lookup using the first IMSI

**Goal:** Confirm that a lookup for IMSI-1 returns the card's static IP.

1. Send a lookup request with IMSI `278773030000001` and APN `internet.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` in the response equals `100.65.140.5`.

---

## Test 3.4 — Lookup using the second IMSI with a different APN

**Goal:** Confirm that a lookup for IMSI-2 using a different APN still returns the same card IP (demonstrating that APN is ignored in ICCID mode).

1. Send a lookup request with IMSI `278773030000002` and APN `ims.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` in the response equals `100.65.140.5` (the same card IP, regardless of APN).

---

## Test 3.5 — Lookup with a completely unrecognised APN

**Goal:** Confirm that even a garbage APN value does not affect the resolved IP in ICCID mode.

1. Send a lookup request with IMSI `278773030000001` and APN `any.garbage.apn`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` in the response equals `100.65.140.5`.

---

## Test 3.6 — Suspend the SIM

**Goal:** Confirm that a subscriber profile can be suspended through a PATCH request.

1. Send a PATCH request to set the profile's `status` to `suspended`.
2. Verify the response is HTTP 200 (success).

---

## Test 3.7 — Lookup while suspended returns access denied

**Goal:** Confirm that a lookup for a suspended SIM is blocked with an appropriate error.

1. Send a lookup request with IMSI `278773030000001` and APN `internet.operator.com`.
2. Verify the response is HTTP 403 (forbidden).
3. Verify the response body contains `error: suspended`.

---

## Test 3.8 — Reactivate the SIM and confirm lookup works again

**Goal:** Confirm that reactivating a suspended SIM restores normal lookup behaviour.

1. Send a PATCH request to set the profile's `status` back to `active`.
2. Verify the response is HTTP 200 (success).
3. Send a lookup request with IMSI `278773030000001` and APN `internet.operator.com`.
4. Verify the response is HTTP 200 (success).
5. Verify `static_ip` equals `100.65.140.5`.

---

## Test 3.9 — Delete the profile and verify its terminal state

**Goal:** Confirm that deleting a profile marks it as terminated while keeping the record readable.

1. Send a DELETE request for the profile.
2. Verify the response is HTTP 204 (deleted successfully).
3. Send a GET request for the same `sim_id`.
4. Verify the response is HTTP 200 (success — the record is still readable).
5. Verify the `status` field reads `terminated`.

---

## Test 3.10 — IMSI-2 with a second APN still returns the card IP

**Goal:** Complement test 3.4 by confirming APN-agnostic resolution works symmetrically for IMSI-2 using yet another APN value.

1. Send a lookup request with IMSI `278773030000002` and APN `internet.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `100.65.140.5` (the shared card IP — APN is ignored).

---

## Post-conditions (Teardown)
1. If the profile was not already deleted by test 3.9, it is deleted during teardown.
2. The IP pool created during setup is deleted.
