# Test Suite 09 — Migration Validation

## What this test suite validates

This suite verifies that data migrated from the legacy MariaDB system into the new PostgreSQL schema is accurate and accessible via the REST API. It checks four specific migration scenarios — a subscriber with a known SIM card (ICCID), a subscriber without a card, a subscriber that appeared in two source data dumps with different IPs (which implies an APN-based resolution mode), and a subscriber that appeared in two dumps with the same IP (which implies a single-IP resolution mode). It also confirms that range configurations and IP pool accounting are correctly migrated.

**Note:** This test suite is tagged for optional execution. It is not included in the default test run; it must be enabled explicitly (e.g., `pytest -m migration`). The test's setup seeds the expected data via the API rather than running the actual migration tool, so it can run in CI without a live legacy database.

## Pre-conditions (Setup)

1. An IP pool is created representing the migrated pool from the legacy system: subnet `100.65.220.0/24`, pool name `athens-migrated`, account `AthensOperator`.
2. A range configuration is created covering the Athens operator's IMSI range (`278773090000001` through `278773090999999`), using `imsi` resolution mode.
3. Four subscriber profiles are created to simulate what the migration script would have produced:
   - **Profile A** (`IMSI_WITH_ICCID`): iccid mode, with a real ICCID from the mapping file, card-level IP `100.65.220.3`.
   - **Profile B** (`IMSI_NO_ICCID`): imsi mode, ICCID field is null (IMSI was not in the mapping file), single IP `100.65.220.4`.
   - **Profile C** (`IMSI_DUAL_APN`): imsi_apn mode, appeared in two source dumps with different IPs — one IP per gateway (pgw1 = `100.65.220.1`, pgw2 = `100.65.220.2`).
   - **Profile D** (`IMSI_SAME_IP`): imsi mode, appeared in two source dumps with the same IP — deduplicated to a single IP `100.65.220.10`.

---

## Test 9.1 — Correct number of profiles migrated for the Athens account

**Goal:** Confirm that at least 4 subscriber profiles are visible under the `AthensOperator` account.

1. Send a request to list all profiles for account name `AthensOperator`.
2. Confirm HTTP 200 (success).
3. Confirm at least 4 profiles are returned.

---

## Test 9.2 — An IMSI that was in the ICCID mapping file has a real ICCID on its profile

**Goal:** When the migration script found an IMSI in the `imsi_iccid_map.csv` file, the resulting profile must have the correct ICCID set.

1. Send a request to look up the profile for `IMSI_WITH_ICCID`.
2. Confirm HTTP 200 (success) and at least one profile returned.
3. Confirm the profile's `iccid` field equals the expected ICCID from the mapping file.

---

## Test 9.3 — An IMSI not in the mapping file has no ICCID (null)

**Goal:** When no ICCID mapping was available for an IMSI, the profile's ICCID must be null (not a fabricated value).

1. Send a request to look up the profile for `IMSI_NO_ICCID`.
2. Confirm HTTP 200 and at least one profile.
3. Confirm the profile's `iccid` field is null.

---

## Test 9.4 — An IMSI from two dumps with different IPs is migrated as imsi_apn mode

**Goal:** When the same IMSI appeared in two source data extracts with different IP addresses (one per gateway), the migration must model this as `imsi_apn` mode with one IP entry per APN.

1. Send a request to look up the profile for `IMSI_DUAL_APN`.
2. Confirm the profile's IP resolution mode is `imsi_apn`.
3. Retrieve the full profile details — confirm the IMSI has exactly 2 `apn_ips` entries (one for each gateway APN).
4. Send a lookup request with `pgw1.operator.com` as the APN — confirm HTTP 200 and `static_ip` = `100.65.220.1`.
5. Send a lookup request with `pgw2.operator.com` as the APN — confirm HTTP 200 and `static_ip` = `100.65.220.2`.

---

## Test 9.5 — An IMSI from two dumps with the same IP is migrated as imsi mode

**Goal:** When the same IMSI appeared in two source extracts with the same IP address, the migration must deduplicate and store it as plain `imsi` mode (one IP, APN-agnostic).

1. Send a request to look up the profile for `IMSI_SAME_IP`.
2. Confirm the profile's IP resolution mode is `imsi`.
3. Send a lookup request with any APN — confirm HTTP 200 and `static_ip` = `100.65.220.10`.

---

## Test 9.6 — The migrated range configuration is present and correct

**Goal:** The IMSI range configuration that was derived from the legacy `tbl_imsi_range_config` table must be retrievable via the API with the correct from/to IMSI values.

1. Send a request to list all range configurations for account `AthensOperator`.
2. Confirm HTTP 200 and at least 1 range configuration returned.
3. Confirm the seeded range configuration is in the list with the correct `f_imsi` = `278773090000001` and `t_imsi` = `278773090999999`.

---

## Test 9.7 — IP pool accounting is correct after migration

**Goal:** The pool's statistics must accurately reflect how many IPs were allocated during migration and how many remain available.

1. Send a request to retrieve statistics for the Athens pool.
2. Confirm HTTP 200.
3. Confirm at least 4 IPs are marked as allocated (one per seeded profile).
4. Confirm `available` is non-negative.
5. Confirm `allocated + available` equals 253, which is the correct number of usable addresses in a /24 subnet (excluding network, broadcast, and gateway).

---

## Post-conditions (Teardown)

1. All four seeded subscriber profiles are deleted.
2. The range configuration is deleted.
3. The IP pool is deleted.
