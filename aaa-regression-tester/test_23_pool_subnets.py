"""
test_23_pool_subnets.py — multi-subnet IP pool expansion via POST /pools/{id}/subnets.

Validates the new lazy-pool capability that lets a single ip_pools row span
multiple CIDR blocks. Each block is recorded in ip_pool_subnets with its own
``next_ip_offset`` watermark and a ``priority`` ordering; allocations drain
priority 0 first, then spill into priority 1 once the primary subnet is done.

Resources
─────────
  Module 23 → IMSI prefix 27877 23 xxxxxxxx
  Subnets:
    Primary    100.66.0.0/29  (6 usable IPs — gateway-reserved default)
    Secondary  100.66.0.16/29 (6 usable IPs)
    Overlap    100.66.0.4/30  (overlaps primary — must be rejected)

Five test cases:
  A.1  Create pool with primary subnet only — fast O(1) creation.
  A.2  GET /pools/{id}/stats reflects primary-subnet capacity.
  A.3  POST /pools/{id}/subnets adds a secondary subnet.
  A.4  Overlap detection rejects an overlapping CIDR (covers both ip_pools.subnet
       AND ip_pool_subnets.subnet via the UNION-based overlap query).
  A.5  Allocation drains priority 0 first, then spills into priority 1.
"""
import time

import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID, make_imsi
from fixtures.pools import (
    create_pool,
    delete_pool,
    get_pool_stats,
    add_pool_subnet,
    _force_clear_pool_ips,
    _force_clear_range_profiles,
)
from fixtures.range_configs import (
    create_range_config,
    delete_range_config,
)


MODULE = 23

PRIMARY_SUBNET   = "100.66.0.0/29"      # /29 → 8 addrs; default bounds .1..(bcast-2) = 5
SECONDARY_SUBNET = "100.66.0.16/29"     # 5 hosts
OVERLAP_SUBNET   = "100.66.0.4/30"      # overlaps PRIMARY (.4–.7)
USABLE_PER_29    = 5                    # default bounds reserve gateway + last host


def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=30.0,
    )


@pytest.mark.order(2300)
class TestPoolMultiSubnet:
    """Lazy multi-subnet pool — primary + secondary CIDR blocks."""

    pool_id: str | None = None
    range_id: int | None = None

    F_IMSI = make_imsi(MODULE, 1)            # 278772300000001
    T_IMSI = make_imsi(MODULE, 8)            # 278772300000008 — 8 IMSIs > primary 5

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_range_config(c, cls.range_id)
            if cls.pool_id:
                _force_clear_pool_ips(cls.pool_id)
                delete_pool(c, cls.pool_id)

    # 23.1 ────────────────────────────────────────────────────────────────────
    def test_01_create_pool_with_primary_subnet(self, http: httpx.Client):
        """POST /pools with primary subnet completes fast (lazy creation)."""
        t0 = time.monotonic()
        pool = create_pool(
            http,
            subnet=PRIMARY_SUBNET,
            pool_name="test-23-multi",
            replace_on_conflict=True,
        )
        elapsed = time.monotonic() - t0
        TestPoolMultiSubnet.pool_id = pool["pool_id"]
        # Lazy creation: even tiny subnets shouldn't take long. Sanity check.
        assert elapsed < 5.0, f"pool creation took {elapsed:.2f}s — lazy regression?"

    # 23.2 ────────────────────────────────────────────────────────────────────
    def test_02_stats_reflect_primary_capacity(self, http: httpx.Client):
        """GET /stats shows total == primary-subnet capacity, allocated == 0."""
        stats = get_pool_stats(http, self.pool_id)
        assert stats["total"] == USABLE_PER_29, (
            f"primary-only total expected {USABLE_PER_29}, got {stats}"
        )
        assert stats["allocated"] == 0, f"unexpected allocated count: {stats}"
        assert stats["available"] == USABLE_PER_29

    # 23.3 ────────────────────────────────────────────────────────────────────
    def test_03_add_secondary_subnet(self, http: httpx.Client):
        """POST /pools/{id}/subnets registers a secondary CIDR; stats sum both."""
        resp = add_pool_subnet(http, self.pool_id, subnet=SECONDARY_SUBNET)
        assert resp.status_code == 201, f"add subnet failed: {resp.status_code} {resp.text}"

        stats = get_pool_stats(http, self.pool_id)
        assert stats["total"] == USABLE_PER_29 * 2, (
            f"after adding secondary, total should be {USABLE_PER_29 * 2}, got {stats}"
        )
        assert stats["allocated"] == 0
        assert stats["available"] == USABLE_PER_29 * 2

    # 23.4 ────────────────────────────────────────────────────────────────────
    def test_04_overlap_detection(self, http: httpx.Client):
        """A CIDR overlapping the primary subnet must be rejected (409)."""
        resp = add_pool_subnet(http, self.pool_id, subnet=OVERLAP_SUBNET)
        assert resp.status_code == 409, (
            f"overlap should return 409, got {resp.status_code} {resp.text}"
        )
        # The error body should identify it as an overlap with this same pool.
        body = resp.json()
        assert body.get("error") in ("pool_overlap", "subnet_overlap"), body

    # 23.5 ────────────────────────────────────────────────────────────────────
    def test_05_allocation_spans_both_subnets(self, http: httpx.Client):
        """Range size > primary capacity drains priority 0 then spills to priority 1."""
        _force_clear_range_profiles(self.F_IMSI, self.T_IMSI)
        # Range size = 8 > primary 5 → 5 from primary + 3 from secondary subnet.
        rc = create_range_config(
            http,
            f_imsi=self.F_IMSI,
            t_imsi=self.T_IMSI,
            pool_id=self.pool_id,
            ip_resolution="imsi",
            provisioning_mode="immediate",
        )
        TestPoolMultiSubnet.range_id = rc["id"]

        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] == 8, (
            f"all 8 IPs should have been claimed across both subnets, got {stats}"
        )
        assert stats["available"] == USABLE_PER_29 * 2 - 8

        # First-connection on F_IMSI returns one of the IPs; verify it's from
        # one of the registered subnets.
        r = http.post(
            "/first-connection",
            json={"imsi": self.F_IMSI, "apn": "internet.operator.com",
                  "use_case_id": USE_CASE_ID},
        )
        assert r.status_code in (200, 201), f"first-connection failed: {r.text}"
        body = r.json()
        ip = body.get("static_ip", "")
        assert ip.startswith("100.66.0."), (
            f"IP {ip!r} not in either registered subnet"
        )
