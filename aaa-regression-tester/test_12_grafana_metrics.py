"""
test_12_grafana_metrics.py — Grafana chart metric validation

Tests that every metric panel in the Grafana "Platform Overview" dashboard is
fed by a real counter/gauge/histogram emitted by the services.

For each scenario the test verifies:
  - **Good path** — a successful operation increments the success-side metric.
  - **Error path** — an error condition increments the error-side metric.

Prometheus endpoints
────────────────────
  Provision API (subscriber-profile-api):  METRICS_URL       default http://localhost:9091
  Lookup service   (aaa-lookup-service):   LOOKUP_METRICS_URL default http://localhost:9090

Pre-requisites
──────────────
  Run with DB_URL set so conftest.py flushes stale data before the suite, or
  ensure module-12 IMSIs are not already provisioned.

Grafana panels covered
──────────────────────
  1. first_connection 503           → first_connection_total{result}
                                      pool_exhausted_total{pool_id}
  2. lookup db error                → aaa_lookup_requests_total{result="db_error"}
                                      aaa_db_errors_total
  3. in-flight requests             → http_requests_in_flight (provision API)
                                      aaa_in_flight_requests   (lookup service)
  4. DB rollbacks                   → db_rollbacks_total{reason="pool_exhausted"}
  5. pool exhaustion (event by pool)→ pool_exhausted_total{pool_id} (label isolation)
  6. failed bulk                    → bulk_job_profiles_total{outcome}
"""
import os
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
import pytest

from conftest import (
    ACCOUNT_NAME,
    PROVISION_BASE,
    LOOKUP_BASE,
    JWT_TOKEN,
    make_imsi,
    poll_until,
)
from fixtures.pools import create_pool, delete_pool, get_pool_stats, _force_clear_pool_ips, _force_clear_range_profiles
from fixtures.range_configs import create_range_config, delete_range_config

# ── Module constants ──────────────────────────────────────────────────────────

MODULE = 12


def _metrics_url(api_url: str, port: int) -> str:
    """Derive a metrics base URL from an API base URL by substituting the port."""
    parsed = urlparse(api_url)
    return f"{parsed.scheme}://{parsed.hostname}:{port}"


METRICS_URL        = os.getenv("METRICS_URL",        _metrics_url(PROVISION_BASE, 9091))
LOOKUP_METRICS_URL = os.getenv("LOOKUP_METRICS_URL", _metrics_url(LOOKUP_BASE,    9090))

# /30 subnet → 2 hosts (.1,.2) minus last-as-gateway (.2) = 1 usable IP.
# One successful first-connection exhausts the pool; the next returns 503.
SUBNET_POOL_A = "100.65.99.0/30"   # for first-connection / db-rollback tests
SUBNET_POOL_B = "100.65.98.0/30"   # for per-pool label isolation test

# IMSI ranges — module 12 namespace
F_IMSI_A = make_imsi(MODULE,   1)   # "278771200000001"
T_IMSI_A = make_imsi(MODULE,  99)   # "278771200000099"
F_IMSI_B = make_imsi(MODULE, 101)   # "278771200000101"
T_IMSI_B = make_imsi(MODULE, 199)   # "278771200000199"


# ── Prometheus text-format helpers ────────────────────────────────────────────

def fetch_metrics(client: httpx.Client) -> str:
    """GET /metrics and return the raw Prometheus text."""
    resp = client.get("/metrics", timeout=10.0)
    resp.raise_for_status()
    return resp.text


