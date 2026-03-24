"""
test_07c_release_ips.py — IP release / detach tests.

Covers two operations:
  POST  /profiles/{sim_id}/release-ips
      Returns all pool-managed IPs for the SIM back to ip_pool_available.
      IMSI bindings (imsi2sim) are kept intact; only IP allocations are cleared.
      Next first-connection re-allocates fresh IPs.

  DELETE /profiles/{sim_id}/imsis/{imsi}  (enhanced)
      Removes the IMSI from the SIM and returns its pool-managed IPs to the pool.
"""

import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID
from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import cleanup_stale_profiles
from fixtures.range_configs import create_range_config, delete_range_config

# Isolated /29 pool → 6 usable IPs (.1–.6)
POOL_SUBNET  = "100.65.195.0/29"
USABLE_COUNT = 6

# IMSI range and test IMSIs (distinct prefix to avoid collision with other modules)
F_IMSI = "278773075000001"
T_IMSI = "278773075000099"

IMSI_REL1 = "278773075000001"   # 7c.2 — release-ips after first-connection
IMSI_REL2 = "278773075000002"   # 7c.4 — re-allocation after release
IMSI_DEL1 = "278773075000010"   # 7c.6 — delete IMSI returns IPs
IMSI_DEL2 = "278773075000011"   # 7c.7 — deleted IMSI can be re-added


