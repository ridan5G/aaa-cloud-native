# Test Suite 07b — Dynamic IP Allocation: All Eight Resolution Modes

## What this test suite validates

This suite verifies that the first-connection flow correctly allocates IP addresses for all eight supported combinations of SIM card type (single-IMSI vs. multi-IMSI) and IP resolution mode (imsi, imsi_apn, iccid, iccid_apn). It confirms that on a device's very first network connection, the platform provisions the right number of IPs from the right pools, links them to the right IMSI slots, and returns the correct IP in the response. Idempotency — calling first-connection a second time and getting the same IP back — is also verified for every mode.

## Pre-conditions (Setup)

Each scenario class creates its own isolated IP pool(s) and range configuration before its tests run:

1. Any stale subscriber profiles left over from a previous interrupted test run are cleaned up.
2. One or two IP pools are created (small /29 subnets with 6 usable addresses each), named per scenario.
3. A range configuration is registered that maps a specific IMSI number range to the pool(s) and sets the correct IP resolution mode.
4. For modes that use an APN catalog (imsi_apn, iccid_apn), the catalog entries (APN name → pool mapping) are added to the range configuration.
5. For multi-IMSI scenarios, a card-level (ICCID) range configuration is created, and each IMSI slot (slot 1, slot 2, etc.) is registered with its own sub-range and pool.

---

## Test S2.01 — Single-IMSI, imsi_apn: First-connection returns the internet APN IP

**Goal:** Confirm that when a single-IMSI SIM connects using the "internet" APN, the response is HTTP 201 (created) with a non-null static IP drawn from the internet pool.

1. Send a first-connection request for a test IMSI, specifying the internet APN.
2. Confirm the response is HTTP 201 (new allocation).
3. Confirm the response body contains a `sim_id` and a `static_ip` that falls within the internet pool's subnet.

## Test S2.02 — Single-IMSI, imsi_apn: Both APN IPs are provisioned in one shot

**Goal:** Confirm that first-connection pre-provisions all APNs listed in the catalog (internet AND ims), not just the one that was requested.

1. Retrieve the subscriber profile created in S2.01.
2. Confirm the profile shows IP resolution mode `imsi_apn`.
3. Confirm the IMSI has two APN IP entries — one for the internet APN and one for the ims APN.

## Test S2.03 — Single-IMSI, imsi_apn: Repeated call returns the same IP (idempotency)

**Goal:** A second first-connection call for the same IMSI and APN must return HTTP 200 (already provisioned) with the exact same IP as the first call.

1. Send a first-connection request for the same IMSI and internet APN a second time.
2. Confirm the response is HTTP 200 (reused, not newly allocated).
3. Confirm the returned IP is identical to the IP allocated in S2.01.

## Test S2.04 — Single-IMSI, imsi_apn: Second APN call is also idempotent

**Goal:** Connecting with the ims APN (already pre-provisioned) returns HTTP 200 and its pre-allocated IP.

1. Send a first-connection request for the same IMSI, but using the ims APN.
2. Confirm the response is HTTP 200.
3. Confirm the returned IP falls within the ims pool's subnet.

---

## Test S3.01 — Single-IMSI, iccid: First-connection allocates a card-level IP

**Goal:** In iccid mode, a single card-level IP (not tied to any APN) is allocated on first connection.

1. Send a first-connection request for a test IMSI.
2. Confirm the response is HTTP 201 with a non-null `static_ip`.

## Test S3.02 — Single-IMSI, iccid: Profile stores a card-level IP with no APN

**Goal:** The profile shows the card-level IP in `iccid_ips` with the APN field empty (null).

1. Retrieve the subscriber profile by IMSI.
2. Confirm the profile's IP resolution mode is `iccid`.
3. Confirm exactly one card-level IP entry exists and its APN field is null.

## Test S3.03 — Single-IMSI, iccid: Any APN returns the same card IP

**Goal:** iccid mode is APN-agnostic; switching APNs does not produce a different IP.

1. Send a first-connection request with the internet APN — record the returned IP.
2. Send a first-connection request with the ims APN for the same IMSI.
3. Confirm both requests return the same IP address.

---

## Test S4.01 — Single-IMSI, iccid_apn: First-connection returns the internet APN card IP

**Goal:** In iccid_apn mode, a card-level IP is allocated per APN; the internet APN IP is returned on first connection.

1. Send a first-connection request specifying the internet APN.
2. Confirm HTTP 201 with a non-null `static_ip` within the internet pool's range.

## Test S4.02 — Single-IMSI, iccid_apn: Both APN IPs are at the card level

**Goal:** The profile stores two card-level IPs (one per APN) rather than per-IMSI IPs.

1. Retrieve the subscriber profile.
2. Confirm IP resolution is `iccid_apn`.
3. Confirm there are exactly two `iccid_ips` entries — one for the internet APN and one for the ims APN.

## Test S4.03 — Single-IMSI, iccid_apn: ims APN call is idempotent

**Goal:** Connecting with the ims APN after the catalog has already been provisioned returns HTTP 200.

1. Send a first-connection request with the ims APN.
2. Confirm the response is HTTP 200 and the returned IP is within the expected pool range.

---

## Test M1.01 — Multi-IMSI, imsi: Slot-1 first-connection returns HTTP 201

**Goal:** When a 2-slot SIM's primary IMSI connects first, a new profile is created with HTTP 201.