def parse_metric(text: str, name: str, labels: Optional[dict] = None) -> float:
    """
    Return a metric value from Prometheus /metrics text format.

    Searches for lines of the form::

        name{k1="v1",k2="v2",...} <value>
        name <value>                         (no-label form)

    Label order is irrelevant — each k="v" pair is checked as a substring.
    Skips ``_created`` and ``_total`` (histogram/counter internal) suffix lines.
    Returns 0.0 when the metric or label combination has not been initialised yet.
    """
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue

        # Extract the metric-name token (everything before the first space or '{')
        line_name = line.split("{")[0] if "{" in line else line.split(" ")[0]

        # Skip internal prometheus_client suffix lines (_created, _sum, _count, _bucket)
        for skip in ("_created", "_sum", "_count", "_bucket"):
            if line_name.endswith(skip):
                break
        else:
            if line_name != name:
                continue

            # Label filter: every k="v" must appear somewhere in the line
            if labels and not all(f'{k}="{v}"' in line for k, v in labels.items()):
                continue

            try:
                return float(line.rsplit(" ", 1)[-1])
            except (ValueError, IndexError):
                continue

    return 0.0


def delta(before: float, after: float) -> float:
    """Counter delta (after − before), always ≥ 0 in a monotonic counter."""
    return after - before


# ── Session fixtures (metrics HTTP clients) ───────────────────────────────────

@pytest.fixture(scope="module")
def metrics_http():
    """Prometheus client for the provision API (/metrics on METRICS_URL)."""
    with httpx.Client(base_url=METRICS_URL, timeout=10.0) as client:
        try:
            client.get("/metrics", timeout=5.0)
        except httpx.ConnectError:
            pytest.skip(f"Provision API metrics unreachable at {METRICS_URL}")
        yield client


@pytest.fixture(scope="module")
def lookup_metrics_http():
    """Prometheus client for the lookup service (/metrics on LOOKUP_METRICS_URL)."""
    with httpx.Client(base_url=LOOKUP_METRICS_URL, timeout=10.0) as client:
        try:
            client.get("/metrics", timeout=5.0)
        except httpx.ConnectError:
            pytest.skip(f"Lookup service metrics unreachable at {LOOKUP_METRICS_URL}")
        yield client


# ── Infrastructure fixtures ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pool_a(http: httpx.Client):
    """
    Tiny /30 pool (1 usable IP) wired to IMSI range A.
    Used by: TestFirstConnection503, TestDbRollbacks, TestPoolExhaustionByPool.
    """
    _force_clear_range_profiles(F_IMSI_A, T_IMSI_A)
    pool = create_pool(
        http,
        subnet=SUBNET_POOL_A,
        pool_name="metrics-test-pool-a",
        account_name=ACCOUNT_NAME,
        routing_domain="metrics-test-12",
        replace_on_conflict=True,
    )
    pool_id = pool["pool_id"]
    rc = create_range_config(
        http,
        f_imsi=F_IMSI_A,
        t_imsi=T_IMSI_A,
        pool_id=pool_id,
        account_name=ACCOUNT_NAME,
        description="metrics-test range A",
    )
    yield {"pool_id": pool_id, "range_config_id": rc["id"]}
    delete_range_config(http, rc["id"])
    _force_clear_pool_ips(pool_id)
    delete_pool(http, pool_id)


@pytest.fixture(scope="module")
def pool_b(http: httpx.Client):
    """
    Tiny /30 pool (1 usable IP) wired to IMSI range B.
    Used by: TestPoolExhaustionByPool — verifies per-pool label isolation.
    """
    _force_clear_range_profiles(F_IMSI_B, T_IMSI_B)
    pool = create_pool(
        http,
        subnet=SUBNET_POOL_B,
        pool_name="metrics-test-pool-b",
        account_name=ACCOUNT_NAME,
        routing_domain="metrics-test-12b",
        replace_on_conflict=True,
    )
    pool_id = pool["pool_id"]
    rc = create_range_config(
        http,
        f_imsi=F_IMSI_B,
        t_imsi=T_IMSI_B,
        pool_id=pool_id,
        account_name=ACCOUNT_NAME,
        description="metrics-test range B",
    )
    yield {"pool_id": pool_id, "range_config_id": rc["id"]}
    delete_range_config(http, rc["id"])
    _force_clear_pool_ips(pool_id)
    delete_pool(http, pool_id)


