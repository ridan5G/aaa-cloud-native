# Test Suite 12b — RADIUS End-to-End Coverage: All Four IP Resolution Modes

## What this test suite validates

This suite extends the basic RADIUS test (test_12) by verifying that the RADIUS authentication flow works correctly for all four IP resolution modes: `iccid` (card-level IP, APN ignored), `imsi_apn` (per-IMSI APN routing), and `iccid_apn` (card-level APN routing). It also tests per-IMSI suspension (blocking one IMSI while a sibling on the same card stays active) and the first-connection flow in `imsi_apn` mode via RADIUS, where connecting with one APN must pre-allocate IPs for all APNs in the catalog.

Every test sends real RADIUS UDP packets and inspects the Access-Accept / Access-Reject response.

**Note:** This suite is tagged `@pytest.mark.radius`. All tests are skipped if the RADIUS server is not reachable.

## Pre-conditions (Setup)

1. Any stale profiles from a previous test run are soft-deleted; any terminated profiles that lock ICCIDs are hard-deleted.
2. The following pools and profiles are created:

   **iccid mode** (pool `pool-r12b-iccid`, subnet `100.65.121.0/29`):
   - One subscriber profile created for a physical card (ICCID #1) with two IMSIs (IMSI_ICCID_A and IMSI_ICCID_B), card-level IP = `100.65.121.1`.

   **imsi_apn mode** (two pools — internet: `100.65.121.8/29`, ims: `100.65.121.16/29`):
   - One subscriber profile for IMSI_IAPN with two APN IP entries: internet APN → `100.65.121.9`, ims APN → `100.65.121.17`.

   **iccid_apn mode** (pool `pool-r12b-icapn`, subnet `100.65.121.24/29`):
   - One subscriber profile for a physical card (ICCID #3) with two IMSIs (IMSI_ICAPN_A and IMSI_ICAPN_B), two card-level APN IPs: internet → `100.65.121.25`, ims → `100.65.121.26`.

   **first-connection imsi_apn** (two pools — fc-int: `100.65.122.0/28`, fc-ims: `100.65.122.16/28`):
   - A range configuration for IMSI_FC_IAPN's range, with an APN catalog: internet → fc-int pool, ims → fc-ims pool. No profile is created ahead of time; the first-connection test creates it.

---

## Test 12b.1 — iccid mode: Primary IMSI returns Access-Accept with the card-level IP

**Goal:** In iccid mode, the primary IMSI on a card is authenticated and the single card-level IP is returned.

1. Send a RADIUS Access-Request for IMSI_ICCID_A with the internet APN.
2. Confirm Access-Accept.
3. Confirm `Framed-IP-Address` = `100.65.121.1`.

---

## Test 12b.2 — iccid mode: Secondary IMSI on the same card returns the same IP

**Goal:** A second IMSI bound to the same physical card shares the card-level IP — APN is irrelevant in iccid mode.

1. Send a RADIUS Access-Request for IMSI_ICCID_B with the ims APN (a different APN than test 12b.1).
2. Confirm Access-Accept.
3. Confirm `Framed-IP-Address` = `100.65.121.1` (the same card IP).

---

## Test 12b.3 — iccid mode: An unrecognized APN is ignored; card IP is still returned

**Goal:** In iccid mode, the APN in the Called-Station-Id attribute is completely irrelevant to IP resolution.

1. Send a RADIUS Access-Request for IMSI_ICCID_A with a garbage APN (e.g., `completely.unknown.apn`).
2. Confirm Access-Accept.
3. Confirm `Framed-IP-Address` = `100.65.121.1` (unchanged despite the unrecognized APN).

---

## Test 12b.4 — imsi_apn mode: Internet APN returns the internet IP

**Goal:** In imsi_apn mode, the RADIUS server routes to the correct APN-specific IP when the internet APN is in the request.

1. Send a RADIUS Access-Request for IMSI_IAPN with the internet APN.
2. Confirm Access-Accept.
3. Confirm `Framed-IP-Address` = `100.65.121.9`.

---

## Test 12b.5 — imsi_apn mode: ims APN returns a different IP for the same IMSI

**Goal:** Different APNs produce different Framed-IP-Address values for the same IMSI in imsi_apn mode.

1. Send a RADIUS Access-Request for IMSI_IAPN with the ims APN.
2. Confirm Access-Accept.
3. Confirm `Framed-IP-Address` = `100.65.121.17`.
4. Confirm this IP is different from the internet APN IP (`100.65.121.9`).

---

## Test 12b.6 — imsi_apn mode: Unknown APN gets Access-Reject

**Goal:** In imsi_apn mode, requesting access with an APN that is not provisioned in the subscriber's profile results in Access-Reject.

1. Send a RADIUS Access-Request for IMSI_IAPN with a garbage APN.
2. Confirm Access-Reject (code 3).

---

## Test 12b.7 — iccid_apn mode: Internet APN returns the card-level internet IP

**Goal:** In iccid_apn mode, the APN in the RADIUS request is used to select the appropriate card-level IP.

1. Send a RADIUS Access-Request for IMSI_ICAPN_A with the internet APN.
2. Confirm Access-Accept.
3. Confirm `Framed-IP-Address` = `100.65.121.25`.

---

## Test 12b.8 — iccid_apn mode: ims APN returns the card-level ims IP

**Goal:** A different APN produces a different card-level IP in iccid_apn mode.

1. Send a RADIUS Access-Request for IMSI_ICAPN_A with the ims APN.
2. Confirm Access-Accept.
3. Confirm `Framed-IP-Address` = `100.65.121.26`.

---

## Test 12b.9 — iccid_apn mode: Sibling IMSI on the same card returns the same card-level IPs

**Goal:** In iccid_apn mode, all IMSIs on the same physical card share the same set of card-level IPs; IMSI_ICAPN_B must resolve identically to IMSI_ICAPN_A.

1. Send a RADIUS Access-Request for IMSI_ICAPN_B with the internet APN.
2. Confirm Access-Accept and `Framed-IP-Address` = `100.65.121.25`.
3. Send a RADIUS Access-Request for IMSI_ICAPN_B with the ims APN.
4. Confirm Access-Accept and `Framed-IP-Address` = `100.65.121.26`.

---

## Test 12b.10 — iccid_apn mode: Unknown APN gets Access-Reject

**Goal:** Like imsi_apn mode, requesting an unrecognized APN in iccid_apn mode results in Access-Reject.

1. Send a RADIUS Access-Request for IMSI_ICAPN_A with a garbage APN.
2. Confirm Access-Reject (code 3).

---

## Test 12b.11 — Per-IMSI suspension: Suspended IMSI gets Reject; sibling stays Accept

**Goal:** Suspending one IMSI at the per-IMSI level blocks only that IMSI. The sibling IMSI on the same card remains fully active.

1. Send an update request to suspend IMSI_ICCID_A at the IMSI level (not the entire SIM).
2. Confirm the update succeeds.
3. Send a RADIUS Access-Request for IMSI_ICCID_A — confirm Access-Reject.
4. Send a RADIUS Access-Request for IMSI_ICCID_B (sibling, still active) — confirm Access-Accept with `Framed-IP-Address` = `100.65.121.1`.
5. Send an update request to reactivate IMSI_ICCID_A.
6. Confirm the reactivation succeeds.
7. Send a RADIUS Access-Request for IMSI_ICCID_A — confirm Access-Accept with the card-level IP.

---

## Test 12b.12 — imsi_apn first-connection via RADIUS: internet APN allocates an IP

**Goal:** When a RADIUS request arrives for an IMSI with no profile in imsi_apn mode, first-connection is triggered automatically, both the internet and ims IPs are allocated from the catalog in one transaction, and the RADIUS response is Access-Accept with the internet IP.

1. Confirm that IMSI_FC_IAPN has no existing profile.
2. Send a RADIUS Access-Request for IMSI_FC_IAPN with the internet APN, IMEI, and `charging_chars = "0800"`.
3. Confirm Access-Accept with a non-null Framed-IP-Address from the internet pool.
4. Record the internet IP for the next test.
5. Retrieve the auto-created profile via the API and record its `sim_id` for teardown.
6. Send a lookup request for IMSI_FC_IAPN with the internet APN — confirm HTTP 200 and the same IP as in the Accept.

---

## Test 12b.13 — imsi_apn first-connection: ims APN returns a different pre-allocated IP

**Goal:** After the first-connection in test 12b.12 allocated both APNs, requesting the ims APN must return the pre-allocated ims IP without triggering a second first-connection.

1. Confirm the internet IP from test 12b.12 is recorded (this test depends on 12b.12 having run first).
2. Send a RADIUS Access-Request for IMSI_FC_IAPN with the ims APN.
3. Confirm Access-Accept with a non-null Framed-IP-Address.
4. Confirm the ims IP is different from the internet IP (different APNs = different pools = different IPs).
5. Record the ims IP for any further inspection.

---

## Post-conditions (Teardown)

1. All subscriber profiles created during setup and tests (iccid profile, imsi_apn profile, iccid_apn profile, and the auto-provisioned first-connection profile) are deleted.
2. The first-connection range configuration is deleted.
3. All IP pools (iccid, imsi_apn internet and ims, iccid_apn, fc-int, fc-ims) are deleted.
