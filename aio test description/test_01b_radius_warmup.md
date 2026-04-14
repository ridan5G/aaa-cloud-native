# Test Suite 01b — RADIUS Metrics Warmup

## What this test suite validates
This single test ensures that the RADIUS server's performance metrics (request counters and timing histograms) are populated in Prometheus from the very beginning of the test run. Without this warmup, RADIUS metrics would only start appearing in Grafana roughly 75 seconds after the lookup service metrics, making the two dashboards look misaligned even though both services started at the same time.

## Pre-conditions (Setup)
1. The RADIUS server (`aaa-radius-server`) should be reachable on the configured host and port.
2. No subscriber profiles or IP pools need to be created — the test deliberately uses an IMSI that is not provisioned in the system, so it will always trigger an Access-Reject response.
3. If the RADIUS server is unreachable, this test is automatically skipped (it does not fail the suite).

---

## Test 1b.1 — Send one RADIUS authentication packet to seed metrics

**Goal:** Trigger all RADIUS metric counters and timing histograms at least once, so they appear in Grafana dashboards from the start of the test run.

1. Send a single RADIUS Access-Request packet using IMSI `278771209999999` (an out-of-band identity guaranteed to have no matching range config) and APN `warmup.internal`.
2. The lookup service will not find a profile for this IMSI (Stage 1 — lookup returns not found), then call the first-connection endpoint which also returns not found (Stage 2), resulting in a RADIUS Access-Reject response.
3. Verify the request completes without a network error. Both an Access-Accept and an Access-Reject response are considered valid outcomes — the goal is metric generation, not authentication success.
4. If the RADIUS server is not reachable (timeout or connection error), the test is skipped automatically and does not count as a failure.

---

## Post-conditions (Teardown)
1. None. No data was created; the rejected IMSI has no profile and requires no cleanup.
