# Test Suite 07e — Release + Reconnect Regression Across All Four Resolution Modes

## What this test suite validates

This suite is a focused regression guard for a specific bug: after calling release-ips on a subscriber profile, the next first-connection call was returning `static_ip = null` instead of allocating a fresh IP. The bug affected all four IP resolution modes (imsi, imsi_apn, iccid, iccid_apn). The suite runs a full release-then-reconnect cycle for each mode and confirms the re-allocated IP is never null. A fifth test also covers a multi-APN recovery scenario: after release, reconnecting with one APN must restore IPs for all configured APNs, not just the one used in the reconnect request.

## Pre-conditions (Setup)

1. Any stale subscriber profiles from a previous test run are cleaned up.
2. Four separate IP pools are created, one per resolution mode, each using a /28 subnet (14 usable IPs):
   - `imsi` mode pool: `100.65.206.0/28`
   - `imsi_apn` mode pool: `100.65.206.16/28`
   - `iccid` mode pool: `100.65.206.32/28`
   - `iccid_apn` mode pool: `100.65.206.48/28`
3. A standalone range configuration is created for the `imsi` mode (IMSI slots 001–009).
4. A standalone range configuration is created for the `imsi_apn` mode (IMSI slots 011–019), with two APNs in its catalog: internet and ims.
5. An ICCID-based range configuration is created for the `iccid` mode (IMSI slots 021–029), with one IMSI slot registered.
6. An ICCID-based range configuration is created for the `iccid_apn` mode (IMSI slots 031–039), with one IMSI slot registered and an APN catalog entry for the internet APN.

The shared test cycle used by tests 1–4 works as follows:
- Step 1: Send first-connection — confirm HTTP 201 and a non-null IP.
- Step 2: Record pool stats, then send release-ips — confirm at least 1 IP returned and pool available count increased.
- Step 3: Send first-connection again (same IMSI, same APN) — confirm HTTP 200 or 201 and a non-null IP. **This is the key regression assertion.**
- Step 4: Confirm pool allocated count went back up.

---

## Test 7e.01 — imsi mode: release-ips then reconnect re-allocates an IP

**Goal:** In imsi mode, after releasing a subscriber's IP, the next first-connection must allocate a fresh non-null IP.

1. Run the full release-reconnect cycle for an IMSI in the `imsi` mode range.
2. Confirm the final re-allocated IP is not null.

---

## Test 7e.02 — imsi_apn mode: release-ips then reconnect re-allocates an IP

**Goal:** In imsi_apn mode, after releasing, reconnecting with the primary APN must allocate a new non-null IP.

1. Run the full release-reconnect cycle for an IMSI in the `imsi_apn` mode range.
2. Confirm the final re-allocated IP is not null.

---

## Test 7e.03 — iccid mode: release-ips then reconnect re-allocates an IP

**Goal:** In iccid mode (card-level IP), after releasing, reconnecting must allocate a fresh card-level IP.

1. Run the full release-reconnect cycle for an IMSI in the `iccid` mode range.
2. Confirm the final re-allocated IP is not null.

---

## Test 7e.04 — iccid_apn mode: release-ips then reconnect re-allocates an IP

**Goal:** In iccid_apn mode, after releasing, reconnecting with the internet APN must allocate a fresh non-null card-level IP.

1. Run the full release-reconnect cycle for an IMSI in the `iccid_apn` mode range.
2. Confirm the final re-allocated IP is not null.

---

## Test 7e.05 — imsi_apn multi-APN idempotency recovery after release

**Goal:** When a range configuration lists two APNs in its catalog, a single first-connection must allocate both. After releasing all IPs, reconnecting with just the primary APN must restore IPs for both APNs — not only the one used in the reconnect request. This guards against a specific secondary bug where only the triggering APN was re-allocated after release.

1. Send a first-connection for a fresh IMSI using the internet (primary) APN — confirm HTTP 201 and a non-null IP.
2. Send a first-connection for the same IMSI using the ims (secondary) APN — confirm HTTP 200 and a non-null IP (pre-allocated by the catalog in step 1).
3. Retrieve the profile and confirm it has exactly 2 `apn_ips` entries, both with non-null IPs.
4. Send release-ips — confirm HTTP 200 with `released_count` = 2, and the pool's available count increases by 2.
5. Send first-connection again using only the primary (internet) APN.
6. Confirm HTTP 200 or 201 and a non-null IP for the primary APN.
7. Retrieve the profile again and confirm both APNs now have non-null IPs — this is the key regression assertion for the multi-APN case.

---

## Post-conditions (Teardown)

1. The iccid-based range configurations (and their IMSI slot registrations) are deleted.
2. The standalone range configurations for imsi and imsi_apn modes are deleted.
3. All four IP pools are deleted.