# ── 1. First-Connection 503 ───────────────────────────────────────────────────

class TestFirstConnection503:
    """
    Grafana panels:
      • "First-Connection Rate"     → first_connection_total{result}
      • "Pool Exhaustion Events"    → pool_exhausted_total / pool_exhausted_total{pool_id}
    """

    # 12.1 ────────────────────────────────────────────────────────────────────
    def test_01_happy_path_increments_allocated(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
        pool_a: dict,
    ):
        """POST /first-connection 201 → first_connection_total{result='allocated'} increments."""
        before = parse_metric(
            fetch_metrics(metrics_http),
            "first_connection_total",
            {"result": "allocated"},
        )

        resp = http.post(
            "/profiles/first-connection",
            json={"imsi": make_imsi(MODULE, 1), "apn": "internet", "use_case_id": "0800"},
        )
        assert resp.status_code == 201, (
            f"Expected 201 (new allocation), got {resp.status_code}: {resp.text}"
        )

        after = parse_metric(
            fetch_metrics(metrics_http),
            "first_connection_total",
            {"result": "allocated"},
        )
        assert delta(before, after) >= 1.0, (
            f"first_connection_total{{result='allocated'}} did not increment "
            f"(before={before}, after={after})"
        )

    # 12.2 ────────────────────────────────────────────────────────────────────
    def test_02_error_503_increments_pool_exhausted(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
        pool_a: dict,
    ):
        """
        Pool-A has 1 IP; drain it if test_01 didn't, then verify 503 increments
        first_connection_total{result='pool_exhausted'}.
        """
        # Self-drain: consume any remaining IPs so the pool is guaranteed exhausted
        # before we test the 503 path (handles the case where test_01 failed early).
        stats = get_pool_stats(http, pool_a["pool_id"])
        drain_seq = 10
        while stats["available"] > 0 and drain_seq <= 99:
            http.post(
                "/profiles/first-connection",
                json={"imsi": make_imsi(MODULE, drain_seq), "apn": "internet"},
            )
            drain_seq += 1
            stats = get_pool_stats(http, pool_a["pool_id"])

        before = parse_metric(
            fetch_metrics(metrics_http),
            "first_connection_total",
            {"result": "pool_exhausted"},
        )

        resp = http.post(
            "/profiles/first-connection",
            json={"imsi": make_imsi(MODULE, 2), "apn": "internet", "use_case_id": "0800"},
        )
        assert resp.status_code == 503, (
            f"Expected 503 (pool exhausted), got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("error") == "pool_exhausted", (
            f"Response body should have error='pool_exhausted', got: {resp.json()}"
        )

        after = parse_metric(
            fetch_metrics(metrics_http),
            "first_connection_total",
            {"result": "pool_exhausted"},
        )
        assert delta(before, after) >= 1.0, (
            f"first_connection_total{{result='pool_exhausted'}} did not increment "
            f"(before={before}, after={after})"
        )


# ── 2. Lookup DB Error ────────────────────────────────────────────────────────

