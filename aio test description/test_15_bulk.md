# Test Suite 15 — Bulk Profile Import

## What this test suite validates

This suite verifies the bulk profile provisioning API (`POST /profiles/bulk`), which allows importing large numbers of SIM profiles in a single asynchronous request. It covers submitting 1,500 profiles in one request, polling the resulting background job to completion, spot-checking randomly sampled results via both the profile API and the lookup service, handling mixed valid/invalid entries in a batch, verifying that re-submitting the same profile updates it rather than duplicating it (upsert behaviour), and uploading profiles via a CSV file attachment instead of JSON.

## Pre-conditions (Setup)

1. Create three separate IP address pools:
   - `bulk-pool-a` in subnet `100.65.200.0/22` (for 500 ICCID-mode profiles).
   - `bulk-pool-b` in subnet `100.65.204.0/22` (for 500 IMSI-mode profiles).
   - `bulk-pool-c` in subnet `100.65.208.0/22` (for 500 IMSI-APN-mode profiles).
2. All three pools are scoped to the account `TestAccount` with routing domain `bulk-test-08`.

## Test 15.1 — Submit 1,500 profiles in one bulk request

**Goal:** Confirm the bulk API accepts a large payload and immediately returns a job ID for asynchronous processing.

1. Build a list of 1,500 profile records:
   - 500 ICCID-mode profiles (each with 1 ICCID, 2 IMSIs, 1 card-level IP from pool-a).
   - 500 IMSI-mode profiles (each with 1 IMSI and its own IP from pool-b).
   - 500 IMSI-APN-mode profiles (each with 1 IMSI, 2 APNs, and a distinct IP per APN from pool-c).
2. Save 5 random samples from the ICCID-mode group and 5 from the IMSI-APN-mode group for later spot-checks.
3. Send a request to `POST /profiles/bulk` with all 1,500 profiles.
4. Verify the response is HTTP 202 (accepted) and contains a `job_id`.

## Test 15.2 — Poll the bulk job until it completes successfully

**Goal:** Confirm the background job processes all 1,500 profiles without any failures (allowed up to 10 minutes).

1. Repeatedly send a request to `GET /jobs/{job_id}` every 10 seconds until the job status is either `completed` or `failed`.
2. Verify the final status is `completed`.
3. Verify `processed = 1500`.
4. Verify `failed = 0`.

## Test 15.3 — Spot-check profiles via the provisioning API

**Goal:** Confirm that a random sample of the imported profiles can be retrieved and have the correct IP resolution type.

1. For each of the 5 sampled ICCID-mode profiles, send a request to `GET /profiles?iccid={iccid}`.
2. Verify the response is HTTP 200 (success) and at least one profile is found.
3. Verify the profile's `ip_resolution` is `"iccid"`.
4. For each of the 5 sampled IMSI-APN-mode profiles, send a request to `GET /profiles?imsi={imsi}`.
5. Verify the response is HTTP 200 (success) and at least one profile is found.
6. Verify the profile's `ip_resolution` is `"imsi_apn"`.

## Test 15.4 — Spot-check IP lookup for a sample of the imported profiles

**Goal:** Confirm the lookup service returns the correct pre-assigned IP for a random sample of the imported IMSI-APN-mode profiles.

1. For each of the 5 sampled IMSI-APN-mode profiles, send a request to `GET /lookup?imsi={imsi}&apn={apn}&use_case_id=...` using the first APN from that profile.
2. Verify the lookup returns HTTP 200 (success).
3. Verify the returned `static_ip` matches the IP that was submitted in the bulk payload for that IMSI and APN.

## Test 15.5 — Bulk request with one invalid entry processes the valid entry and records the failure

**Goal:** Confirm that a single invalid record in a batch does not prevent the rest from being processed — only that record fails.

1. Build a payload with 2 profiles:
   - One valid IMSI-mode profile with a correctly formatted 15-digit IMSI.
   - One invalid IMSI-mode profile with a 5-digit IMSI (too short — fails validation).
2. Send a request to `POST /profiles/bulk` with this payload.
3. Verify the response is HTTP 202 (accepted).
4. Poll `GET /jobs/{job_id}` until the job completes.
5. Verify the job status is `completed`.
6. Verify `processed = 1` (the valid profile succeeded).
7. Verify `failed = 1` (the invalid profile was rejected).

## Test 15.6 — Job error details include a field-level description for invalid records

**Goal:** Confirm that the errors array in the job response identifies which field caused a failure.

1. Send a request to `POST /profiles/bulk` with a single profile containing a 5-digit IMSI.
2. Verify the response is HTTP 202 (accepted).
3. Poll `GET /jobs/{job_id}` until the job completes.
4. Retrieve the `errors` array from the job response.
5. Verify at least one error entry is present.
6. Verify the error entry's `field` value is `"imsi"` or `"imsis"`, indicating the problem field was identified.

## Test 15.7 — Submitting the same profile twice updates it rather than creating a duplicate

**Goal:** Confirm that bulk upload is an upsert operation — re-importing a profile with a new IP replaces the old IP rather than creating a second profile.

1. Send a request to `POST /profiles/bulk` with a single IMSI-mode profile using IP version 1.
2. Poll `GET /jobs/{job_id_1}` until the job completes.
3. Send a second request to `POST /profiles/bulk` with the same IMSI but a different IP (version 2).
4. Poll `GET /jobs/{job_id_2}` until the job completes.
5. Send a request to `GET /profiles?imsi={imsi}`.
6. Verify the response contains exactly 1 profile (not 2) — confirming no duplicate was created.

## Test 15.8 — Bulk upload via CSV file produces the same result as JSON

**Goal:** Confirm that profiles can also be imported by uploading a CSV file rather than sending JSON in the request body.

1. Build a small CSV file with 3 rows: one ICCID-mode profile, one IMSI-mode profile, and one IMSI-APN-mode profile.
2. Send a `POST /profiles/bulk` request with the CSV file as a multipart form-data attachment.
3. Verify the response is HTTP 202 (accepted) and contains a `job_id`.
4. Poll `GET /jobs/{job_id}` until the job reaches a terminal status.
5. Verify the job status is `completed`.
6. Verify `failed = 0`.

## Post-conditions (Teardown)

1. Force-clear all IP allocations from all three pools.
2. Delete the three pools (`bulk-pool-a`, `bulk-pool-b`, `bulk-pool-c`).
