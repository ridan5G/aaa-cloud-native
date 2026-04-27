# Test Suite 12 — Grafana Dashboard Metric Validation

## What this test suite validates

This suite verifies that every Prometheus metric powering the platform's Grafana "Platform Overview" dashboard is actually emitted by the services and increments correctly in response to real operations. It covers six Grafana panel categories: first-connection success/failure rates, lookup database error counters, in-flight request gauges, database transaction rollback counters, per-pool exhaustion event counters (with label isolation), and bulk job outcome counters. The tests work by reading the `/metrics` endpoint before and after triggering specific operations, then confirming the relevant counter or gauge changed as expected.

**Metrics endpoints used:**
- Provisioning API metrics: `http://localhost:9091/metrics` (configurable via `METRICS_URL`)
- Lookup service metrics: `http://localhost:9090/metrics` (configurable via `LOOKUP_METRICS_URL`)

If either metrics endpoint is unreachable, the tests that depend on it are automatically skipped.

## Pre-conditions (Setup)

Two small IP pools are created as module-level fixtures and reused across test classes:

1. **Pool A** (`100.65.99.0/30`): a /30 subnet with only 1 usable IP. Used for first-connection, rollback, and per-pool label tests. Any stale profiles in its IMSI range are cleared before creation.
2. **Pool B** (`100.65.98.0/30`): a second /30 subnet with only 1 usable IP. Used exclusively for the per-pool label isolation tests.

Both pools are wired to their own IMSI range configurations.

---

## Test 12.1 — Successful first-connection increments the `allocated` counter

**Goal:** When a first-connection succeeds (HTTP 201), the `first_connection_total{result="allocated"}` counter on the provisioning API must increase by at least 1.

1. Read the current value of `first_connection_total{result="allocated"}` from the metrics endpoint.
2. Send a first-connection request for an IMSI in Pool A's range.
3. Confirm the response is HTTP 201 (new allocation).
4. Read the metric again and confirm it increased by at least 1.

---

## Test 12.2 — Pool exhaustion (HTTP 503) increments the `pool_exhausted` counter

**Goal:** When a first-connection attempt fails because no IPs remain (HTTP 503), the `first_connection_total{result="pool_exhausted"}` counter must increase.

1. Ensure Pool A is fully exhausted (drain any remaining IPs by sending additional first-connection requests until the pool is empty).
2. Read the current value of `first_connection_total{result="pool_exhausted"}`.
3. Send a first-connection request for an IMSI that maps to the now-exhausted Pool A.
4. Confirm the response is HTTP 503 (service unavailable) with `"error": "pool_exhausted"`.
5. Read the metric again and confirm it increased by at least 1.

---

## Test 12.3 — Successful lookup increments the `resolved` counter on the lookup service

**Goal:** A successful GET /lookup for a provisioned IMSI increments `aaa_lookup_requests_total{result="resolved"}` on the lookup service's metrics endpoint.

