"""
test_18_lookup_prequalify.py — IMSI pre-qualification short-circuit in aaa-lookup-service.

Background
──────────
  When the lookup service's HOT_PATH_SQL returns no rows for an IMSI, it now
  runs PREQUALIFY_SQL on the read replica:

      SELECT 1 FROM imsi_range_configs
      WHERE  f_imsi <= $1 AND t_imsi >= $1
        AND  status IN ('active', 'provisioned')
      LIMIT  1

  - 0 rows → 404 {"error": "unqualified"} (subscriber-profile-api is NOT called)
  - ≥1 row → falls through to POST /first-connection (legacy path)
  - SQL error → fail-open, falls through to /first-connection

  Controlled by env var QUALIFY_PRECHECK_ENABLED (default "true"), surfaced
  in charts/aaa-lookup-service/values.yaml as ``qualifyPrecheckEnabled``.

Resources
─────────
  Module   : 18  → IMSI prefix 27877 18 xxxxxxxx
  Pool     : pool-prequalify-18  100.65.214.0/29  (1 usable IP — only test_02 allocates)
  Range    : 278771800000100..278771800000200  (active, ip_resolution="imsi")

Scenario matrix
───────────────
  18.1  [bad]  IMSI not covered by any range → 404 unqualified, metric increments
  18.2  [good] IMSI inside an active range (no profile) → /lookup falls through to API → 200 IP
  18.3  [bad]  IMSI inside a suspended range → 404 unqualified (status filter excludes)
  18.4  [skip] Kill-switch toggle requires deployment env change — out of scope
  18.5  [bad]  Boundary IMSIs: f_imsi & t_imsi qualified; f_imsi-1 & t_imsi+1 unqualified
"""
import os
from urllib.parse import urlparse

import httpx
import pytest

from conftest import (
    LOOKUP_BASE,
    PROVISION_BASE,
    JWT_TOKEN,
    USE_CASE_ID,
    make_imsi,
)
from fixtures.pools import create_pool, delete_pool, _force_clear_range_profiles
from fixtures.profiles import cleanup_stale_profiles
from fixtures.range_configs import create_range_config, delete_range_config


MODULE = 18

POOL_SUBNET = "100.65.214.0/29"          # 6 usable IPs — plenty for one allocation

# Range covers seqs 100..200 inclusive
F_IMSI = make_imsi(MODULE, 100)          # "278771800000100"
T_IMSI = make_imsi(MODULE, 200)          # "278771800000200"

# Below / above the active range — must come back "unqualified"
IMSI_BELOW    = make_imsi(MODULE,  99)   # "278771800000099"
IMSI_ABOVE    = make_imsi(MODULE, 201)   # "278771800000201"
IMSI_FAR_OOB  = make_imsi(MODULE, 9999)  # "278771800009999"

# Range used only by test_03 (suspended). Disjoint from the active range.
F_IMSI_SUSP = make_imsi(MODULE, 500)
T_IMSI_SUSP = make_imsi(MODULE, 599)
IMSI_SUSP   = make_imsi(MODULE, 550)

APN = "internet.operator.com"


# ── /metrics endpoint for the lookup service ─────────────────────────────────
def _metrics_url(api_url: str, port: int) -> str:
    parsed = urlparse(api_url)
    return f"{parsed.scheme}://{parsed.hostname}:{port}"


LOOKUP_METRICS_URL = os.getenv("LOOKUP_METRICS_URL",
                               _metrics_url(LOOKUP_BASE, 9090))


@pytest.fixture(scope="module")
def lookup_metrics_http():
    """Prometheus client for the lookup-service /metrics endpoint."""
    with httpx.Client(base_url=LOOKUP_METRICS_URL, timeout=10.0) as client:
        try:
            client.get("/metrics", timeout=5.0)
        except httpx.ConnectError:
            pytest.skip(f"lookup-service metrics unreachable at {LOOKUP_METRICS_URL}")
        yield client


