# Test Suite 18 — Lookup-Service IMSI Pre-Qualification Short-Circuit

## What this test suite validates

When the C++ lookup service's hot-path SQL returns no rows for an IMSI, it now consults a short read-replica query (`PREQUALIFY_SQL`) before falling through to the slower `subscriber-profile-api` first-connection path. If no `imsi_range_configs` row covers the IMSI with `status IN ('active','provisioned')`, the lookup short-circuits with `404 unqualified` and never calls the API. This suite verifies the contract: out-of-range IMSIs short-circuit with the right error and increment the metric, qualified IMSIs still fall through to the API, suspended ranges are excluded, and the range boundaries are inclusive.

## Pre-conditions (Setup)

A single test class sets up:

- A `/29` pool (`100.65.214.0/29`, 6 usable IPs) — enough for two boundary allocations.
- An **active** range config covering IMSI seq 100..200 (`278771800000100`–`278771800000200`) with `ip_resolution="imsi"`.
- A second **suspended** range covering IMSI seq 500..599, used by test 18.3 to verify the status filter excludes non-active rows.

Stale profiles for the module-18 IMSI prefix are soft-deleted before the run, and any leftover IP allocations in those ranges are force-cleared.

The pre-check kill switch is the deployment env var `QUALIFY_PRECHECK_ENABLED` (default `"true"`), surfaced in `charts/aaa-lookup-service/values.yaml` as `qualifyPrecheckEnabled`. Tests assume it is enabled.

---

## Test 18.1 — Unqualified IMSI short-circuits with metric increment

**Goal:** Confirm that an IMSI no range row covers returns 404 `unqualified` and that the lookup-service Prometheus counter `aaa_lookup_unqualified_total` increments — proving `subscriber-profile-api` was never called.

1. Read the current value of `aaa_lookup_unqualified_total` from the lookup-service `/metrics` endpoint.
2. Send `GET /lookup?imsi=278771800009999&apn=internet.operator.com&use_case_id=…`.
3. Verify the response is HTTP 404 with body `{"error": "unqualified"}`.
4. Re-read the counter and verify it increased by at least 1.

## Test 18.2 — Qualified IMSI falls through to first-connection

**Goal:** Confirm that an IMSI inside the active range, with no existing profile, passes the pre-check and reaches the first-connection allocation path.

1. Send `GET /lookup?imsi=278771800000150&apn=internet.operator.com` (inside the active range, never provisioned).
2. Verify the response is HTTP 200 with a `static_ip` field set — meaning the lookup-service called `/first-connection` and relayed the allocated IP.

## Test 18.3 — Suspended range is treated as unqualified

**Goal:** Confirm that a range with `status='suspended'` is excluded by the `PREQUALIFY_SQL` filter (`status IN ('active','provisioned')`).

1. Send `GET /lookup` for an IMSI inside the suspended range (seq 550).
2. Verify the response is HTTP 404 with body `{"error": "unqualified"}` even though the IMSI is bracketed by `f_imsi`/`t_imsi`.

## Test 18.4 — Kill switch behaviour

Skipped at runtime: `QUALIFY_PRECHECK_ENABLED` is a deployment env var that requires a pod restart to toggle. CI exercises the disabled path through a dedicated `values-prequalify-off` chart override rather than from inside the regression suite.

## Test 18.5 — Boundary IMSIs are inclusive; one-off neighbours are unqualified

**Goal:** Verify the SQL predicate `f_imsi <= $1 AND t_imsi >= $1` has no off-by-one error.

1. Lookup for `f_imsi` exactly (seq 100) → HTTP 200 (allocates an IP).
2. Lookup for `t_imsi` exactly (seq 200) → HTTP 200 (allocates) or HTTP 503 `pool_exhausted` if the `/29` pool is already full. The response must NOT be `404 unqualified`.
3. Lookup for `f_imsi - 1` (seq 99) → HTTP 404 `unqualified`.
4. Lookup for `t_imsi + 1` (seq 201) → HTTP 404 `unqualified`.

---

## Post-conditions (Teardown)

The class re-activates the suspended range (so the API accepts the DELETE), removes both range configs, and deletes the pool. Profiles created by test 18.2 / 18.5 remain active and are cleaned up by the next run's `cleanup_stale_profiles`.