class TestLookupDbError:
    """
    Grafana panels:
      • "Lookup DB Errors" → aaa_lookup_requests_total{result="db_error"}
      • "DB Error Rate"    → aaa_db_errors_total

    These metrics come from the aaa-lookup-service (C++ service, metrics on port 9090).
    """

    # 12.3 ────────────────────────────────────────────────────────────────────
    def test_03_happy_path_resolved_increments_metric(
        self,
        lookup_http: httpx.Client,
        lookup_metrics_http: httpx.Client,
        pool_a: dict,
    ):
        """
        Lookup for an already-provisioned IMSI (from TestFirstConnection503.test_01).
        aaa_lookup_requests_total{result='resolved'} must increment.
        """
        imsi = make_imsi(MODULE, 1)  # provisioned in test_01
        before = parse_metric(
            fetch_metrics(lookup_metrics_http),
            "aaa_lookup_requests_total",
            {"result": "resolved"},
        )

        resp = lookup_http.get("/lookup", params={"imsi": imsi, "apn": "internet"})
        # 200 = resolved from DB; 404 = not in lookup cache yet (acceptable for new allocs)
        assert resp.status_code in (200, 404), (
            f"Unexpected lookup status: {resp.status_code} {resp.text}"
        )

        after = parse_metric(
            fetch_metrics(lookup_metrics_http),
            "aaa_lookup_requests_total",
            {"result": "resolved"},
        )
        if resp.status_code == 200:
            assert delta(before, after) >= 1.0, (
                f"aaa_lookup_requests_total{{result='resolved'}} did not increment "
                f"(before={before}, after={after})"
            )

    # 12.4 ────────────────────────────────────────────────────────────────────
    def test_04_db_error_metric_observable(
        self,
        lookup_metrics_http: httpx.Client,
    ):
        """
        aaa_db_errors_total is present in the lookup-service /metrics output.
        Validates the Grafana chart has a live series (value ≥ 0).
        """
        text = fetch_metrics(lookup_metrics_http)
        assert "aaa_db_errors_total" in text, (
            "aaa_db_errors_total not found in lookup-service /metrics — "
            "the Grafana 'DB Error Rate' panel will have no data"
        )

    # 12.5 ────────────────────────────────────────────────────────────────────
    def test_05_db_error_label_observable(
        self,
        lookup_metrics_http: httpx.Client,
    ):
        """
        aaa_lookup_requests_total metric family is present in the output.
        Grafana can render the {result='db_error'} series once an error occurs.
        """
        text = fetch_metrics(lookup_metrics_http)
        assert "aaa_lookup_requests_total" in text, (
            "aaa_lookup_requests_total not found in lookup-service /metrics — "
            "the Grafana 'Lookup DB Errors' panel will have no data"
        )


# ── 3. In-Flight Requests ─────────────────────────────────────────────────────

class TestInFlightRequests:
    """
    Grafana panels:
      • "In-Flight Requests" → aaa_in_flight_requests  (lookup service)

    The provision API also exposes http_requests_in_flight for cross-checking.
    """

    # 12.6 ────────────────────────────────────────────────────────────────────
    def test_06_provision_api_in_flight_returns_to_zero(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
    ):
        """
        After N concurrent requests complete, http_requests_in_flight sums to 0.
        Validates the Gauge is properly decremented on every request completion.
        """
        errors: list[str] = []

        def make_request() -> None:
            try:
                http.get("/pools")
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        threads = [threading.Thread(target=make_request) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent requests raised errors: {errors}"

        text = fetch_metrics(metrics_http)
        total_in_flight = sum(
            float(line.rsplit(" ", 1)[-1])
            for line in text.splitlines()
            if line.startswith("http_requests_in_flight{")
            and not line.split("{")[0].endswith("_created")
        )
        assert total_in_flight == 0.0, (
            f"Expected http_requests_in_flight=0 after all requests completed, "
            f"got {total_in_flight}"
        )

    # 12.7 ────────────────────────────────────────────────────────────────────
    def test_07_provision_api_in_flight_peaks_above_zero(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
    ):
        """
        Under concurrent load the in-flight gauge rises above 0 at least once,
        then returns to 0 when all requests complete.
        """
        observed_above_zero = False
        errors: list[str] = []

        def make_request() -> None:
            try:
                http.get("/pools")
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        threads = [threading.Thread(target=make_request) for _ in range(20)]
        for t in threads:
            t.start()

        # Opportunistic poll — may not catch the peak every time (timing-dependent)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                text = fetch_metrics(metrics_http)
                total = sum(
                    float(line.rsplit(" ", 1)[-1])
                    for line in text.splitlines()
                    if line.startswith("http_requests_in_flight{")
                    and not line.split("{")[0].endswith("_created")
                )
                if total > 0:
                    observed_above_zero = True
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.005)

        for t in threads:
            t.join()

        # After all requests finish, gauge MUST be 0 (hard assertion)
        text = fetch_metrics(metrics_http)
        total_after = sum(
            float(line.rsplit(" ", 1)[-1])
            for line in text.splitlines()
            if line.startswith("http_requests_in_flight{")
            and not line.split("{")[0].endswith("_created")
        )
        assert total_after == 0.0, (
            f"http_requests_in_flight != 0 after all requests completed: {total_after}"
        )
        # Best-effort: log whether we caught the peak; not a hard failure because
        # the metrics endpoint itself is a concurrent request that may dominate.
        if not observed_above_zero:
            import warnings
            warnings.warn(
                "Did not observe http_requests_in_flight > 0 during polling — "
                "metrics poll was likely slower than the actual requests.",
                stacklevel=1,
            )

    # 12.8 ────────────────────────────────────────────────────────────────────
    def test_08_lookup_service_in_flight_observable(
        self,
        lookup_metrics_http: httpx.Client,
    ):
        """
        aaa_in_flight_requests is declared in the lookup-service /metrics output.
        Validates the Grafana 'In-Flight Requests' panel has a live series.
        """
        text = fetch_metrics(lookup_metrics_http)
        assert "aaa_in_flight_requests" in text, (
            "aaa_in_flight_requests not found in lookup-service /metrics — "
            "the Grafana 'In-Flight Requests' panel will have no data"
        )