1. Send a first-connection request for the slot-1 IMSI.
2. Confirm HTTP 201, with `sim_id` and `static_ip` in the response.

## Test M1.02 — Multi-IMSI, imsi: Slot-2 IMSI is pre-provisioned atomically

**Goal:** The slot-1 connection triggers pre-provisioning of the slot-2 IMSI in the same database transaction — no separate first-connection needed.

1. Look up the subscriber profile by the slot-2 IMSI.
2. Confirm the profile already exists with IP resolution mode `imsi`.
3. Confirm both the slot-1 and slot-2 IMSIs appear on the same profile.

## Test M1.03 — Multi-IMSI, imsi: Slot-2 connection is idempotent

**Goal:** When the slot-2 IMSI connects (already pre-provisioned), the response is HTTP 200.

1. Send a first-connection request for the slot-2 IMSI.
2. Confirm HTTP 200 (reused) with a non-null static IP.

## Test M1.04 — Multi-IMSI, imsi: Each slot has a distinct IP from its own pool

**Goal:** Slot-1 and slot-2 draw IPs from their respective separate pools and the IPs are different.

1. Send first-connection for slot-1 IMSI — record IP.
2. Send first-connection for slot-2 IMSI — record IP.
3. Confirm both return success (HTTP 200 or 201).
4. Confirm the two IPs are different.
5. Confirm each IP falls within its slot's designated pool subnet.

---

## Test M2.01 — Multi-IMSI, imsi_apn: Slot-1 first-connection returns HTTP 201

**Goal:** For a 2-slot, 2-APN SIM, the first connection on slot-1 succeeds and returns the internet APN IP.

1. Send a first-connection request for slot-1 IMSI with the internet APN.
2. Confirm HTTP 201 with `sim_id` and `static_ip`.

## Test M2.02 — Multi-IMSI, imsi_apn: Slot-1 has both APNs provisioned

**Goal:** After slot-1's first connection, both the internet and ims APN IPs exist on the slot-1 IMSI.

1. Look up the subscriber profile by slot-1 IMSI.
2. Confirm the slot-1 IMSI entry has two `apn_ips` entries — one for each APN.

## Test M2.03 — Multi-IMSI, imsi_apn: Slot-2 is pre-provisioned with both APNs

**Goal:** Slot-2 is also provisioned in the same transaction, including both APN IPs.

1. Look up the subscriber profile by slot-2 IMSI.
2. Confirm the profile exists and the slot-2 IMSI entry has both internet and ims APN IPs.

## Test M2.04 — Multi-IMSI, imsi_apn: Total IPs allocated is four

**Goal:** 2 slots × 2 APNs = 4 IPs drawn from two pools.

1. Check the internet pool's statistics — confirm at least 2 IPs are allocated.
2. Check the ims pool's statistics — confirm at least 2 IPs are allocated.

---

## Test M3.01 — Multi-IMSI, iccid: First-connection creates a card-level profile

**Goal:** In iccid mode, connecting with the first slot creates one shared card IP.

1. Send a first-connection request for the slot-1 IMSI.
2. Confirm HTTP 201 with `sim_id` and `static_ip`.

## Test M3.02 — Multi-IMSI, iccid: Both slots share the same IP and sim_id

**Goal:** iccid mode shares a single IP across all IMSIs on the card; both slots point to the same profile.

1. Send first-connection for slot-1 — record IP and sim_id.
2. Send first-connection for slot-2 — confirm HTTP 200.
3. Confirm slot-2's IP equals slot-1's IP.
4. Confirm both share the same `sim_id`.

## Test M3.03 — Multi-IMSI, iccid: Exactly one IP is consumed from the pool

**Goal:** Despite two IMSI slots, iccid mode consumes only one address from the IP pool.

1. Check the pool's statistics.
2. Confirm `allocated` equals 1.

---

## Test M4.01 — Multi-IMSI, iccid_apn: Slot-1 first-connection returns the internet card IP

**Goal:** In iccid_apn mode, the first connection allocates a card-level internet IP.

1. Send a first-connection request for slot-1 IMSI with the internet APN.
2. Confirm HTTP 201 with `sim_id` and `static_ip`.

## Test M4.02 — Multi-IMSI, iccid_apn: Both APN IPs exist at the card level

**Goal:** The profile has two card-level IPs (one per APN) shared across both slots.

1. Retrieve the profile by slot-1 IMSI.
2. Confirm IP resolution is `iccid_apn`.
3. Confirm there are exactly two `iccid_ips` entries: internet and ims.

## Test M4.03 — Multi-IMSI, iccid_apn: Slot-2 returns the same internet card IP

**Goal:** Slot-2 resolves the identical card-level internet IP as slot-1.

1. Send first-connection for slot-1 with internet APN — record IP.
2. Send first-connection for slot-2 with internet APN.
3. Confirm both return the same IP.

## Test M4.04 — Multi-IMSI, iccid_apn: Slot-2 ims APN returns the same card-level ims IP

**Goal:** The ims APN card IP is also shared across slots.

1. Send first-connection for slot-1 with ims APN — record IP.
2. Send first-connection for slot-2 with ims APN.
3. Confirm both return the same ims IP.

---

## Post-conditions (Teardown)

Each scenario class cleans up its own resources in order:

1. The ICCID range configuration (and its IMSI slots) is deleted.
2. Each IP pool created for the scenario is deleted.
3. Subscriber profiles are intentionally left in place after the run so they can be inspected if needed.
