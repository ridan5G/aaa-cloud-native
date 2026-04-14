# Test Suite 18 — Nullable Slot Pool and APN-Pool Routing Regressions

## What this test suite validates

This suite is a targeted regression test for a set of production bugs encountered when configuring multi-IMSI ICCID ranges using `imsi_apn` resolution where IMSI slots are created without a default pool assignment (pool_id = null) and instead rely entirely on per-APN pool overrides. It verifies five distinct scenarios (M5, M5b, M6, M7, M8), each covering a different failure mode that previously caused crashes or incorrect IP allocation.

## Pre-conditions (Setup)

Each of the five scenario classes sets up its own pools, ICCID range config, IMSI slots, and APN-pool mappings. All scenarios use 14-IP `/28` subnets in the `100.65.210.x` range. Before creating resources, each class force-deletes any leftover terminated profiles from a previous run.

---

## Scenario M5 — IMSI-APN mode, both slots have NO default pool (exact production bug reproduction)

**Setup:**
- Create 4 pools: slot-1 internet (`100.65.210.0/28`), slot-1 IMS (`100.65.210.16/28`), slot-2 internet (`100.65.210.32/28`), slot-2 IMS (`100.65.210.48/28`).
- Create an ICCID range config (3 cards, 2 slots) with `ip_resolution="imsi_apn"`, no default pool.
- Add slot 1 with no `pool_id`; attach APN-pool entries for internet and IMS APNs pointing to the slot-1 pools.
- Add slot 2 with no `pool_id`; attach APN-pool entries for internet and IMS APNs pointing to the slot-2 pools.

### Test 18.M5.1 — Slots added without pool_id do not crash the system

**Goal:** Confirm the database schema now allows null pool_id on IMSI slots (the original bug caused a crash here).

1. Verify that `slot1_range_config_id` and `slot2_range_config_id` were set by the setup (if setup succeeded without errors, this bug is fixed).

### Test 18.M5.2 — First-connection on slot-1 IMSI allocates an IP from the slot-1 internet pool

**Goal:** Confirm that when a SIM connects via slot 1 using the internet APN, the system routes the allocation to the correct slot-1 internet pool.

1. Send a `POST /first-connection` request using the first IMSI from slot 1 and the internet APN.
2. Verify the response is HTTP 201 (created) with a non-null IP.
3. Verify the returned IP falls within the slot-1 internet subnet (`100.65.210.0/28`).

### Test 18.M5.3 — Slot 2 is pre-provisioned atomically with both APNs from its own APN catalog

**Goal:** Confirm that when slot 1 connects, the system also pre-provisioned the sibling slot-2 IMSI for the same card, using slot-2's own APN-pool catalog (not slot-1's).

1. Send a request to `GET /profiles?imsi={slot2_first_imsi}`.
2. Verify the profile exists (slot 2 was pre-provisioned).
3. Verify the profile's slot-2 IMSI entry has both internet and IMS APNs already provisioned.

### Test 18.M5.4 — Slot-2 IPs come from slot-2 pools, not slot-1 pools

**Goal:** Confirm correct pool routing — slot-2's IPs must come from slot-2's internet and IMS pools, not slot-1's.

1. Retrieve the profile for the slot-2 IMSI.
2. For each APN entry on slot-2, verify:
   - The internet APN IP falls within the slot-2 internet subnet (`100.65.210.32/28`).
   - The IMS APN IP falls within the slot-2 IMS subnet (`100.65.210.48/28`).

### Test 18.M5.5 — Connecting an already-provisioned slot-2 IMSI is idempotent

**Goal:** Confirm that calling first-connection for slot-2 after it was pre-provisioned returns the existing IP rather than allocating a new one.

1. Send a `POST /first-connection` request for the slot-2 IMSI using the IMS APN.
2. Verify the response is HTTP 200 (success / idempotent) with a non-null IP.

### Test 18.M5.6 — Releasing IPs for the first card returns 4 IPs (2 APNs × 2 slots)

**Goal:** Confirm that the release operation removes all APN IPs for all slots of the card.

1. Retrieve the sim_id for the slot-1 IMSI profile.
2. Send a `POST /profiles/{sim_id}/release-ips` request.
3. Verify the response is HTTP 200 (success) with `released_count = 4`.