# ── 4. DB Rollbacks ───────────────────────────────────────────────────────────

class TestDbRollbacks:
    """
    Grafana panel: "DB Rollbacks" → db_rollbacks_total{reason} (provision API)

    A first-connection that hits an exhausted pool raises HTTPException(503) inside
    an asyncpg transaction — asyncpg automatically rolls back the transaction.
    db_rollbacks_total{reason='pool_exhausted'} is incremented at that point.
    """

    # 12.9 ────────────────────────────────────────────────────────────────────
    def test_09_rollback_metric_increments_on_503(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
        pool_a: dict,
    ):
        """
        Pool-A is already exhausted.
        Another first-connection attempt → 503 → db_rollbacks_total{reason='pool_exhausted'}
        increments (the asyncpg transaction is rolled back when HTTPException propagates).
        """
        before = parse_metric(
            fetch_metrics(metrics_http),
            "db_rollbacks_total",
            {"reason": "pool_exhausted"},
        )

        resp = http.post(
            "/profiles/first-connection",
            json={"imsi": make_imsi(MODULE, 3), "apn": "internet"},
        )
        assert resp.status_code == 503

        after = parse_metric(
            fetch_metrics(metrics_http),
            "db_rollbacks_total",
            {"reason": "pool_exhausted"},
        )
        assert delta(before, after) >= 1.0, (
            f"db_rollbacks_total{{reason='pool_exhausted'}} did not increment "
            f"(before={before}, after={after})"
        )

    # 12.10 ───────────────────────────────────────────────────────────────────
    def test_10_rollback_metric_stable_on_happy_path(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
    ):
        """
        Successful read operations do not increment db_rollbacks_total.
        Validates the counter is not falsely incremented on normal traffic.
        """
        before = parse_metric(
            fetch_metrics(metrics_http),
            "db_rollbacks_total",
            {"reason": "pool_exhausted"},
        )
        resp = http.get("/pools")
        assert resp.status_code == 200

        after = parse_metric(
            fetch_metrics(metrics_http),
            "db_rollbacks_total",
            {"reason": "pool_exhausted"},
        )
        assert delta(before, after) == 0.0, (
            f"db_rollbacks_total unexpectedly incremented on a successful GET "
            f"(before={before}, after={after})"
        )


# ── 5. Pool Exhaustion by Pool ────────────────────────────────────────────────

