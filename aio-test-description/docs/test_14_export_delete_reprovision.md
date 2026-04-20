# Test Suite 14 — Export, Delete, and Reprovision

## What this test suite validates

This suite verifies the full export-delete-reprovision lifecycle for all four SIM profile types: `iccid` (card-level IP), `imsi` (per-IMSI APN-agnostic IP), `imsi_apn` (per-IMSI per-APN IP), and `iccid_apn` (card-level per-APN IP). For each type, the suite exports existing profiles via the CSV export API, deletes them, re-imports them via the bulk provisioning API, and then confirms the re-created profiles are active and return the correct IPs from the lookup service.

## Pre-conditions (Setup)

Each of the four test groups (A–D) performs its own independent setup:

**Group A — iccid type (subnet 100.65.184.0/24)**
1. Clean up any profiles left from a previous interrupted run.
2. Create a pool named `pool-14-iccid` in subnet `100.65.184.0/24`.
3. Create 4 SIM profiles, each with one ICCID, two IMSIs, and one card-level static IP.

**Group B — imsi type (subnet 100.65.185.0/24)**
1. Clean up any stale profiles.
2. Create a pool named `pool-14-imsi` in subnet `100.65.185.0/24`.
3. Create 4 SIM profiles, each with two IMSIs and a separate static IP per IMSI.

**Group C — imsi_apn type (subnet 100.65.186.0/24)**
1. Clean up any stale profiles.
2. Create a pool named `pool-14-imsi-apn` in subnet `100.65.186.0/24`.
3. Create 4 SIM profiles, each with two IMSIs and two APNs per IMSI (total 4 IP entries per SIM).

**Group D — iccid_apn type (subnet 100.65.187.0/24)**
1. Clean up any stale profiles.
2. Create a pool named `pool-14-iccid-apn` in subnet `100.65.187.0/24`.
3. Create 4 SIM profiles, each with one ICCID, two IMSIs, and two card-level APN IPs.

---

## Test 14.1 — Export confirms all SIMs are present (one row per IP entry)

**Goal:** Verify the export API returns all provisioned SIMs with non-null IP values, in the correct flat row structure for the given profile type.

**iccid type:**
1. Send a request to `GET /profiles/export?account_name=ExportDeleteReprovision14&ip_resolution=iccid`.
2. Verify the response is HTTP 200 (success) and contains rows.
3. Verify all 4 SIM IDs appear in the results.
4. Verify every row has a non-null `static_ip` (this validates an earlier export bug fix for card-level IPs).
5. Save these rows for use in the reprovision step.

**imsi type:**
1. Send a request to `GET /profiles/export?account_name=ExportDeleteReprovision14&ip_resolution=imsi`.
2. Verify all 4 SIM IDs appear.
3. Verify there are exactly 8 rows total (4 SIMs × 2 IMSIs each).
4. Verify every row has a non-null `static_ip`.

**imsi_apn type:**
1. Send a request to `GET /profiles/export?account_name=ExportDeleteReprovision14&ip_resolution=imsi_apn`.
2. Verify all 4 SIM IDs appear.
3. Verify there are exactly 16 rows (4 SIMs × 2 IMSIs × 2 APNs).
4. Verify every row has a non-null `static_ip`.

**iccid_apn type:**
1. Send a request to `GET /profiles/export?account_name=ExportDeleteReprovision14&ip_resolution=iccid_apn`.
2. Verify all 4 SIM IDs appear.
3. Verify there are exactly 16 rows (4 SIMs × 2 IMSIs × 2 APNs).
4. Verify every row has a non-null `static_ip`.

---

## Test 14.2 — Delete all SIMs and confirm termination

**Goal:** Verify that deleting each SIM succeeds and leaves the profile in a terminated state (not removed).

1. For each of the 4 SIM profiles, send a `DELETE /profiles/{sim_id}` request.
2. Verify each deletion returns HTTP 204 (no content / success).
3. For each SIM, send a `GET /profiles/{sim_id}` request.
4. Verify each returns HTTP 200 (success) with `status = "terminated"`.

---

## Test 14.3 — Reprovision via bulk import and confirm job completes

**Goal:** Convert the exported flat rows back into the nested bulk import format and confirm the bulk job completes with zero failures.

1. Convert the saved export rows into the bulk import JSON format (grouping rows back by SIM, IMSI, and APN as appropriate for the profile type).
2. Verify the converted payload contains exactly 4 profiles.
3. Send a request to `POST /profiles/bulk` with the payload.
4. Verify the response is HTTP 202 (accepted) and contains a `job_id`.
5. Repeatedly check `GET /jobs/{job_id}` until the job reaches a terminal status (up to 5 minutes).
6. Verify the job status is `completed`.
7. Verify `failed = 0` and `processed = 4`.

---

## Test 14.4 — Verify reprovisioned profiles are active and lookup returns correct IPs

**Goal:** Confirm the re-created profiles are active and the lookup service returns the originally assigned IPs.

1. For each re-provisioned IMSI, send a request to `GET /profiles?imsi={imsi}`.
2. Verify the response is HTTP 200 (success) and at least one profile with `status = "active"` is returned.
3. For each IMSI (and APN, where applicable), send a request to the lookup service at `GET /lookup?imsi={imsi}&apn={apn}&use_case_id=...`.
4. Verify the lookup returns HTTP 200 (success).
5. Verify the returned `static_ip` matches the originally assigned IP from before deletion.

---

## Post-conditions (Teardown)

Each group independently cleans up its own resources:

1. Delete all 4 re-provisioned SIM profiles.
2. Delete the IP address pool created for that group.
