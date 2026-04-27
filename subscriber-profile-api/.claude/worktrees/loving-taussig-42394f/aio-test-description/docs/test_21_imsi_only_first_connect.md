# Test Suite 21 — IMSI-Only First-Connect Provisioning (All IP Resolution Modes)

## What this test suite validates

This suite verifies that "skip-ICCID" range configurations (created without ICCID bounds, using `provisioning_mode="first_connect"`) correctly allocate IPs on demand when a SIM connects for the first time. It covers all four IP resolution modes (`imsi`, `imsi_apn`, `iccid`, `iccid_apn`) and verifies the sibling slot pre-provisioning feature (where connecting one IMSI also pre-provisions all other IMSI slots for the same card, preventing a thundering-herd problem). It also tests idempotency and a set of edge-case error paths.

## Pre-conditions (Setup)

Each of the five test groups (A–E) handles its own setup within the first test step (tests are numbered sequentially, with setup embedded in `test_01_setup`). Each group force-clears any stale profiles for its IMSI ranges before creating pools and configs.

---

## Group A — ip_resolution="imsi" (per-IMSI IP, 2 slots, 3 cards)

**Setup (Test 21.A.1):**
1. Force-clear stale profiles for both slot IMSI ranges.
2. Create pool `test-21-A` in subnet `100.65.240.0/24`.
3. Create a skip-ICCID range config with `ip_resolution="imsi"`, `imsi_count=2`, `provisioning_mode="first_connect"`.
4. Add slot 1 (IMSI range covering 3 cards) and slot 2 (IMSI range covering the same 3 cards).

### Test 21.A.2 — First connect on slot-1 card-0 creates a new profile and allocates an IP

**Goal:** Confirm that the first connection for an IMSI triggers profile creation and IP allocation.

1. Send a `POST /first-connection` request for the first IMSI in slot 1.
2. Verify the response is HTTP 201 (created).
3. Verify the response contains a `sim_id` and a non-null `static_ip`.

### Test 21.A.3 — Slot-2 card-0 is pre-provisioned by the sibling loop

**Goal:** Confirm that when slot-1 connects, the system automatically provisions slot-2 for the same card (thundering-herd prevention).

1. Send a `POST /first-connection` request for the first IMSI in slot 2 (same card offset 0).
2. Verify the response is HTTP 200 (success / idempotent) — not HTTP 201 (meaning it was already provisioned).
3. Verify the returned `sim_id` matches the one returned in test A.2 (same card, same profile).
4. Verify the slot-2 `static_ip` is different from the slot-1 IP (in `imsi` mode, each IMSI has its own IP).

### Test 21.A.4 — Connecting slot-1 card-0 again returns the same sim_id and IP

**Goal:** Confirm that first-connection is fully idempotent.

1. Send a `POST /first-connection` request for the same slot-1 IMSI again.
2. Verify the response is HTTP 200 (success).
3. Verify the returned `sim_id` and `static_ip` match the values from test A.2.

### Test 21.A.5 — Connecting slot-1 card-1 creates a new, separate profile

**Goal:** Confirm that a different card (card offset 1) within the same range gets its own fresh profile and IPs.

1. Send a `POST /first-connection` request for the second IMSI in slot 1 (card offset 1).
2. Verify the response is HTTP 201 (created) with a different `sim_id` from card-0's profile.
3. Verify the `static_ip` is different from card-0's slot-1 IP.
4. Send a `POST /first-connection` for slot-2 card-1.
5. Verify it returns HTTP 200 (pre-provisioned) with the same `sim_id` as slot-1 card-1.

### Test 21.A.6 — Pool consumption is correct: 4 IPs for 2 provisioned cards

**Goal:** Confirm the pool accounting is accurate — one IP per IMSI per card (2 slots × 2 cards = 4 IPs).

1. Send a request to `GET /pools/{pool_id}/stats`.
2. Verify `allocated = 4`.

### Test 21.A.7 — Teardown: delete the range config and pool

1. Force-clear profiles for all IMSI ranges.
2. Delete the range config.
3. Delete the pool.

---

## Group B — ip_resolution="imsi_apn" (per-IMSI per-APN IPs, 2 slots, 2 APNs per slot, 3 cards)

**Setup (Test 21.B.1):**
1. Force-clear stale profiles for both slot ranges.
2. Create internet pool (`test-21-B-inet`) and IMS pool (`test-21-B-ims`).
3. Create a skip-ICCID range config with `ip_resolution="imsi_apn"`, `imsi_count=2`, `provisioning_mode="first_connect"`.
4. Add slot 1 and slot 2 with APN pool entries for internet and IMS APNs (APN pools must be configured before first-connect).

### Test 21.B.2 — Slot-1 card-0 connects on the internet APN and both APNs are provisioned

**Goal:** Confirm that connecting on one APN provisions all configured APNs for that slot and card.

1. Send a `POST /first-connection` for slot-1's first IMSI using the internet APN.
2. Verify the response is HTTP 201 (created) with a non-null `static_ip`.

### Test 21.B.3 — Slot-1 connecting again on the IMS APN is idempotent

**Goal:** Confirm the IMS APN was provisioned alongside the internet APN and returns a different IP.

1. Send a `POST /first-connection` for the same IMSI using the IMS APN.
2. Verify the response is HTTP 200 (idempotent) with the same `sim_id`.
3. Verify the IMS `static_ip` is different from the internet IP.

### Test 21.B.4 — Slot-2 card-0 was pre-provisioned for the internet APN

