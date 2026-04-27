# Test Suite 04 — IMSI-Mode Subscriber Profile (Per-IMSI IP Resolution)

## What this test suite validates
This suite validates subscriber profiles where each individual IMSI number has its own dedicated static IP address, and the APN is ignored during lookup. It covers creation of a multi-IMSI profile, per-IMSI lookups, per-IMSI suspension and reactivation (without affecting other IMSIs on the same profile), ICCID enrichment, and IP address changes.

## Pre-conditions (Setup)
1. The subscriber-profile-api and the aaa-lookup-service are both running and reachable.
2. One IP pool is created before the tests begin:
   - Subnet `100.65.150.0/24`, named `pool-b-04`, for account `TestAccount`.
   - If the pool already exists from a previous run, it is reused.
3. Tests 4.1 through 4.9 share a single subscriber profile created in test 4.1 and must run in order.

---

## Test 4.1 — Create an IMSI-mode profile with two IMSIs and distinct IPs

**Goal:** Confirm that a subscriber profile in IMSI resolution mode can be created with two separate IMSI numbers, each assigned its own static IP.

1. Send a request to create a profile in `imsi` mode with no ICCID, for account `TestAccount`, with:
   - IMSI `278773040000001` → static IP `100.65.150.5`
   - IMSI `278773040000002` → static IP `101.65.150.5`
2. Verify the response is HTTP 201 (created).
3. Verify the response body contains a `sim_id` field.
4. Save the `sim_id` for subsequent tests.

---

## Test 4.2 — Lookup for the first IMSI returns its assigned IP

**Goal:** Confirm that a lookup for IMSI-1 returns its own IP.

1. Send a lookup request with IMSI `278773040000001` and APN `internet.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `100.65.150.5`.

---

## Test 4.3 — Lookup for IMSI-1 with a different APN returns the same IP

**Goal:** Confirm that the APN is ignored in IMSI mode — the same IP is returned regardless of which APN is used.

1. Send a lookup request with IMSI `278773040000001` and APN `ims.operator.com` (a different APN than used in test 4.2).
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` still equals `100.65.150.5`.

---

## Test 4.4 — Lookup for the second IMSI returns its own distinct IP

**Goal:** Confirm that IMSI-2 has a different IP than IMSI-1, demonstrating per-IMSI IP isolation.

1. Send a lookup request with IMSI `278773040000002` and APN `internet.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `101.65.150.5` (distinct from IMSI-1's IP).

---

## Test 4.5 — Enrich the profile with an ICCID

**Goal:** Confirm that an ICCID can be added to an existing profile that was created without one.

1. Send a PATCH request to set `iccid` to `8944501040000000001` on the profile.
2. Verify the response is HTTP 200 (success).
3. Retrieve the profile and verify the `iccid` field now equals `8944501040000000001`.

---

## Test 4.6 — Suspend a single IMSI within the profile

**Goal:** Confirm that an individual IMSI can be suspended without affecting other IMSIs on the same profile.

1. Send a PATCH request to the IMSI-level endpoint for IMSI `278773040000001`, setting its `status` to `suspended`.
2. Verify the response is HTTP 200 (success).

---

## Test 4.7 — Lookup for a suspended IMSI returns access denied

**Goal:** Confirm that lookups for a suspended IMSI are blocked.

1. Send a lookup request with IMSI `278773040000001` and APN `internet.operator.com`.
2. Verify the response is HTTP 403 (forbidden).
3. Verify the response body contains `error: suspended`.

---

## Test 4.8 — Lookup for the other IMSI still works while IMSI-1 is suspended

**Goal:** Confirm that suspending one IMSI does not affect other IMSIs on the same profile.

1. Send a lookup request with IMSI `278773040000002` and APN `internet.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `101.65.150.5` (IMSI-2 is unaffected).

---

## Test 4.9 — Reactivate IMSI-1 and change its IP address

**Goal:** Confirm that an IMSI can be reactivated and given a new static IP in a single update, and that subsequent lookups reflect the new IP.

1. Send a PATCH request to the IMSI-level endpoint for IMSI `278773040000001`, setting `status` to `active`, `static_ip` to `100.65.150.99`, and the `pool_id` to the pool created in setup.
2. Verify the response is HTTP 200 (success).
3. Send a lookup request with IMSI `278773040000001` and APN `internet.operator.com`.
4. Verify the response is HTTP 200 (success).
5. Verify `static_ip` equals `100.65.150.99` (the new IP).

---

## Test 4.10 — IMSI-2 with a second APN still returns its own IP

**Goal:** Complement test 4.3 by confirming APN-agnostic resolution works symmetrically for IMSI-2 as well.

1. Send a lookup request with IMSI `278773040000002` and APN `ims.operator.com` (a different APN).
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `101.65.150.5` (APN is ignored; IMSI-2's IP is unchanged).

---

## Post-conditions (Teardown)
1. The subscriber profile is deleted.
2. The IP pool created during setup is deleted.
