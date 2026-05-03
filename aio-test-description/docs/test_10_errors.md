# Test Suite 10 — API Error Handling: Validation, Conflicts, and Authentication

## What this test suite validates

This suite systematically verifies that the platform's APIs reject bad input with the correct HTTP status codes and informative error messages. It covers input validation errors (malformed IMSI/ICCID, missing required fields), duplicate data conflicts (reusing an IMSI or ICCID already assigned to another profile), resource-not-found errors, invalid state transitions, and authentication failures. It also verifies a handful of positive behaviors that could be mishandled: updating a profile's IP resolution mode, and confirming that the `use_case_id` parameter is truly optional for both the lookup and first-connection APIs.

## Pre-conditions (Setup)

1. A shared IP pool is created: subnet `100.65.200.0/24`.
2. A "conflict profile" is created using test IMSI #1 and ICCID #1, with static IP `100.65.200.1`. This profile is used to trigger IMSI and ICCID conflict errors in later tests.
3. A "second profile" is created using test IMSI #2, with static IP `100.65.200.2`. This profile is used for the ICCID-on-PATCH conflict test.
4. A "main profile" is created using test IMSI #10, with static IP `100.65.200.10`. This profile is used for suspend/reactivate and IP-resolution-mode-change tests.

---

## Test 10.1 — Create profile with a 14-digit IMSI → HTTP 400 (validation error)

**Goal:** An IMSI that is too short (14 digits instead of the required 15) must be rejected immediately.

1. Send a create-profile request containing an IMSI with 14 digits.
2. Confirm the response is HTTP 400 (bad request).
3. Confirm the error body references the `imsi` field.

---

## Test 10.2 — Create profile with a 10-digit ICCID → HTTP 400 (validation error)

**Goal:** An ICCID that is far too short (10 digits) must be rejected.

1. Send a create-profile request with an ICCID that has only 10 digits.
2. Confirm the response is HTTP 400 (bad request).
3. Confirm the error body references the `iccid` field.

---

## Test 10.3 — Create profile with no `ip_resolution` field → HTTP 400 (validation error)

**Goal:** The `ip_resolution` field is mandatory; omitting it must produce a validation error.

1. Send a create-profile request without the `ip_resolution` field.
2. Confirm the response is HTTP 400 (bad request).

---

## Test 10.4 — Create profile with an invalid `ip_resolution` value → HTTP 400 (validation error)

**Goal:** Only specific known values are accepted for `ip_resolution`; an unrecognized string must be rejected.

1. Send a create-profile request with `ip_resolution` set to an arbitrary invalid string (e.g., `"bogus_value"`).
2. Confirm the response is HTTP 400 (bad request).

---

## Test 10.5 — Create profile with a duplicate ICCID → HTTP 409 (conflict)

**Goal:** An ICCID that is already assigned to an existing profile must not be reused.

1. Send a create-profile request using the same ICCID as the conflict profile created in setup.
2. Confirm the response is HTTP 409 (conflict).
3. Confirm the error body contains `"error": "iccid_conflict"` or `"conflict"`.

---

## Test 10.6 — Create profile with a duplicate IMSI → HTTP 409 (conflict)

**Goal:** An IMSI that is already registered on an existing profile must not be assigned to a second profile.

1. Send a create-profile request using the same IMSI as the conflict profile.
2. Confirm the response is HTTP 409 (conflict).
3. Confirm the error body contains `"error": "imsi_conflict"` or `"conflict"`.

---

## Test 10.7 — Retrieve a non-existent profile → HTTP 404 (not found)

**Goal:** Requesting a profile with an unknown UUID returns a clear "not found" response.

1. Send a get-profile request using a made-up UUID that does not exist in the system.
2. Confirm the response is HTTP 404 (not found).

---

## Test 10.8 — Delete a non-existent profile → HTTP 404 (not found)

**Goal:** Attempting to delete a profile that does not exist must return "not found", not an error crash.

1. Send a delete-profile request using a made-up UUID.
2. Confirm the response is HTTP 404 (not found).

---

## Test 10.9 — Update a profile's ICCID to one already used by another profile → HTTP 409 (conflict)

**Goal:** A PATCH operation that would assign a conflict-causing ICCID to a different profile must be rejected.

1. Send an update request for the "second profile," setting its ICCID to the ICCID already owned by the "conflict profile."
2. Confirm the response is HTTP 409 (conflict).

---

## Test 10.10 — Suspend a profile; lookup returns HTTP 403 (forbidden/suspended)

**Goal:** After setting a subscriber's status to `suspended`, any lookup for that subscriber must be blocked.

