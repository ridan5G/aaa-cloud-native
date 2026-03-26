"""
test_07e_release_reconnect_all_modes.py — Regression test: release-ips + first-connection
re-allocation across all four ip_resolution modes.

Bug guarded against
───────────────────
After POST /profiles/{sim_id}/release-ips, a subsequent POST /profiles/first-connection
was returning static_ip=null instead of allocating a fresh IP from the pool.  This
happened across all four resolution modes (imsi, imsi_apn, iccid, iccid_apn).

What this file tests
────────────────────
For each mode the test performs a full release → reconnect cycle:
  1. first-connection → assert 201 + non-null static_ip
  2. release-ips      → assert 200, released_count >= 1, pool available increases
  3. first-connection → assert 200/201 + non-null static_ip  ← KEY regression assertion
  4. assert pool allocated count increased again

Module number 79 avoids conflicts with other test modules (75=test_07c, 76=test_08b,
77=test_08c, 78=test_08d).
"""

import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID
from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import cleanup_stale_profiles
from fixtures.range_configs import (
    create_range_config,
    delete_range_config,
    create_iccid_range_config,
    delete_iccid_range_config,
    add_imsi_slot,
)

# ── Module constants ──────────────────────────────────────────────────────────

MODULE = 79   # distinct from: 75=test_07c, 76=test_08b, 77=test_08c etc.
APN = "internet.operator.com"

# ── IMSI / ICCID ranges ───────────────────────────────────────────────────────
# Each mode MUST have a non-overlapping IMSI range — first-connection picks
# ONE matching range config (ORDER BY f_imsi LIMIT 1); overlapping ranges for
# different ip_resolution modes would produce non-deterministic results.

# imsi mode: slots 001–009
F_IMSI_IMSI    = f"27877{MODULE:02d}00000001"
T_IMSI_IMSI    = f"27877{MODULE:02d}00000009"
IMSI_IMSI      = f"27877{MODULE:02d}00000001"

# imsi_apn mode: slots 011–019
F_IMSI_IMSI_APN = f"27877{MODULE:02d}00000011"
T_IMSI_IMSI_APN = f"27877{MODULE:02d}00000019"
IMSI_IMSI_APN   = f"27877{MODULE:02d}00000011"

# iccid mode: slots 021–029 (multi-IMSI via iccid_range_config)
F_IMSI_ICCID     = f"27877{MODULE:02d}00000021"
T_IMSI_ICCID     = f"27877{MODULE:02d}00000029"
IMSI_ICCID       = f"27877{MODULE:02d}00000021"
F_ICCID_ICCID    = "8944501790000000021"   # 19 digits
T_ICCID_ICCID    = "8944501790000000029"   # 19 digits

# iccid_apn mode: slots 031–039 (multi-IMSI via iccid_range_config)
F_IMSI_ICCID_APN  = f"27877{MODULE:02d}00000031"
T_IMSI_ICCID_APN  = f"27877{MODULE:02d}00000039"
IMSI_ICCID_APN    = f"27877{MODULE:02d}00000031"
F_ICCID_ICCID_APN = "8944501790000000031"  # 19 digits
T_ICCID_ICCID_APN = "8944501790000000039"  # 19 digits

# Verify all IMSIs and range bounds are exactly 15 characters at import time.
for _name, _imsi in [
    ("IMSI_IMSI",          IMSI_IMSI),
    ("IMSI_IMSI_APN",      IMSI_IMSI_APN),
    ("IMSI_ICCID",         IMSI_ICCID),
    ("IMSI_ICCID_APN",     IMSI_ICCID_APN),
    ("F_IMSI_IMSI",        F_IMSI_IMSI),
    ("T_IMSI_IMSI",        T_IMSI_IMSI),
    ("F_IMSI_IMSI_APN",    F_IMSI_IMSI_APN),
    ("T_IMSI_IMSI_APN",    T_IMSI_IMSI_APN),
    ("F_IMSI_ICCID",       F_IMSI_ICCID),
    ("T_IMSI_ICCID",       T_IMSI_ICCID),
    ("F_IMSI_ICCID_APN",   F_IMSI_ICCID_APN),
    ("T_IMSI_ICCID_APN",   T_IMSI_ICCID_APN),
]:
    assert len(_imsi) == 15, f"{_name}={_imsi!r} is {len(_imsi)} chars, expected 15"

# ── Pool subnets (/28 = 14 usable IPs per mode) ───────────────────────────────

