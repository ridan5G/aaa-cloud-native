# Test Suite 13 — Export and IP Search

## What this test suite validates

This suite verifies the profile export API (`GET /profiles/export`) and the IP-address filter for the profile list API (`GET /profiles?ip=`). It also confirms that terminated SIM profiles are no longer hidden from the list and lookup endpoints, and that all filter parameters (account, status, IMSI prefix, ICCID prefix) work correctly on both the list and export APIs.

## Pre-conditions (Setup)

1. Create one IP address pool (`pool-export-13`) in the subnet `100.65.170.0/24`, scoped to the account `ExportTest13`.
2. Create **sim_a** — an IMSI-mode profile with two IMSIs: IMSI1 assigned IP `100.65.170.10` (unique to sim_a) and IMSI2 assigned IP `100.65.170.20` (shared with sim_b).
3. Create **sim_b** — an IMSI-APN-mode profile with one IMSI (IMSI3) configured for two APNs: APN1 mapped to IP `100.65.170.30` and APN2 mapped to IP `100.65.170.20` (shared with sim_a).
4. Create **sim_card** — an ICCID-mode profile with one physical card (ICCID) and one IMSI (IMSI4), with a card-level IP of `100.65.170.40`.
5. Create **sim_term** — an IMSI-mode profile with one IMSI (IMSI5) assigned IP `100.65.170.50`. This SIM will be terminated during the tests.

## Test 13.1 — Export columns match the import format

**Goal:** Confirm that every row returned by the export API contains exactly the nine standard fields required by the bulk import format.

1. Send a request to `GET /profiles/export` filtered by account `ExportTest13`.
2. Verify the response is HTTP 200 (success) and contains at least one row.
3. Verify that every row contains exactly these nine fields: `sim_id`, `iccid`, `account_name`, `status`, `ip_resolution`, `imsi`, `apn`, `static_ip`, `pool_id`.

## Test 13.2 — Export IMSI-mode profile yields one row per IMSI

**Goal:** Confirm that sim_a, which has two IMSIs, produces two separate export rows.

1. Send a request to `GET /profiles/export` filtered by account `ExportTest13`.
2. From the results, find all rows belonging to sim_a.
3. Verify there are exactly 2 rows.
4. Verify that one row contains IMSI1 with IP `100.65.170.10` and the other contains IMSI2 with IP `100.65.170.20`.

## Test 13.3 — Export IMSI-APN-mode profile yields one row per IMSI-APN pair

**Goal:** Confirm that sim_b, which has one IMSI across two APNs, produces two separate export rows.

1. Send a request to `GET /profiles/export` filtered by account `ExportTest13`.
2. From the results, find all rows belonging to sim_b.
3. Verify there are exactly 2 rows (one per APN).
4. Verify one row has APN1 and the other has APN2.

## Test 13.4 — Export filtered by account returns only that account's SIMs

**Goal:** Confirm the account filter works and all four test SIMs appear.

1. Send a request to `GET /profiles/export?account_name=ExportTest13`.
2. Verify that every returned row belongs to the `ExportTest13` account.
3. Verify that sim_a, sim_b, sim_card, and sim_term all appear in the results.

## Test 13.5 — Export by IP filter returns only the SIM owning that unique IP

**Goal:** Confirm filtering by an IP address that belongs to only one SIM returns only that SIM's rows.

1. Send a request to `GET /profiles/export?ip=100.65.170.10` (the unique IP assigned to sim_a/IMSI1).
2. Verify the response is HTTP 200 (success) and contains at least one row.
3. Verify every row belongs to sim_a, and that the IP `100.65.170.10` appears in the results.

## Test 13.6 — Export by shared IP returns both SIMs that hold it

**Goal:** Confirm filtering by an IP shared between two SIMs returns rows from both.

1. Send a request to `GET /profiles/export?ip=100.65.170.20` (the IP shared by sim_a/IMSI2 and sim_b/IMSI3/APN2).
2. Verify the response is HTTP 200 (success).
3. Verify that rows from both sim_a and sim_b appear in the results.

## Test 13.7 — List profiles by unique IP returns exactly one SIM

**Goal:** Confirm `GET /profiles?ip=` returns a single SIM when the IP belongs to only one profile.

1. Send a request to `GET /profiles?ip=100.65.170.10`.
2. Verify the response is HTTP 200 (success) with `total = 1`.
3. Verify the one returned SIM is sim_a.

## Test 13.8 — List profiles by shared IP returns multiple SIMs

**Goal:** Confirm `GET /profiles?ip=` returns all SIMs that own a shared IP.

1. Send a request to `GET /profiles?ip=100.65.170.20`.
2. Verify the response is HTTP 200 (success) with `total >= 2`.
3. Verify that both sim_a and sim_b appear in the results.