1. Send an update request setting the "main profile" status to `suspended`.
2. Confirm HTTP 200 (update succeeded).
3. Send a lookup request for the main profile's IMSI.
4. Confirm HTTP 403 (forbidden) with `"error": "suspended"`.
5. Send an update to reactivate the profile (status = `active`) so subsequent tests can use it.

---

## Test 10.11 — Switch IP resolution mode `imsi → imsi_apn` is a safe transition → HTTP 200

**Goal:** Changing a profile's IP resolution mode from `imsi` to `imsi_apn` requires no force flag and no extra APN data — the existing `apn IS NULL` row becomes the `imsi_apn` wildcard fallback.

1. Send a PATCH request for the main profile changing `ip_resolution` to `imsi_apn` (no other fields).
2. Confirm the response is HTTP 200.

This test guards against regression of the orphan-row guard added to `PATCH /profiles/{sim_id}`: same-table additive transitions don't strand any rows, so they must not require `?force=true`. The previous over-cautious "switching to imsi_apn requires existing APN-specific entries" check was incorrect and is replaced by the new guard. See [test_22_resolution_method_conversion.md](test_22_resolution_method_conversion.md) for the full conversion-safety contract.

---

## Test 10.12 — Switch IP resolution mode to `iccid` (cross-table) requires `?force=true` → HTTP 409 then HTTP 200

**Goal:** Changing the resolution mode to a different table family (`imsi*` ↔ `iccid*`) is a cross-table change that orphans every row in the previous mode's table. The orphan-row guard rejects the change with 409 unless the caller passes `?force=true`, which then deletes the orphans in the same transaction as the `UPDATE sim_profiles`.

1. Send a PATCH for the main profile with body `{"ip_resolution": "iccid"}` and **no** `?force=true`.
2. Confirm HTTP 409.
3. Confirm the response body contains `"error": "mode_conversion_orphans_rows"` and `"to": "iccid"`.
4. Send a second PATCH with `?force=true` and the full mode-change payload:
   - `ip_resolution` to `iccid`
   - A new ICCID
   - A card-level IP entry (`100.65.200.11`)
5. Confirm HTTP 200 (success).
6. Send a lookup request for the main profile's IMSI.
7. Confirm HTTP 200 and `static_ip` = `100.65.200.11` (the new card-level IP). The previous `imsi`/`imsi_apn` IP row was deleted by the forced cleanup, so the resolver runs against a clean state.

---

## Test 10.13 — Lookup with missing `apn` parameter → HTTP 400 (bad request)

**Goal:** The APN is a required parameter for the lookup endpoint; omitting it must produce a validation error.

1. Send a lookup request with only the IMSI parameter and no APN.
2. Confirm HTTP 400 (bad request).

---

## Test 10.14 — Lookup with missing `imsi` parameter → HTTP 400 (bad request)

**Goal:** The IMSI is a required parameter for the lookup endpoint; omitting it must produce a validation error.

1. Send a lookup request with only the APN parameter and no IMSI.
2. Confirm HTTP 400 (bad request).

---

## Test 10.15 — Request with invalid or missing JWT → HTTP 401 (unauthorized)

**Goal:** Both the provisioning API and the lookup service must reject requests without a valid authentication token.

1. Send a request to the provisioning API (list profiles) without a valid JWT.
2. Confirm HTTP 401 (unauthorized).
3. Send a lookup request to the lookup service with an invalid JWT (`"Bearer invalid-token"`).
4. Confirm HTTP 401 (unauthorized).

---

## Test 10.16 — Lookup without `use_case_id` succeeds (parameter is optional)

**Goal:** The `use_case_id` field — which carries the 3GPP charging characteristics — must be optional. Lookups without it must still succeed.

1. Send a lookup request with only IMSI and APN, deliberately omitting `use_case_id`.
2. Confirm HTTP 200 (success).
3. Confirm the returned `static_ip` is correct (using the card-level IP set in test 10.12).

---

## Test 10.17 — First-connection and lookup both work without `use_case_id`

**Goal:** Confirms the optional nature of `use_case_id` across both the first-connection flow and the lookup, and that the presence or absence of the parameter does not change the returned IP.

1. Send a first-connection request for the main profile's IMSI without `use_case_id` — confirm success and record the IP.
2. Send a first-connection request for the same IMSI with `use_case_id` = a standard value — confirm success and the same IP.
3. Send a lookup request without `use_case_id` — confirm HTTP 200.
4. Send a lookup request with `use_case_id` — confirm HTTP 200 with the same IP.
5. Confirm all four returned IPs match the expected card-level IP.

---

## Post-conditions (Teardown)

1. The conflict profile, second profile, and main profile are all deleted.
2. The shared IP pool is deleted.