**Goal:** Confirm the sibling loop also pre-provisioned slot-2 when slot-1 connected.

1. Send a `POST /first-connection` for slot-2's first IMSI using the internet APN.
2. Verify the response is HTTP 200 (pre-provisioned) with the same `sim_id` as slot-1 card-0.
3. Verify slot-2's internet IP is different from slot-1's internet IP (each IMSI has its own IP in `imsi_apn` mode).

### Test 21.B.5 — Slot-2 IMS APN was also pre-provisioned

**Goal:** Confirm all APNs were pre-provisioned for the sibling slot.

1. Send a `POST /first-connection` for slot-2's IMSI using the IMS APN.
2. Verify the response is HTTP 200 with the same `sim_id`.

### Test 21.B.6 — Teardown

1. Force-clear profiles, delete range config, delete both pools.

---

## Group C — ip_resolution="iccid" (card-level shared IP, 2 slots, 3 cards)

**Setup (Test 21.C.1):**
1. Create pool `test-21-C`. Create a skip-ICCID config with `ip_resolution="iccid"`, `imsi_count=2`.
2. Add slots 1 and 2.

### Test 21.C.2 — Slot-1 card-0 connects and receives a card-level IP

**Goal:** Confirm one IP is allocated at the card level (shared across all slots).

1. Send a `POST /first-connection` for slot-1's first IMSI.
2. Verify the response is HTTP 201 (created) with a non-null `static_ip`.

### Test 21.C.3 — Slot-2 card-0 returns the SAME card-level IP

**Goal:** Confirm that in `iccid` mode, all slots on the same card share one IP.

1. Send a `POST /first-connection` for slot-2's first IMSI.
2. Verify the response is HTTP 200 (pre-provisioned) with the same `sim_id` and the same `static_ip` as slot-1.

### Test 21.C.4 — Slot-1 connects again and returns the same IP (idempotent)

1. Send a `POST /first-connection` for slot-1's first IMSI again.
2. Verify HTTP 200 with the same `sim_id` and IP.

### Test 21.C.5 — Card 1 gets a fresh profile and a different card-level IP

**Goal:** Confirm each card produces a distinct profile with its own card-level IP.

1. Send a `POST /first-connection` for slot-1's second IMSI (card offset 1).
2. Verify HTTP 201 with a different `sim_id` and different IP from card-0.
3. Send a `POST /first-connection` for slot-2 card-1; verify HTTP 200 with the same card-level IP.

### Test 21.C.6 — Pool shows 2 IPs allocated (one per card, not per slot)

1. Send `GET /pools/{pool_id}/stats`.
2. Verify `allocated = 2`.

### Test 21.C.7 — Teardown

1. Force-clear profiles, delete range config, delete pool.

---

## Group D — ip_resolution="iccid_apn" (card-level per-APN IPs, 2 slots, 2 APNs on slot 1, 3 cards)

**Setup (Test 21.D.1):**
1. Create internet and IMS pools. Create a skip-ICCID config with `ip_resolution="iccid_apn"`, `imsi_count=2`.
2. Add slots 1 and 2. Configure APN pools on slot 1 only (card-level IPs are sourced from the first-connecting slot).

### Tests 21.D.2–21.D.5 — Connect on each APN, verify shared card-level IPs per APN, verify slot-2 pre-provisioning

Key verifications:
- Slot-1 connects on internet APN → HTTP 201 with IP from internet pool.
- Slot-1 connects on IMS APN → HTTP 200 with a different IP from IMS pool.
- Slot-2 connects on internet APN → HTTP 200 with the same card-level internet IP as slot-1.
- Slot-2 connects on IMS APN → HTTP 200 with the same card-level IMS IP as slot-1.

### Test 21.D.6 — Teardown

1. Force-clear profiles, delete range config, delete both pools.

---

## Group E — Edge Cases and Error Paths

### Test 21.E.1 — Connecting via a slot-2 IMSI when slot 1 has not been defined returns a clear error

**Goal:** Confirm the system identifies missing slot-1 configuration rather than silently failing.

1. Create a skip-ICCID config with `imsi_count=2`. Add only slot 2 (deliberately omit slot 1).
2. Send a `POST /first-connection` for an IMSI in slot 2.
3. Verify the response is HTTP 422 (unprocessable) with `"error": "missing_slot1"` or an equivalent clear message.

### Test 21.E.2 — Range config stores NULL (not empty string) for ICCID fields

**Goal:** Confirm the database stores the absence of ICCID bounds as a true NULL value.

1. Create a skip-ICCID config (no `f_iccid`/`t_iccid`).
2. Send a request to `GET /iccid-range-configs/{id}`.
3. Verify the returned `f_iccid` and `t_iccid` fields are `null` (not empty strings).

### Test 21.E.3 — Immediate-mode skip-ICCID config returns 404 on first-connection before provisioning job runs

**Goal:** Confirm that in `provisioning_mode="immediate"`, first-connection returns HTTP 404 until the background job has run.

1. Create a skip-ICCID config with `provisioning_mode="immediate"`, `imsi_count=1`.
2. Add slot 1 (this triggers the immediate job).
3. Before the job completes, send a `POST /first-connection` for a slot-1 IMSI.
4. Verify the response is HTTP 404 (not found) — the profile does not exist yet in the first-connect path.

## Post-conditions (Teardown)

Each group embeds its teardown as the final numbered test step, deleting profiles, range configs, and pools.
