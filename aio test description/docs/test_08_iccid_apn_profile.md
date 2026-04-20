# Test Suite 08 — ICCID-APN Profile: Card-Level APN Routing

## What this test suite validates

This suite verifies end-to-end behavior of the `iccid_apn` IP resolution mode, where a physical SIM card is assigned one static IP address per APN (rather than one IP per IMSI). Multiple IMSIs on the same card share the same card-level IPs. The suite covers: profile creation and retrieval, correct APN-based IP resolution for two IMSIs on the same card, wildcard APN fallback behavior (when no exact APN match exists), SIM-level and IMSI-level suspend/reactivate cycles, and the behavior when a profile is deleted (terminated).

## Pre-conditions (Setup)

1. Any active subscriber profiles from a previous test run (for the module's IMSI range) are soft-deleted via the API.
2. Any terminated profiles that still occupy the ICCID (which would block reuse) are hard-deleted directly from the database.
3. A single IP pool is created: subnet `100.65.170.0/24`, pool name `pool-d-08`.
4. Three specific static IPs within that pool are reserved for use in the tests:
   - `100.65.170.1` — for the internet APN
   - `100.65.170.2` — for the ims APN
   - `100.65.170.3` — for a wildcard fallback entry added later in the test run

---

## Test 8.1 — Create a statically provisioned iccid_apn profile

**Goal:** Create a subscriber profile with one physical card (ICCID), two IMSIs, and two APN-specific card-level IPs.

1. Send a create-profile request with:
   - ICCID for the physical card
   - Two IMSI entries (IMSI1 and IMSI2) bound to the card
   - Two card-level IPs: `100.65.170.1` mapped to the internet APN, and `100.65.170.2` mapped to the ims APN
2. Confirm the response contains a `sim_id`.

---

## Test 8.2 — Retrieve the profile and confirm both APN entries are stored

**Goal:** The profile stored in the database accurately reflects both card-level IPs and their APN mappings.

1. Send a request to retrieve the profile by its `sim_id`.
2. Confirm HTTP 200 (success).
3. Confirm the profile's ICCID matches what was submitted.
4. Confirm IP resolution mode is `iccid_apn`.
5. Confirm `iccid_ips` contains two entries: the internet APN maps to `.1` and the ims APN maps to `.2`.

---

## Test 8.3 — Lookup IMSI1 with the internet APN returns the internet IP

**Goal:** The lookup service resolves IMSI1 + internet APN to the card-level internet IP.

1. Send a lookup request with IMSI1 and the internet APN.
2. Confirm HTTP 200 (success).
3. Confirm `static_ip` = `100.65.170.1`.

---

## Test 8.4 — Lookup IMSI1 with the ims APN returns the ims IP

**Goal:** Different APNs resolve to different card-level IPs for the same IMSI.

1. Send a lookup request with IMSI1 and the ims APN.
2. Confirm HTTP 200 (success).
3. Confirm `static_ip` = `100.65.170.2`.

---

## Test 8.5 — IMSI2 (same physical card) resolves the same card-level IPs

**Goal:** Both IMSIs on the same card share identical card-level IPs — IMSI2 must resolve to the same addresses as IMSI1.

1. Send a lookup request with IMSI2 and the internet APN.
2. Confirm HTTP 200 and `static_ip` = `100.65.170.1`.
3. Send a lookup request with IMSI2 and the ims APN.
4. Confirm HTTP 200 and `static_ip` = `100.65.170.2`.

---

## Test 8.6 — Lookup with an unknown APN (and no wildcard) returns HTTP 404 (not found)

**Goal:** When no APN entry matches the requested APN and no wildcard entry exists, the lookup returns "APN not found".

1. Send a lookup request with IMSI1 and an APN that is not in the card's IP list (e.g., `unknown.apn.nowhere`).
2. Confirm HTTP 404 (not found).
3. Confirm the error body contains `"error": "apn_not_found"`.

---

## Test 8.7 — Add a wildcard card-level IP (APN = null)

**Goal:** Update the profile to include a wildcard entry (null APN) that will catch any APN not explicitly listed.

1. Send an update request that replaces the `iccid_ips` list with the existing two entries plus a new entry with `apn = null` and IP `100.65.170.3`.
2. Confirm HTTP 200 (success).

---

## Test 8.8 — Unknown APN now resolves via the wildcard entry

**Goal:** After adding the wildcard, any unrecognized APN should fall back to the wildcard IP.

1. Send a lookup request with IMSI1 and the same unknown APN used in test 8.6.
2. Confirm HTTP 200 (success).
3. Confirm `static_ip` = `100.65.170.3` (the wildcard IP).

---

## Test 8.9 — A registered APN still wins over the wildcard

**Goal:** The lookup service must always prefer an exact APN match over the wildcard, even when a wildcard is present.

1. Send a lookup request with IMSI1 and the internet APN.
2. Confirm HTTP 200 (success).
3. Confirm `static_ip` = `100.65.170.1` (the exact match, not the wildcard `.3`).

---

## Test 8.10 — Suspend the entire SIM (all IMSIs)

**Goal:** Change the profile's status to `suspended`.

1. Send an update request setting the profile status to `suspended`.
2. Confirm HTTP 200 (success).

---

## Test 8.11 — A suspended SIM is blocked for all APN variants

**Goal:** While the SIM is suspended, every lookup — regardless of APN — must return HTTP 403 (forbidden) with error code "suspended".

1. Send lookup requests for IMSI1 with each of the three APNs: internet, ims, and the unknown APN.
2. For each, confirm HTTP 403 (forbidden) and `"error": "suspended"`.

---

## Test 8.12 — Reactivate the SIM; lookups succeed again

**Goal:** Restoring the status to `active` immediately re-enables lookups.

1. Send an update request setting the profile status back to `active`.
2. Confirm HTTP 200 (success).
3. Send a lookup with IMSI1 and the internet APN.
4. Confirm HTTP 200 and `static_ip` = `100.65.170.1`.

---

## Test 8.13 — Suspend IMSI1 individually (IMSI-level suspension)

**Goal:** The platform supports per-IMSI suspension; only IMSI1 is blocked while the SIM (and IMSI2) remain active.

1. Send an update request to suspend IMSI1 at the IMSI level (not the entire SIM).
2. Confirm HTTP 200 (success).

---

## Test 8.14 — Suspended IMSI1 is blocked for all APNs (IMSI-level enforcement)

**Goal:** With IMSI1 individually suspended, all lookups for IMSI1 return HTTP 403, regardless of APN.

1. Send lookup requests for IMSI1 with the internet, ims, and unknown APNs.
2. For each, confirm HTTP 403 (forbidden) and `"error": "suspended"`.

---

## Test 8.15 — IMSI2 (same card) resolves correctly while IMSI1 is suspended

**Goal:** Per-IMSI suspension is independent; IMSI2's status is unaffected by IMSI1's suspension.

1. Send a lookup with IMSI2 and the internet APN.
2. Confirm HTTP 200 and `static_ip` = `100.65.170.1`.
3. Send a lookup with IMSI2 and the ims APN.
4. Confirm HTTP 200 and `static_ip` = `100.65.170.2`.

---

## Test 8.16 — Reactivate IMSI1; lookups succeed again for all APNs

**Goal:** Re-enabling IMSI1 restores its ability to be looked up successfully.

1. Send an update request to set IMSI1's status back to `active`.
2. Confirm HTTP 200.
3. Send lookups for IMSI1 with both the internet and ims APNs.
4. Confirm HTTP 200 and the correct IP for each.

---

## Test 8.17 — Delete the profile; subsequent lookup returns HTTP 403 or 404

**Goal:** Deleting (soft-deleting) the profile marks the SIM as terminated, and any subsequent lookup for its IMSIs is blocked.

1. Send a delete request for the profile.
2. Confirm HTTP 204 (no content / deleted).
3. Send a lookup with IMSI1 and the internet APN.
4. Confirm the response is either HTTP 403 (forbidden — SIM is terminated, not active) or HTTP 404 (not found — IMSI record was removed).
5. If HTTP 403, confirm `"error": "suspended"`.

---

## Post-conditions (Teardown)

1. The subscriber profile is deleted (if not already deleted by test 8.17).
2. The IP pool (`pool-d-08`) is deleted.