POOL_SUBNETS = {
    "imsi":      "100.65.206.0/28",
    "imsi_apn":  "100.65.206.16/28",
    "iccid":     "100.65.206.32/28",
    "iccid_apn": "100.65.206.48/28",
}


class TestReleaseReconnectAllModes:
    pool_ids:     dict = {}
    rc_ids:       dict = {}
    iccid_rc_ids: dict = {}

    @classmethod
    def setup_class(cls):
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            # Clean up any profiles left by a previous interrupted run.
            cleanup_stale_profiles(c, f"27877{MODULE:02d}")

            # ── Create one pool per resolution mode ───────────────────────────
            cls.pool_ids = {}
            for mode, subnet in POOL_SUBNETS.items():
                p = create_pool(
                    c,
                    subnet=subnet,
                    pool_name=f"pool-rel-07e-{mode}",
                    account_name="TestAccount",
                    replace_on_conflict=True,
                )
                cls.pool_ids[mode] = p["pool_id"]

            # ── imsi mode: standalone range config (slots 001–009) ────────────
            rc_imsi = create_range_config(
                c,
                f_imsi=F_IMSI_IMSI,
                t_imsi=T_IMSI_IMSI,
                pool_id=cls.pool_ids["imsi"],
                ip_resolution="imsi",
                account_name="TestAccount",
            )
            cls.rc_ids["imsi"] = rc_imsi["id"]

            # ── imsi_apn mode: standalone range config (slots 011–019) ────────
            rc_imsi_apn = create_range_config(
                c,
                f_imsi=F_IMSI_IMSI_APN,
                t_imsi=T_IMSI_IMSI_APN,
                pool_id=cls.pool_ids["imsi_apn"],
                ip_resolution="imsi_apn",
                account_name="TestAccount",
            )
            cls.rc_ids["imsi_apn"] = rc_imsi_apn["id"]

            # ── iccid mode: iccid_range_config + imsi slot ────────────────────
            iccid_rc = create_iccid_range_config(
                c,
                f_iccid=F_ICCID_ICCID,
                t_iccid=T_ICCID_ICCID,
                ip_resolution="iccid",
                account_name="TestAccount",
                imsi_count=1,
                pool_id=cls.pool_ids["iccid"],
            )
            cls.iccid_rc_ids["iccid"] = iccid_rc["id"]

            add_imsi_slot(
                c,
                iccid_range_id=iccid_rc["id"],
                f_imsi=F_IMSI_ICCID,
                t_imsi=T_IMSI_ICCID,
                imsi_slot=1,
                ip_resolution="iccid",
                pool_id=cls.pool_ids["iccid"],
            )

            # ── iccid_apn mode: iccid_range_config + imsi slot ────────────────
            iccid_apn_rc = create_iccid_range_config(
                c,
                f_iccid=F_ICCID_ICCID_APN,
                t_iccid=T_ICCID_ICCID_APN,
                ip_resolution="iccid_apn",
                account_name="TestAccount",
                imsi_count=1,
                pool_id=cls.pool_ids["iccid_apn"],
            )
            cls.iccid_rc_ids["iccid_apn"] = iccid_apn_rc["id"]

            add_imsi_slot(
                c,
                iccid_range_id=iccid_apn_rc["id"],
                f_imsi=F_IMSI_ICCID_APN,
                t_imsi=T_IMSI_ICCID_APN,
                imsi_slot=1,
                ip_resolution="iccid_apn",
                pool_id=cls.pool_ids["iccid_apn"],
            )

    @classmethod
    def teardown_class(cls):
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            # Delete iccid range configs first (cascade removes imsi slots).
            for mode in ("iccid", "iccid_apn"):
                if cls.iccid_rc_ids.get(mode):
                    delete_iccid_range_config(c, cls.iccid_rc_ids[mode])

            # Delete standalone range configs.
            for mode in ("imsi", "imsi_apn"):
                if cls.rc_ids.get(mode):
                    delete_range_config(c, cls.rc_ids[mode])

            # Delete pools last.
            for pool_id in cls.pool_ids.values():
                if pool_id:
                    delete_pool(c, pool_id)

    # ── Shared cycle helper ───────────────────────────────────────────────────

    def _cycle(self, http: httpx.Client, imsi: str, pool_id: str, apn: str) -> str:
        """Perform a full first-connection → release-ips → first-connection cycle.

        Returns the re-allocated IP (guaranteed non-null by assertion).

        Step 1: first-connection — must succeed with a non-null static_ip.
        Step 2: record pool stats, then release-ips — released_count >= 1, pool
                available must increase.
        Step 3: first-connection again (same IMSI, same APN) — must return a
                non-null static_ip.  This is the KEY regression assertion.
        Step 4: pool allocated count must have gone back up.
        """
        # Step 1: initial first-connection
        r1 = http.post(
            "/profiles/first-connection",
            json={"imsi": imsi, "apn": apn, "use_case_id": USE_CASE_ID},
        )
        assert r1.status_code == 201, (
            f"[_cycle imsi={imsi}] initial first-connection failed "
            f"({r1.status_code}): {r1.text}"
        )
        sim_id = r1.json()["sim_id"]
        ip1 = r1.json().get("static_ip")
        assert ip1 is not None, (
            f"[_cycle imsi={imsi}] initial first-connection returned static_ip=null"
        )

        # Step 2: record pool stats, then release IPs
        stats_before = http.get(f"/pools/{pool_id}/stats").json()

        r_rel = http.post(f"/profiles/{sim_id}/release-ips")
        assert r_rel.status_code == 200, (
            f"[_cycle imsi={imsi}] release-ips failed ({r_rel.status_code}): {r_rel.text}"
        )
        rel_body = r_rel.json()
        assert rel_body["released_count"] >= 1, (
            f"[_cycle imsi={imsi}] release-ips returned released_count=0: {rel_body}"
        )

        stats_after_release = http.get(f"/pools/{pool_id}/stats").json()
        assert stats_after_release["available"] > stats_before["available"], (
            f"[_cycle imsi={imsi}] pool available did not increase after release: "
            f"before={stats_before}, after={stats_after_release}"
        )

        # Step 3: reconnect — KEY regression assertion
        r2 = http.post(
            "/profiles/first-connection",
            json={"imsi": imsi, "apn": apn, "use_case_id": USE_CASE_ID},
        )
        assert r2.status_code in (200, 201), (
            f"[_cycle imsi={imsi}] re-connect after release failed "
            f"({r2.status_code}): {r2.text}"
        )
        ip2 = r2.json().get("static_ip")
        assert ip2 is not None, (
            f"[_cycle imsi={imsi}] Re-allocation after release returned null IP — "
            f"first-connection did not re-allocate"
        )

        # Step 4: pool allocated count must have gone back up
        stats_after_reconnect = http.get(f"/pools/{pool_id}/stats").json()
        assert stats_after_reconnect["allocated"] >= stats_after_release["allocated"] + 1, (
            f"[_cycle imsi={imsi}] pool allocated count did not increase after re-connect: "
            f"after_release={stats_after_release}, after_reconnect={stats_after_reconnect}"
        )

        return ip2

    # ── Test methods ──────────────────────────────────────────────────────────

    def test_01_imsi_mode(self, http: httpx.Client):
        """Regression: release-ips + first-connection re-allocates in imsi mode."""
        ip = self._cycle(
            http,
            IMSI_IMSI,
            TestReleaseReconnectAllModes.pool_ids["imsi"],
            APN,
        )
        assert ip is not None, (
            "[imsi mode] Re-allocation after release returned null IP — "
            "first-connection did not re-allocate"
        )

    def test_02_imsi_apn_mode(self, http: httpx.Client):
        """Regression: release-ips + first-connection re-allocates in imsi_apn mode."""
        ip = self._cycle(
            http,
            IMSI_IMSI_APN,
            TestReleaseReconnectAllModes.pool_ids["imsi_apn"],
            APN,
        )
        assert ip is not None, (
            "[imsi_apn mode] Re-allocation after release returned null IP — "
            "first-connection did not re-allocate"
        )

    def test_03_iccid_mode(self, http: httpx.Client):
        """Regression: release-ips + first-connection re-allocates in iccid mode."""
        ip = self._cycle(
            http,
            IMSI_ICCID,
            TestReleaseReconnectAllModes.pool_ids["iccid"],
            APN,
        )
        assert ip is not None, (
            "[iccid mode] Re-allocation after release returned null IP — "
            "first-connection did not re-allocate"
        )

    def test_04_iccid_apn_mode(self, http: httpx.Client):
        """Regression: release-ips + first-connection re-allocates in iccid_apn mode."""
        ip = self._cycle(
            http,
            IMSI_ICCID_APN,
            TestReleaseReconnectAllModes.pool_ids["iccid_apn"],
            APN,
        )
        assert ip is not None, (
            "[iccid_apn mode] Re-allocation after release returned null IP — "
            "first-connection did not re-allocate"
        )
