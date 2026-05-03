# Test Suite 22 — `ip_resolution` Conversion Safety on `sim_profiles`

## What this test suite validates

Changing `sim_profiles.ip_resolution` after the profile has IP rows is a high-risk operation: the C++ fast-path resolver dispatches on this column and only matches rows whose shape fits the new mode (`imsi`/`iccid` look for `apn IS NULL`; `imsi_apn`/`iccid_apn` look for an exact APN with NULL fallback). Rows from the previous mode that don't fit silently become orphans — the resolver walks past them and returns `NotFound` for live subscribers.

This suite verifies the API guard added to `PATCH /profiles/{sim_id}`:

- A change that would orphan rows is **rejected** with HTTP 409 `mode_conversion_orphans_rows` (and the existing state is left untouched).
- The same change with `?force=true` **succeeds** and deletes the orphan rows in the same transaction as the `UPDATE sim_profiles` so the resolver invariant holds across the change.
- Same-table additive transitions (`imsi → imsi_apn` when only a NULL row exists) and same-value PATCHes are **accepted without `?force=true`** because they do not orphan anything.

## Pre-conditions (Setup)

Each scenario class creates its own pool (a `/24` inside the module-26 block, `100.66.48.0/22`) and provisions a fresh profile in the relevant starting mode. Profiles are cleaned up in `teardown_class`.

---

## Scenario A — `imsi_apn → imsi` (the canonical bad transition)

**Setup:** A profile with two IMSIs, each with two specific-APN rows (`internet`, `ims`) and no wildcard. Four `imsi_apn_ips` rows total.

### Test 22.A.1 — Provision the imsi_apn profile

Create the profile via `POST /profiles` with `ip_resolution="imsi_apn"`; expect HTTP 201.

### Test 22.A.2 — Baseline lookup returns the exact-APN IP

`GET /lookup?imsi=…&apn=internet.operator.com` → HTTP 200 with the `internet` IP.

### Test 22.A.3 — Unforced change to `imsi` is rejected

1. Send `PATCH /profiles/{sim_id}` with body `{"ip_resolution": "imsi"}` (no `?force=true`).
2. Verify HTTP 409.
3. Verify the response body contains `error="mode_conversion_orphans_rows"`, `from="imsi_apn"`, `to="imsi"`, and `orphaned_count=4` (the four specific-APN rows).

### Test 22.A.4 — Lookup state is unchanged after the rejected change

The 409 must have been a no-op transactionally. Lookup again and verify the original IP is still returned.

### Test 22.A.5 — Forced change deletes orphans

`PATCH /profiles/{sim_id}?force=true` with body `{"ip_resolution": "imsi"}` → HTTP 200. Re-fetch the profile; verify `ip_resolution="imsi"`.

### Test 22.A.6 — Lookup post-conversion never returns a stale IP

After the forced conversion the resolver runs in `imsi` mode and looks for `apn IS NULL`. The test accepts either:

- HTTP 404 (no rows in `imsi_apn_ips` for this IMSI — clean, predictable miss), or
- HTTP 200 with a freshly-allocated IP from first-connection.

What MUST NOT happen is returning one of the deleted per-APN IPs. The test asserts the returned IP (if any) is not in the original set — proving the resolver invariant is now sound.

---

## Scenario B — `imsi_apn → imsi` with a wildcard row already present

**Setup:** One IMSI with one specific-APN row (`internet`) **and** one wildcard row (`apn IS NULL`).

### Test 22.B.1 — Provision the profile

### Test 22.B.2 — Unforced change is still rejected

The specific-APN row is still an orphan. PATCH without `?force=true` → 409 with `orphaned_count=1` (only the per-APN row, not the wildcard).

### Test 22.B.3 — Forced change keeps the wildcard, lookup keeps working

After `?force=true`:

- `GET /lookup` for any APN returns the wildcard IP — proving the wildcard row was preserved while the orphan was deleted.

---

## Scenario C — `iccid_apn → iccid` (same shape on `sim_apn_ips`)

**Setup:** A 2-IMSI card profile with two card-level per-APN rows (`internet`, `ims`).

### Test 22.C.1 — Provision the iccid_apn profile

### Test 22.C.2 — Unforced change to `iccid` is rejected

PATCH → 409 with `from="iccid_apn"`, `to="iccid"`, `orphaned_count=2`.

### Test 22.C.3 — Forced change clears the per-APN rows

PATCH `?force=true` → 200; profile now in `iccid` mode.

---

## Scenario D — Cross-table conversion `imsi_apn → iccid_apn`

**Setup:** One IMSI with two per-APN rows in `imsi_apn_ips`.

### Test 22.D.1 — Provision the imsi_apn profile

### Test 22.D.2 — Unforced cross-table change is rejected

The new resolver reads `sim_apn_ips`, so every row in the previous table (`imsi_apn_ips`) becomes an orphan. PATCH without `?force=true` → 409 with `orphaned_count=2` (every row, not just specific-APN ones — cross-table is total).

### Test 22.D.3 — Forced change wipes the previous table for this sim

PATCH `?force=true` → 200; profile flipped to `iccid_apn`. The orphan rows in `imsi_apn_ips` for this sim's IMSIs are gone.

---

## Scenario E — Same-value and additive transitions don't trigger the guard

**Setup:** A profile created with `ip_resolution="imsi_apn"` containing only a wildcard row (the `imsi`-shaped data inside an `imsi_apn` profile).

### Test 22.E.1 — Provision the profile

### Test 22.E.2 — `imsi_apn → imsi` with only a wildcard requires no force

Because the only existing row already has `apn IS NULL`, nothing is orphaned. PATCH without `?force=true` → HTTP 200.

### Test 22.E.3 — Same-value PATCH is a no-op

A second PATCH with the same `ip_resolution="imsi"` value → HTTP 200, guard does not fire.

---

## Post-conditions (Teardown)

Each class soft-deletes its profile and deletes its pool. The auto-bucket `conftest` hook tags every test in this file with both the `fastpath` and `api` markers so it is included in `pytest -m fastpath` runs.