def _read_counter(metrics_http: httpx.Client, name: str) -> float:
    """Fetch the no-label counter ``name`` from /metrics; return 0.0 if absent."""
    text = metrics_http.get("/metrics", timeout=5.0).text
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        head = line.split(" ", 1)[0]
        # Skip `_created`/`_total` companion lines from prometheus-cpp
        if head == name:
            try:
                return float(line.rsplit(" ", 1)[-1])
            except (ValueError, IndexError):
                return 0.0
    return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Single test class — all cases share one pool + one active range config
# ══════════════════════════════════════════════════════════════════════════════
class TestLookupPrequalify:
    pool_id:              str | None = None
    range_config_id:      str | None = None
    range_config_id_susp: str | None = None

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            cleanup_stale_profiles(c, "278771800000", "278771800009")
            _force_clear_range_profiles(F_IMSI, T_IMSI)
            _force_clear_range_profiles(F_IMSI_SUSP, T_IMSI_SUSP)

            pool = create_pool(
                c,
                subnet=POOL_SUBNET,
                pool_name="pool-prequalify-18",
                account_name="TestAccount",
                replace_on_conflict=True,
            )
            cls.pool_id = pool["pool_id"]

            rc = create_range_config(
                c,
                f_imsi=F_IMSI,
                t_imsi=T_IMSI,
                pool_id=cls.pool_id,
                ip_resolution="imsi",
                account_name="TestAccount",
                description="prequalify-active",
            )
            cls.range_config_id = rc["id"]

            rc_susp = create_range_config(
                c,
                f_imsi=F_IMSI_SUSP,
                t_imsi=T_IMSI_SUSP,
                pool_id=cls.pool_id,
                ip_resolution="imsi",
                account_name="TestAccount",
                description="prequalify-suspended",
            )
            cls.range_config_id_susp = rc_susp["id"]

            # Flip the second range to suspended so PREQUALIFY_SQL excludes it.
            r_susp = c.patch(
                f"/range-configs/{cls.range_config_id_susp}",
                json={"status": "suspended"},
            )
            assert r_susp.status_code == 200, (
                f"PATCH suspend failed: {r_susp.status_code} {r_susp.text}"
            )

    @classmethod
    def teardown_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            if cls.range_config_id_susp:
                # Re-activate before delete so the API doesn't reject the DELETE.
                c.patch(f"/range-configs/{cls.range_config_id_susp}",
                        json={"status": "active"})
                delete_range_config(c, cls.range_config_id_susp)
            if cls.range_config_id:
                delete_range_config(c, cls.range_config_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # 18.1 ────────────────────────────────────────────────────────────────────
    def test_01_unqualified_imsi_short_circuits(
        self,
        lookup_http: httpx.Client,
        lookup_metrics_http: httpx.Client,
    ):
        """IMSI in a prefix with no range row → 404 unqualified.

        The pre-check counter must increment, confirming the API was NOT called.
        """
        before = _read_counter(lookup_metrics_http, "aaa_lookup_unqualified_total")

        r = lookup_http.get(
            "/lookup",
            params={"imsi": IMSI_FAR_OOB, "apn": APN, "use_case_id": USE_CASE_ID},
        )
        assert r.status_code == 404, \
            f"Expected 404, got {r.status_code}: {r.text}"
        assert r.json()["error"] == "unqualified", \
            f"Expected error=unqualified, got {r.json()}"

        after = _read_counter(lookup_metrics_http, "aaa_lookup_unqualified_total")
        assert after - before >= 1.0, (
            f"aaa_lookup_unqualified_total did not increment "
            f"(before={before}, after={after})"
        )

    # 18.2 ────────────────────────────────────────────────────────────────────
    def test_02_qualified_imsi_falls_through(
        self,
        lookup_http: httpx.Client,
    ):
        """IMSI inside the active range (no profile yet) → pre-check passes →
        lookup-service calls /first-connection and returns 200 with an IP.
        """
        imsi = make_imsi(MODULE, 150)  # inside [100,200], not previously provisioned

        r = lookup_http.get(
            "/lookup",
            params={"imsi": imsi, "apn": APN, "use_case_id": USE_CASE_ID},
        )
        assert r.status_code == 200, (
            f"Pre-check should not block qualified IMSI; got {r.status_code}: {r.text}"
        )
        body = r.json()
        assert "static_ip" in body, f"Expected static_ip in body, got {body}"

    # 18.3 ────────────────────────────────────────────────────────────────────
    def test_03_inactive_status_treated_as_unqualified(
        self,
        lookup_http: httpx.Client,
    ):
        """A range with status='suspended' is excluded by PREQUALIFY_SQL's
        ``status IN ('active','provisioned')`` filter — IMSI must 404 unqualified.
        """
        r = lookup_http.get(
            "/lookup",
            params={"imsi": IMSI_SUSP, "apn": APN, "use_case_id": USE_CASE_ID},
        )
        assert r.status_code == 404, \
            f"Expected 404, got {r.status_code}: {r.text}"
        assert r.json()["error"] == "unqualified", (
            f"Suspended range should produce unqualified, got {r.json()}"
        )

    # 18.4 ────────────────────────────────────────────────────────────────────
    @pytest.mark.skip(
        reason="Kill switch (QUALIFY_PRECHECK_ENABLED) is a deployment-time env var; "
               "toggling it requires a pod restart and is exercised in CI via a "
               "dedicated values-prequalify-off chart override."
    )
    def test_04_kill_switch_disables_prequalify(self):
        pass

    # 18.5 ────────────────────────────────────────────────────────────────────
    def test_05_boundary_imsis(
        self,
        lookup_http: httpx.Client,
    ):
        """Exact boundary IMSIs are inclusive; one-off IMSIs are unqualified.

        The PREQUALIFY_SQL predicate is ``f_imsi <= $1 AND t_imsi >= $1`` —
        confirms no off-by-one in the lookup-service's call site.
        """
        # f_imsi (lower bound, inclusive) — qualified, expect 200 (allocates IP)
        r_lo = lookup_http.get(
            "/lookup",
            params={"imsi": F_IMSI, "apn": APN, "use_case_id": USE_CASE_ID},
        )
        assert r_lo.status_code == 200, \
            f"f_imsi ({F_IMSI}) must be qualified, got {r_lo.status_code}: {r_lo.text}"

        # t_imsi (upper bound, inclusive) — qualified; pool may already be exhausted.
        # Either 200 (allocated) or 503 pool_exhausted is acceptable; what we
        # require is that the response is NOT a pre-check rejection.
        r_hi = lookup_http.get(
            "/lookup",
            params={"imsi": T_IMSI, "apn": APN, "use_case_id": USE_CASE_ID},
        )
        if r_hi.status_code == 404:
            assert r_hi.json().get("error") != "unqualified", (
                f"t_imsi ({T_IMSI}) must NOT be unqualified — boundary inclusive"
            )
        else:
            assert r_hi.status_code in (200, 503), \
                f"Unexpected status for t_imsi: {r_hi.status_code} {r_hi.text}"

        # f_imsi - 1 (just below) — unqualified
        r_below = lookup_http.get(
            "/lookup",
            params={"imsi": IMSI_BELOW, "apn": APN, "use_case_id": USE_CASE_ID},
        )
        assert r_below.status_code == 404 and r_below.json()["error"] == "unqualified", (
            f"IMSI_BELOW ({IMSI_BELOW}) must be unqualified, "
            f"got {r_below.status_code}: {r_below.text}"
        )

        # t_imsi + 1 (just above) — unqualified
        r_above = lookup_http.get(
            "/lookup",
            params={"imsi": IMSI_ABOVE, "apn": APN, "use_case_id": USE_CASE_ID},
        )
        assert r_above.status_code == 404 and r_above.json()["error"] == "unqualified", (
            f"IMSI_ABOVE ({IMSI_ABOVE}) must be unqualified, "
            f"got {r_above.status_code}: {r_above.text}"
        )