1. Read the current value of `aaa_lookup_requests_total{result="resolved"}` from the lookup service metrics.
2. Send a lookup request for the IMSI provisioned in test 12.1.
3. If the response is HTTP 200 (resolved), confirm the metric increased by at least 1.
4. (A HTTP 404 response is also acceptable if the lookup service's cache has not yet been updated; in that case the metric check is noted but not failed.)

---

## Test 12.4 — The `aaa_db_errors_total` counter is present in the lookup service metrics

**Goal:** The lookup service must declare and expose the `aaa_db_errors_total` metric, even if its value is zero, so the Grafana "DB Error Rate" panel has a live data series.

1. Retrieve the full text from the lookup service metrics endpoint.
2. Confirm the string `aaa_db_errors_total` appears anywhere in the output.

---

## Test 12.5 — The `aaa_lookup_requests_total` metric family is present in the lookup service metrics

**Goal:** The `aaa_lookup_requests_total` metric family (which includes the `result="db_error"` label) must be present in the lookup service metrics output so the Grafana "Lookup DB Errors" panel has a live series.

1. Retrieve the full text from the lookup service metrics endpoint.
2. Confirm the string `aaa_lookup_requests_total` appears anywhere in the output.

---

## Test 12.6 — In-flight request gauge returns to zero after concurrent requests complete

**Goal:** The `http_requests_in_flight` gauge on the provisioning API must be properly decremented after every request finishes, so it reaches zero once all concurrent requests have completed.

1. Launch 10 concurrent requests to the provisioning API (listing pools).
2. Wait for all 10 to finish.
3. Confirm no requests raised exceptions.
4. Read the metrics endpoint and sum all `http_requests_in_flight` values across all endpoint labels.
5. Confirm the total is 0.0.

---

## Test 12.7 — In-flight gauge rises above zero during concurrent load

**Goal:** Under concurrent load, the `http_requests_in_flight` gauge must actually go above zero at some point — confirming the gauge is being incremented on request start and not just decremented.

1. Launch 20 concurrent requests to the provisioning API.
2. While the requests are running, repeatedly poll the metrics endpoint and check whether `http_requests_in_flight` is above zero.
3. Wait for all 20 requests to complete.
4. Read the metrics endpoint one final time and confirm the gauge is back to 0.0 (hard requirement).
5. If the gauge was never observed above zero during polling, emit a warning (this can happen if the metrics poll was slower than the requests themselves — it is not treated as a hard failure).

---

## Test 12.8 — The lookup service's `aaa_in_flight_requests` metric is present

**Goal:** The lookup service must declare `aaa_in_flight_requests` so the Grafana "In-Flight Requests" panel has a live series.

1. Retrieve the full text from the lookup service metrics endpoint.
2. Confirm the string `aaa_in_flight_requests` appears in the output.

---

## Test 12.9 — Pool exhaustion (HTTP 503) increments the `db_rollbacks_total` rollback counter

**Goal:** When a first-connection attempt hits an exhausted pool and the transaction is rolled back, `db_rollbacks_total{reason="pool_exhausted"}` must increase.

1. (Pool A is already exhausted from earlier tests in this class.)
2. Read the current value of `db_rollbacks_total{reason="pool_exhausted"}`.
3. Send another first-connection request to Pool A's IMSI range — confirm HTTP 503.
4. Read the metric again and confirm it increased by at least 1.

---

## Test 12.10 — Successful read operations do not increment the rollback counter

**Goal:** Normal successful operations must not accidentally trigger rollback counter increments — the counter must only move when an actual database rollback occurs.

1. Read the current value of `db_rollbacks_total{reason="pool_exhausted"}`.
2. Send a successful GET /pools request.
3. Confirm HTTP 200.
4. Read the metric again and confirm it did not change (delta = 0).

---

## Test 12.11 — Pool A exhaustion increments the `pool_exhausted_total` counter with Pool A's label

**Goal:** The `pool_exhausted_total{pool_id=<pool_a_id>}` counter must increment when Pool A is exhausted — confirming the per-pool label is applied correctly.

1. Read the current value of `pool_exhausted_total{pool_id=<pool_a_id>}`.
2. Send a first-connection request that maps to Pool A's (already exhausted) range — confirm HTTP 503.
3. Read the metric again and confirm it increased by at least 1 for Pool A's pool_id label.

---

## Test 12.12 — Pool B exhaustion increments Pool B's counter

**Goal:** Pool B's counter increments independently when Pool B is exhausted, confirming per-pool label isolation.

1. Send a first-connection request for an IMSI in Pool B's range — confirm HTTP 201 (Pool B's one IP is allocated).
2. Read the current value of `pool_exhausted_total{pool_id=<pool_b_id>}`.
3. Send another first-connection for Pool B's range (now exhausted) — confirm HTTP 503.
4. Confirm Pool B's counter increased by at least 1.

---

## Test 12.13 — Exhausting Pool B does not change Pool A's counter

**Goal:** The per-pool label must isolate the time series; an exhaustion event in Pool B must not increment Pool A's counter.

1. Read the current value of `pool_exhausted_total{pool_id=<pool_a_id>}`.
2. Send another first-connection that maps to Pool B's exhausted range — confirm HTTP 503.
3. Read Pool A's counter again.
4. Confirm Pool A's counter did not change (delta = 0).

---

## Test 12.14 — Successful bulk job increments the `processed` outcome counter

**Goal:** When a bulk import job completes successfully, `bulk_job_profiles_total{outcome="processed"}` must increase by at least the number of profiles submitted.

1. Read the current value of `bulk_job_profiles_total{outcome="processed"}`.
2. Submit a bulk import job containing 5 valid subscriber profiles.
3. Confirm HTTP 202 (accepted) and record the job ID.
4. Poll the job to completion — confirm status = `completed` and at least 5 rows processed.
5. Read the metric again and confirm it increased by at least 5.

---

## Test 12.15 — A bulk job with invalid entries increments the `failed` outcome counter

**Goal:** When a bulk import job contains rows with invalid IMSIs, `bulk_job_profiles_total{outcome="failed"}` must increment for each bad row.

1. Read the current value of `bulk_job_profiles_total{outcome="failed"}`.
2. Submit a bulk import job with a mix of 3 valid profiles and 2 intentionally invalid profiles (IMSI = `"BADIMSI"` and `"123"` — neither is 15 digits).
3. Confirm HTTP 202 and record the job ID.
4. Poll the job to completion — confirm at least 2 rows failed.
5. Read the metric again and confirm it increased by at least 2.

---

## Post-conditions (Teardown)

1. Pool A's range configuration is deleted.
2. Any IPs in Pool A are cleared.
3. Pool A is deleted.
4. Pool B's range configuration is deleted.
5. Any IPs in Pool B are cleared.
6. Pool B is deleted.