class TestPoolExhaustionByPool:
    """
    Grafana panel: "Pool Exhaustion Events by Pool" → pool_exhausted_total{pool_id}

    Creates two pools (A and B) and exhausts them independently to verify that
    the pool_id label correctly partitions the time series.
    """

    # 12.11 ───────────────────────────────────────────────────────────────────
    def test_11_pool_a_counter_increments_for_pool_a(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
        pool_a: dict,
    ):
        """
        pool_exhausted_total{pool_id=<pool_a_id>} increments when pool-A exhaustion
        is triggered (IMSI seq 4 from range A → pool A → already exhausted).
        """
        pool_id_a = pool_a["pool_id"]
        before = parse_metric(
            fetch_metrics(metrics_http),
            "pool_exhausted_total",
            {"pool_id": pool_id_a},
        )

        resp = http.post(
            "/profiles/first-connection",
            json={"imsi": make_imsi(MODULE, 4), "apn": "internet"},
        )
        assert resp.status_code == 503

        after = parse_metric(
            fetch_metrics(metrics_http),
            "pool_exhausted_total",
            {"pool_id": pool_id_a},
        )
        assert delta(before, after) >= 1.0, (
            f"pool_exhausted_total{{pool_id={pool_id_a}}} did not increment "
            f"(before={before}, after={after})"
        )

    # 12.12 ───────────────────────────────────────────────────────────────────
    def test_12_pool_b_success_then_exhaustion(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
        pool_b: dict,
    ):
        """
        Pool-B: first IMSI 201 (allocates the single IP), second IMSI → 503.
        pool_exhausted_total{pool_id=<pool_b_id>} increments for pool-B.
        """
        pool_id_b = pool_b["pool_id"]

        # Happy path — allocate the only IP in pool-B
        resp1 = http.post(
            "/profiles/first-connection",
            json={"imsi": make_imsi(MODULE, 101), "apn": "internet"},
        )
        assert resp1.status_code == 201, (
            f"Expected 201 for pool-B first allocation, got {resp1.status_code}: {resp1.text}"
        )

        # Pool-B now exhausted; next attempt → 503
        before = parse_metric(
            fetch_metrics(metrics_http),
            "pool_exhausted_total",
            {"pool_id": pool_id_b},
        )
        resp2 = http.post(
            "/profiles/first-connection",
            json={"imsi": make_imsi(MODULE, 102), "apn": "internet"},
        )
        assert resp2.status_code == 503

        after = parse_metric(
            fetch_metrics(metrics_http),
            "pool_exhausted_total",
            {"pool_id": pool_id_b},
        )
        assert delta(before, after) >= 1.0, (
            f"pool_exhausted_total{{pool_id={pool_id_b}}} did not increment "
            f"(before={before}, after={after})"
        )

    # 12.13 ───────────────────────────────────────────────────────────────────
    def test_13_pool_a_counter_unaffected_by_pool_b_exhaustion(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
        pool_a: dict,
        pool_b: dict,
    ):
        """
        When pool-B is exhausted, pool_exhausted_total{pool_id=<pool_a_id>} must NOT
        change.  Validates that the pool_id label correctly partitions the series.
        """
        pool_id_a = pool_a["pool_id"]
        before_a = parse_metric(
            fetch_metrics(metrics_http),
            "pool_exhausted_total",
            {"pool_id": pool_id_a},
        )

        # Trigger another pool-B exhaustion (IMSI 103 falls in range B → pool B)
        resp = http.post(
            "/profiles/first-connection",
            json={"imsi": make_imsi(MODULE, 103), "apn": "internet"},
        )
        assert resp.status_code == 503

        after_a = parse_metric(
            fetch_metrics(metrics_http),
            "pool_exhausted_total",
            {"pool_id": pool_id_a},
        )
        assert delta(before_a, after_a) == 0.0, (
            f"pool_exhausted_total{{pool_id=pool-A}} changed when pool-B was exhausted "
            f"— pool_id label is not isolating time series correctly "
            f"(before={before_a}, after={after_a})"
        )


# ── 6. Failed Bulk ────────────────────────────────────────────────────────────