## Test 13.9 — List profiles by card-level IP finds the ICCID-mode SIM

**Goal:** Confirm IP search also works for IPs stored in the card-level IP table (`sim_apn_ips`).

1. Send a request to `GET /profiles?ip=100.65.170.40` (sim_card's card-level IP).
2. Verify the response is HTTP 200 (success).
3. Verify sim_card appears in the results.

## Test 13.10 — List profiles by non-existent IP returns zero results

**Goal:** Confirm that searching for an IP not assigned to any SIM returns an empty result set.

1. Send a request to `GET /profiles?ip=1.2.3.4`.
2. Verify the response is HTTP 200 (success) with `total = 0`.

## Test 13.11 — Fetching a terminated SIM returns success, not "not found"

**Goal:** Confirm that deleting a SIM marks it as `terminated` rather than removing it, and that `GET /profiles/{id}` still returns it.

1. Send a `DELETE /profiles/{sim_term_id}` request.
2. Verify the response is HTTP 204 (no content / success).
3. Send a `GET /profiles/{sim_term_id}` request.
4. Verify the response is HTTP 200 (success) — not HTTP 404 (not found).
5. Verify the returned profile has `status = "terminated"`.
6. Verify the `imsis` list is empty (IMSIs are removed on termination).

## Test 13.12 — Listing all profiles includes terminated SIMs when no status filter is applied

**Goal:** Confirm the profile list no longer silently excludes terminated SIMs by default.

1. Send a request to `GET /profiles?account_name=ExportTest13&limit=100` (no status filter).
2. Verify the response is HTTP 200 (success).
3. Verify sim_term appears in the results despite being terminated.

## Test 13.13 — List with status filter "terminated" returns only terminated profiles

**Goal:** Confirm that filtering by `status=terminated` returns only terminated SIMs.

1. Send a request to `GET /profiles?status=terminated&account_name=ExportTest13&limit=100`.
2. Verify the response is HTTP 200 (success).
3. Verify every item in the results has `status = "terminated"`.
4. Verify sim_term is present.

## Test 13.14 — List profiles by IMSI prefix returns matching SIMs

**Goal:** Confirm that `GET /profiles?imsi_prefix=` filters profiles by IMSI prefix.

1. Send a request to `GET /profiles?imsi_prefix=2787713&limit=50` (the shared prefix for all test-13 IMSIs).
2. Verify the response is HTTP 200 (success).
3. Verify sim_a, sim_b, and sim_card all appear.
4. Verify sim_term does not appear (its IMSIs were removed on termination).
5. Verify no SIMs outside the test-13 set appear.

## Test 13.15 — Export filtered by IMSI prefix returns matching rows only

**Goal:** Confirm the export API also supports IMSI prefix filtering.

1. Send a request to `GET /profiles/export?imsi_prefix=2787713`.
2. Verify the response is HTTP 200 (success) with at least one row.
3. Verify every row's IMSI either starts with the prefix `2787713` or is null.

## Test 13.16 — List profiles by ICCID prefix returns the ICCID-mode SIM only

**Goal:** Confirm that `GET /profiles?iccid_prefix=` filters to SIMs that have a matching ICCID.

1. Send a request to `GET /profiles?iccid_prefix=894450113&limit=50`.
2. Verify the response is HTTP 200 (success).
3. Verify sim_card appears in the results.
4. Verify sim_a and sim_b do not appear (they have no ICCID).

## Test 13.17 — Export filtered by ICCID prefix returns ICCID-mode SIM only

**Goal:** Confirm the export API also supports ICCID prefix filtering.

1. Send a request to `GET /profiles/export?iccid_prefix=894450113`.
2. Verify the response is HTTP 200 (success) with at least one row.
3. Verify sim_card appears; verify sim_a and sim_b do not appear.

## Test 13.18 — List profiles by account name returns all SIMs for that account

**Goal:** Confirm that `GET /profiles?account_name=` returns all SIMs for the account, including terminated ones.

1. Send a request to `GET /profiles?account_name=ExportTest13&limit=100`.
2. Verify the response is HTTP 200 (success).
3. Verify every returned SIM belongs to account `ExportTest13`.
4. Verify all four SIMs (sim_a, sim_b, sim_card, sim_term) appear.

## Test 13.19 — Export with status=active excludes terminated SIMs

**Goal:** Confirm that filtering the export by `status=active` removes terminated SIMs from the output.

1. Send a request to `GET /profiles/export?status=active&account_name=ExportTest13`.
2. Verify the response is HTTP 200 (success).
3. Verify sim_a, sim_b, and sim_card all appear.
4. Verify sim_term does NOT appear.

## Post-conditions (Teardown)

1. Delete the profiles for sim_a, sim_b, sim_card, and sim_term (handles already-terminated SIMs gracefully).
2. Delete the `pool-export-13` IP address pool.