class TestReleaseIps:
    pool_id:         str | None = None
    range_config_id: str | None = None

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            # Terminate any profiles left by a previous interrupted run.
            cleanup_stale_profiles(c, "278773075")

            p = create_pool(c, subnet=POOL_SUBNET,
                            pool_name="pool-rel-07c", account_name="TestAccount",
                            replace_on_conflict=True)
            cls.pool_id = p["pool_id"]

            rc = create_range_config(
                c,
                f_imsi=F_IMSI,
                t_imsi=T_IMSI,
                pool_id=cls.pool_id,
                ip_resolution="imsi",
                account_name="TestAccount",
            )
            cls.range_config_id = rc["id"]

    @classmethod
    def teardown_class(cls):
        # Profiles are intentionally NOT deleted — they remain visible after
        # the run for post-run inspection via GET /profiles/export.
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            if cls.range_config_id:
                delete_range_config(c, cls.range_config_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    @staticmethod
    def _first_connection(http: httpx.Client, imsi: str) -> httpx.Response:
        return http.post(
            "/profiles/first-connection",
            json={"imsi": imsi, "apn": "internet.operator.com", "use_case_id": USE_CASE_ID},
        )

    # 7c.1 ────────────────────────────────────────────────────────────────────
    def test_01_setup_verified(self, http: httpx.Client):
        """Pool and range config are reachable before release tests."""
        r = http.get(f"/pools/{TestReleaseIps.pool_id}/stats")
        assert r.status_code == 200
        stats = r.json()
        # Allow up to 1 stale allocated IP from a previous unclean run.
        assert stats["available"] >= USABLE_COUNT - 1, \
            f"Pool has too few available IPs: {stats}"
        assert stats["allocated"] <= 1, \
            f"Pool has unexpected allocations from a prior run: {stats}"

    # 7c.2 ────────────────────────────────────────────────────────────────────
    def test_02_release_ips_returns_to_pool(self, http: httpx.Client):
        """
        first-connection allocates an IP → POST release-ips returns it to pool.
        Profile and IMSI binding remain; only IP allocation is cleared.
        """
        r_fc = self._first_connection(http, IMSI_REL1)
        assert r_fc.status_code == 201, f"first-connection failed: {r_fc.text}"
        sim_id = r_fc.json()["sim_id"]
        allocated_ip = r_fc.json()["static_ip"]

        stats_before = http.get(f"/pools/{TestReleaseIps.pool_id}/stats").json()
        assert stats_before["allocated"] >= 1

        # Release IPs
        r_rel = http.post(f"/profiles/{sim_id}/release-ips")
        assert r_rel.status_code == 200, f"release-ips failed: {r_rel.text}"
        body = r_rel.json()
        assert body["released_count"] == 1
        assert len(body["ips_released"]) == 1
        assert body["ips_released"][0]["ip"] == allocated_ip
        assert body["ips_released"][0]["imsi"] == IMSI_REL1

        # Pool available count must increase by 1
        stats_after = http.get(f"/pools/{TestReleaseIps.pool_id}/stats").json()
        assert stats_after["available"] == stats_before["available"] + 1

        # Profile still exists, IMSI binding still exists, but no IP
        r_prof = http.get(f"/profiles/{sim_id}")
        assert r_prof.status_code == 200
        imsis = r_prof.json()["imsis"]
        assert len(imsis) == 1
        assert imsis[0]["imsi"] == IMSI_REL1
        assert imsis[0]["apn_ips"] == []

    # 7c.3 ────────────────────────────────────────────────────────────────────
    def test_03_release_ips_idempotent(self, http: httpx.Client):
        """Calling release-ips on a profile with no IPs → 200, released_count=0."""
        # IMSI_REL1's sim_id was released in 7c.2; re-fetch sim_id
        r_list = http.get("/profiles", params={"imsi": IMSI_REL1})
        assert r_list.status_code == 200
        sim_id = r_list.json()[0]["sim_id"]

        r_rel = http.post(f"/profiles/{sim_id}/release-ips")
        assert r_rel.status_code == 200
        assert r_rel.json()["released_count"] == 0
        assert r_rel.json()["ips_released"] == []

    # 7c.4 ────────────────────────────────────────────────────────────────────
    def test_04_first_connection_after_release_allocates_fresh_ip(
            self, http: httpx.Client):
        """After release-ips, first-connection on the same IMSI allocates a new IP."""
        r_fc = self._first_connection(http, IMSI_REL1)
        assert r_fc.status_code in (200, 201), \
            f"Expected 200/201 after re-connect, got {r_fc.status_code}: {r_fc.text}"
        assert "static_ip" in r_fc.json()

        # Verify pool allocated count went back up
        stats = http.get(f"/pools/{TestReleaseIps.pool_id}/stats").json()
        assert stats["allocated"] >= 1

    # 7c.5 ────────────────────────────────────────────────────────────────────
    def test_05_release_ips_not_found(self, http: httpx.Client):
        """POST release-ips on unknown sim_id → 404."""
        fake_id = "00000000-0000-0000-0000-000000000099"
        r = http.post(f"/profiles/{fake_id}/release-ips")
        assert r.status_code == 404

    # 7c.6 ────────────────────────────────────────────────────────────────────
    def test_06_delete_imsi_returns_ips_to_pool(self, http: httpx.Client):
        """
        DELETE /profiles/{sim_id}/imsis/{imsi} must return the IMSI's IPs to the pool.
        """
        r_fc = self._first_connection(http, IMSI_DEL1)
        assert r_fc.status_code == 201, f"first-connection failed: {r_fc.text}"
        sim_id = r_fc.json()["sim_id"]

        stats_before = http.get(f"/pools/{TestReleaseIps.pool_id}/stats").json()

        r_del = http.delete(f"/profiles/{sim_id}/imsis/{IMSI_DEL1}")
        assert r_del.status_code == 204, f"delete IMSI failed: {r_del.text}"

        stats_after = http.get(f"/pools/{TestReleaseIps.pool_id}/stats").json()
        assert stats_after["available"] == stats_before["available"] + 1, \
            "IP was not returned to pool after IMSI deletion"

    # 7c.7 ────────────────────────────────────────────────────────────────────
    def test_07_deleted_imsi_can_be_reassigned(self, http: httpx.Client):
        """
        After DELETE /imsis/{imsi}, the same IMSI can be added to another profile
        without a conflict error.
        """
        # Create a profile with IMSI_DEL2 via first-connection
        r_fc = self._first_connection(http, IMSI_DEL2)
        assert r_fc.status_code == 201
        sim_id = r_fc.json()["sim_id"]

        # Delete the IMSI from the profile
        r_del = http.delete(f"/profiles/{sim_id}/imsis/{IMSI_DEL2}")
        assert r_del.status_code == 204

        # Create a fresh profile and add the same IMSI — must succeed without conflict
        r_new = http.post("/profiles", json={
            "ip_resolution": "imsi",
            "account_name": "TestAccount",
            "imsis": [{"imsi": IMSI_DEL2, "priority": 1}],
        })
        assert r_new.status_code == 201, \
            f"Expected 201 reassigning deleted IMSI, got {r_new.status_code}: {r_new.text}"