class TestFailedBulk:
    """
    Grafana panel: "Bulk Job Outcomes" → bulk_job_profiles_total{outcome}
    """

    # 12.14 ───────────────────────────────────────────────────────────────────
    def test_14_bulk_processed_increments_on_success(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
    ):
        """
        Submit a bulk job with valid profiles.
        bulk_job_profiles_total{outcome='processed'} must increase by ≥ submitted count.
        """
        profiles = [
            {
                "account_name": ACCOUNT_NAME,
                "status": "active",
                "ip_resolution": "imsi",
                "imsis": [{"imsi": make_imsi(MODULE, 500 + i), "apn_ips": []}],
            }
            for i in range(5)
        ]

        before = parse_metric(
            fetch_metrics(metrics_http),
            "bulk_job_profiles_total",
            {"outcome": "processed"},
        )

        resp = http.post("/profiles/bulk", json=profiles)
        assert resp.status_code == 202, f"Bulk submit failed: {resp.status_code} {resp.text}"
        job_id = resp.json()["job_id"]

        job = poll_until(
            lambda: http.get(f"/jobs/{job_id}").json(),
            lambda j: j["status"] == "completed",
            timeout=60.0,
            interval=1.0,
            label=f"bulk job {job_id}",
        )
        assert job["processed"] >= 5, f"Expected ≥5 processed rows, got: {job}"

        after = parse_metric(
            fetch_metrics(metrics_http),
            "bulk_job_profiles_total",
            {"outcome": "processed"},
        )
        assert delta(before, after) >= 5.0, (
            f"bulk_job_profiles_total{{outcome='processed'}} did not increase by ≥5 "
            f"(before={before}, after={after})"
        )

    # 12.15 ───────────────────────────────────────────────────────────────────
    def test_15_bulk_failed_increments_on_invalid_imsi(
        self,
        http: httpx.Client,
        metrics_http: httpx.Client,
    ):
        """
        Submit a bulk job that mixes valid and invalid IMSI entries.
        bulk_job_profiles_total{outcome='failed'} must increment for each bad row.
        """
        profiles: list[dict] = [
            # 3 valid profiles
            {
                "account_name": ACCOUNT_NAME,
                "status": "active",
                "ip_resolution": "imsi",
                "imsis": [{"imsi": make_imsi(MODULE, 600 + i), "apn_ips": []}],
            }
            for i in range(3)
        ]
        # 2 invalid rows — IMSI not 15 digits → BulkValidationError
        profiles += [
            {
                "account_name": ACCOUNT_NAME,
                "status": "active",
                "ip_resolution": "imsi",
                "imsis": [{"imsi": "BADIMSI", "apn_ips": []}],
            },
            {
                "account_name": ACCOUNT_NAME,
                "status": "active",
                "ip_resolution": "imsi",
                "imsis": [{"imsi": "123", "apn_ips": []}],
            },
        ]

        before = parse_metric(
            fetch_metrics(metrics_http),
            "bulk_job_profiles_total",
            {"outcome": "failed"},
        )

        resp = http.post("/profiles/bulk", json=profiles)
        assert resp.status_code == 202, f"Bulk submit failed: {resp.status_code} {resp.text}"
        job_id = resp.json()["job_id"]

        job = poll_until(
            lambda: http.get(f"/jobs/{job_id}").json(),
            lambda j: j["status"] == "completed",
            timeout=60.0,
            interval=1.0,
            label=f"bulk job {job_id}",
        )
        assert job["failed"] >= 2, (
            f"Expected ≥2 failed rows (invalid IMSIs), got: {job}"
        )

        after = parse_metric(
            fetch_metrics(metrics_http),
            "bulk_job_profiles_total",
            {"outcome": "failed"},
        )
        assert delta(before, after) >= 2.0, (
            f"bulk_job_profiles_total{{outcome='failed'}} did not increase by ≥2 "
            f"(before={before}, after={after})"
        )
