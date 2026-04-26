"""
test_24_lazy_pool_creation.py — verify large pool creation is O(1) and IPs
are claimed lazily.

Before lazy-pool, ``POST /pools`` materialised every host address into
``ip_pool_available`` at creation time. A /12 pool (≈1 M IPs) timed out the
request with a 504. After lazy-pool, creation only stores the subnet bounds
in ``ip_pool_subnets``; IPs are claimed in chunks at range-config time and
on-demand by ``_allocate_ip``.

This test exercises a /20 (4094 host IPs) — large enough that an eager
pre-population would take noticeably long, small enough that we don't
need a /12 reservation.

Resources
─────────
  Module 24 → IMSI prefix 27877 24 xxxxxxxx
  Subnet:   100.66.16.0/20  (4094 usable IPs)
"""
import time

import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID, make_imsi
from fixtures.pools import (
    create_pool,
    delete_pool,
    get_pool_stats,
    _force_clear_pool_ips,
    _force_clear_range_profiles,
)
from fixtures.range_configs import (
    create_range_config,
    delete_range_config,
)


MODULE = 24
SUBNET_LARGE = "100.66.16.0/20"   # 4094 hosts (default bounds)
USABLE_LARGE = 4094

CREATION_BUDGET_SECONDS = 5.0     # Eager would have taken minutes; lazy is sub-second


def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=30.0,
    )


@pytest.mark.order(2400)
class TestLazyPoolCreation:
    """Large /20 subnet creates fast and allocates on demand."""

    pool_id: str | None = None
    range_id: int | None = None

    F_IMSI = make_imsi(MODULE, 1)
    T_IMSI = make_imsi(MODULE, 5)     # 5 IMSIs — small range for on-demand claim

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_range_config(c, cls.range_id)
            if cls.pool_id:
                _force_clear_pool_ips(cls.pool_id)
                delete_pool(c, cls.pool_id)

    # 24.1 ────────────────────────────────────────────────────────────────────
    def test_01_creation_is_fast(self, http: httpx.Client):
        """POST /pools with /20 returns within seconds (no eager pre-pop)."""
        t0 = time.monotonic()
        pool = create_pool(
            http,
            subnet=SUBNET_LARGE,
            pool_name="test-24-lazy",
            replace_on_conflict=True,
        )
        elapsed = time.monotonic() - t0
        TestLazyPoolCreation.pool_id = pool["pool_id"]
        assert elapsed < CREATION_BUDGET_SECONDS, (
            f"pool creation took {elapsed:.2f}s — eager pre-pop regression?"
        )

    # 24.2 ────────────────────────────────────────────────────────────────────
    def test_02_stats_reflect_full_capacity(self, http: httpx.Client):
        """Stats show full /20 capacity available, zero allocated."""
        stats = get_pool_stats(http, self.pool_id)
        assert stats["total"] == USABLE_LARGE, (
            f"expected total={USABLE_LARGE}, got {stats}"
        )
        assert stats["allocated"] == 0
        assert stats["available"] == USABLE_LARGE

    # 24.3 ────────────────────────────────────────────────────────────────────
    def test_03_immediate_range_claims_only_what_it_needs(self, http: httpx.Client):
        """Immediate range over a 5-IMSI window claims exactly 5 IPs (lazy)."""
        _force_clear_range_profiles(self.F_IMSI, self.T_IMSI)
        rc = create_range_config(
            http,
            f_imsi=self.F_IMSI,
            t_imsi=self.T_IMSI,
            pool_id=self.pool_id,
            ip_resolution="imsi",
            provisioning_mode="immediate",
        )
        TestLazyPoolCreation.range_id = rc["id"]

        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] == 5, (
            f"only 5 IPs should have been claimed, got {stats}"
        )
        # Plenty of headroom — we touched a tiny slice of the /20 watermark.
        assert stats["available"] == USABLE_LARGE - 5

    # 24.4 ────────────────────────────────────────────────────────────────────
    def test_04_first_connection_returns_real_ip(self, http: httpx.Client):
        """Allocated IPs are real, parseable, and inside the registered subnet."""
        r = http.post(
            "/first-connection",
            json={"imsi": self.F_IMSI, "apn": "internet.operator.com",
                  "use_case_id": USE_CASE_ID},
        )
        assert r.status_code in (200, 201), f"first-connection failed: {r.text}"
        ip = r.json().get("static_ip", "")
        # Subnet 100.66.16.0/20 spans 100.66.16.x – 100.66.31.x
        first_octets = ".".join(ip.split(".")[:2])
        assert first_octets == "100.66", f"IP {ip!r} not in registered /20"
        third = int(ip.split(".")[2])
        assert 16 <= third <= 31, f"IP {ip!r} third octet not in /20 range"