### Test 18.M5.7 — Reconnecting after IP release allocates a fresh IP from the slot-1 internet pool

**Goal:** Confirm the re-connection path works correctly after a release.

1. Send a `POST /first-connection` request for the slot-1 IMSI using the internet APN.
2. Verify the response is HTTP 200 or 201 (success) with a non-null IP.
3. Verify the returned IP is within the slot-1 internet subnet (`100.65.210.0/28`).

---

## Scenario M5b — Sibling slot has a pool but NO APN config in imsi_apn mode

**Setup:**
- A 2-card, 2-slot ICCID range with `ip_resolution="imsi_apn"`.
- Slot 1: configured with internet and IMS APN pools.
- Slot 2: has a default `pool_id` but deliberately no APN catalog entries.

### Test 18.M5b.1 — First-connection fails with "missing APN config" when sibling slot has no APN entries

**Goal:** Confirm the system detects the misconfiguration and returns a clear error rather than crashing or silently mis-routing.

1. Send a `POST /first-connection` request for the slot-1 IMSI.
2. Verify the response is HTTP 422 (unprocessable / validation error).
3. Verify the response contains `"error": "missing_apn_config"`.

### Test 18.M5b.2 — No profile is created when the first-connection returns 422

**Goal:** Confirm the transaction was rolled back — no partial profile was saved.

1. Send a request to `GET /profiles?imsi={slot1_first_imsi}`.
2. Verify either HTTP 404 (not found) is returned, or the profile list is empty.

### Test 18.M5b.3 — After adding APN pools to slot 2, first-connection succeeds

**Goal:** Confirm the system recovers correctly once the misconfiguration is resolved.

1. Add internet and IMS APN pool entries to slot 2.
2. Send a `POST /first-connection` request for the slot-1 IMSI.
3. Verify the response is HTTP 201 (created) with a non-null IP.

### Test 18.M5b.4 — After the fix, slot-2 is pre-provisioned with both APNs from its own pool

**Goal:** Confirm the sibling pre-provisioning loop now succeeds for slot-2 after its APN config was added.

1. Send a request to `GET /profiles?imsi={slot2_first_imsi}`.
2. Verify the profile exists with both internet and IMS APNs provisioned.
3. Verify both IPs fall within the slot-2 pool's subnet (`100.65.210.96/28`).

---

## Scenario M6 — ICCID mode, both slots have no pool, parent range supplies the pool

**Goal:** Confirm that in `iccid` (card-level IP) mode, slots without a `pool_id` correctly fall back to the parent ICCID range config's pool.

**Setup:** 2-card, 2-slot ICCID range with `ip_resolution="iccid"`. Parent range has a pool; both slots do not.

Key tests confirm:
- First-connection on slot-1 returns an IP from the parent pool.
- Slot-2 is pre-provisioned and shares the same card-level IP as slot-1 (iccid mode is card-level).
- The pool's allocation count is correct (1 IP per card, not per slot).

---

## Scenario M7 — ICCID-APN mode, slot 1 has APN pools, slot 2 has neither pool nor APN config

**Goal:** Confirm that in `iccid_apn` mode, a slot-2 with no APN config is handled correctly when slot-1 first connects.

**Setup:** 2-card, 2-slot ICCID range with `ip_resolution="iccid_apn"`. Slot 1 has internet and IMS APN pools; slot 2 has no pool and no APN entries.

Key tests confirm:
- First-connection on slot-1 returns an appropriate status (either a card-level IP if slot-2 is acceptable without APNs, or a clear error).

---

## Scenario M8 — Immediate mode, imsi_apn, last slot added with no APN config

**Goal:** Confirm that in immediate provisioning mode, if the last slot is added without an APN catalog and the job fires, the job completes with `completed_with_errors` and a clear error message rather than silently failing or crashing.

**Setup:** 2-card, 2-slot ICCID range with `ip_resolution="imsi_apn"` and `provisioning_mode="immediate"`. Slot 1 has APN pools; slot 2 has none and is added last (triggering the job).

Key tests confirm:
- Adding the last slot (slot 2) returns a `job_id`.
- The job completes with status `completed_with_errors` (not `failed` and not `completed`).
- The error message clearly identifies which SIMs could not be provisioned and why.

---

## Post-conditions (Teardown)

Each scenario class independently cleans up its own ICCID range config and all pools it created.
