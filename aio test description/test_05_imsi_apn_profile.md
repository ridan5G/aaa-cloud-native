# Test Suite 05 — IMSI+APN-Mode Subscriber Profile (Per-IMSI, Per-APN IP Resolution)

## What this test suite validates
This suite validates subscriber profiles where each IMSI and APN combination has its own dedicated static IP address. This is the most granular resolution mode — a single subscriber SIM can connect through different APNs and receive a different IP on each. The suite also validates wildcard APN entries (a catch-all fallback when no exact APN match exists), correct priority between exact matches and wildcards, and that concurrent lookups for different APNs on the same IMSI are handled correctly.

## Pre-conditions (Setup)
1. The subscriber-profile-api and the aaa-lookup-service are both running and reachable.
2. One IP pool is created before the tests begin:
   - Subnet `100.65.160.0/24`, named `pool-c-05`, for account `TestAccount`.
   - If the pool already exists from a previous run, it is reused.
3. Tests 5.1 through 5.9 share a single subscriber profile created in test 5.1 and must run in order.

---

## Test 5.1 — Create an IMSI+APN-mode profile with multiple IMSI/APN combinations

**Goal:** Confirm that a profile in `imsi_apn` resolution mode can be created with multiple IMSIs, each having multiple APN-to-IP mappings.

1. Send a request to create a profile in `imsi_apn` mode with no ICCID, for account `TestAccount`, with:
   - IMSI `278773050000001`:
     - APN `smf1.operator.com` → IP `100.65.160.1`
     - APN `smf2.operator.com` → IP `100.65.160.2`
   - IMSI `278773050000002`:
     - APN `smf3.operator.com` → IP `100.65.160.3`
     - APN `smf4.operator.com` → IP `100.65.160.5`
2. Verify the response is HTTP 201 (created).
3. Verify the response body contains a `sim_id` field.
4. Save the `sim_id` for subsequent tests.

---

## Test 5.2 — Lookup IMSI-1 on its first APN

**Goal:** Confirm that a lookup for IMSI-1 with APN `smf1` returns the correct APN-specific IP.

1. Send a lookup request with IMSI `278773050000001` and APN `smf1.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `100.65.160.1`.

---

## Test 5.3 — Lookup IMSI-1 on its second APN

**Goal:** Confirm that the same IMSI returns a different IP when connecting through a different APN.

1. Send a lookup request with IMSI `278773050000001` and APN `smf2.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `100.65.160.2` (different from the smf1 IP).

---

## Test 5.4 — Lookup IMSI-2 on its APN

**Goal:** Confirm that IMSI-2 resolves to its own distinct IP.

1. Send a lookup request with IMSI `278773050000002` and APN `smf3.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `100.65.160.3`.

---

## Test 5.5 — Lookup with an unknown APN and no wildcard returns not found

**Goal:** Confirm that when no APN match exists and no wildcard is configured, the lookup returns a clear not-found error.

1. Send a lookup request with IMSI `278773050000001` and APN `smf9.unknown.com` (not in the profile).
2. Verify the response is HTTP 404 (not found).
3. Verify the response body contains `error: apn_not_found`.

---

## Test 5.6 — Add a wildcard APN entry to IMSI-1

**Goal:** Confirm that a catch-all wildcard APN entry can be added to an existing IMSI, giving it a fallback IP for any unrecognised APN.

1. Send a PATCH request to the IMSI-level endpoint for IMSI `278773050000001`, providing the full updated list of APN-IP mappings:
   - APN `smf1.operator.com` → IP `100.65.160.1` (unchanged)
   - APN `smf2.operator.com` → IP `100.65.160.2` (unchanged)
   - APN `null` (wildcard) → IP `100.65.160.4` (new)
2. Verify the response is HTTP 200 (success).

---

## Test 5.7 — Unknown APN now resolves via the wildcard

**Goal:** Confirm that after adding the wildcard entry, the same unknown APN that previously returned not-found now resolves to the wildcard IP.

1. Send a lookup request with IMSI `278773050000001` and APN `smf9.unknown.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `100.65.160.4` (the wildcard IP).

---

## Test 5.8 — Exact APN match takes priority over the wildcard

**Goal:** Confirm that when both an exact APN entry and a wildcard exist, the exact entry wins.

1. Send a lookup request with IMSI `278773050000001` and APN `smf1.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `100.65.160.1` (the exact smf1 IP, not the wildcard IP).

---

## Test 5.9 — Concurrent lookups for different APNs on the same IMSI

**Goal:** Confirm that the lookup service handles simultaneous requests for different APN entries on the same IMSI correctly, without returning mixed-up IPs.

1. Launch two simultaneous lookup requests for IMSI `278773050000001`:
   - Request A: APN `smf1.operator.com`
   - Request B: APN `smf2.operator.com`
2. Wait for both requests to complete.
3. Verify Request A returned HTTP 200 with `static_ip` equal to `100.65.160.1`.
4. Verify Request B returned HTTP 200 with `static_ip` equal to `100.65.160.2`.

---

## Test 5.10 — IMSI-2 second APN resolves to its own distinct IP

**Goal:** Confirm that IMSI-2's second APN entry resolves correctly, symmetric with the multi-APN behaviour validated for IMSI-1.

1. Send a lookup request with IMSI `278773050000002` and APN `smf4.operator.com`.
2. Verify the response is HTTP 200 (success).
3. Verify `static_ip` equals `100.65.160.5` (IMSI-2's second APN IP).

---

## Post-conditions (Teardown)
1. The subscriber profile is deleted.
2. The IP pool created during setup is deleted.
