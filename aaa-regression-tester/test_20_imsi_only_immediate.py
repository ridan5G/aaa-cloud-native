"""
test_20_imsi_only_immediate.py — Immediate provisioning for IMSI-only (no ICCID) configs.

Verifies that ICCID range configs created without f_iccid/t_iccid (skip-ICCID mode)
can use provisioning_mode="immediate", triggering _run_provision_imsi_job which:
  - Iterates over slot-1's IMSI range to derive card_count
  - Creates sim_profiles with iccid=NULL (PostgreSQL UNIQUE allows multiple NULLs)
  - Links all IMSI slots and allocates IPs per resolution type
  - DELETE cleans up all provisioned data (sim_profiles, imsi2sim, *_ips)

Six test groups (A–F):
  A — ip_resolution="imsi"     : 3 slots, 5 cards → 15 IPs, per-IMSI allocation
  B — ip_resolution="imsi_apn" : 4 slots, 5 cards, 2 APNs/slot → >= 15 IPs/APN pool
                                  (4th slot is trigger; slots 1-3 fully configured first)
  C — ip_resolution="iccid"    : 3 slots, 5 cards → 5 IPs, card-level (slot 1 only)
  D — ip_resolution="iccid_apn": 3 slots, 5 cards, 2 APNs on slot 1 → 5 IPs/APN pool
  E — deletion                 : imsi-only immediate config is fully cleaned up on DELETE
  F — validation               : cross-slot cardinality mismatch → 400

Resources
─────────
  Module 20 → IMSI prefix 27877 20 xxxxxxxx  (no conflict with other modules)

  Subnets (all 119.175.230.x / 119.175.231.x):
    A  — 119.175.230.0/24   (253 usable; 15 needed for imsi)
    B  — 119.175.231.0/24   (internet APN pool)
         119.175.232.0/24   (IMS APN pool)
    C  — 119.175.233.0/24   (5 needed for iccid)
    D  — 119.175.234.0/24   (internet APN pool)
         119.175.235.0/24   (IMS APN pool)
    E  — 119.175.236.0/24   (15 needed for deletion test)
    F  — 119.175.237.0/28   (tiny; no IPs actually allocated for validation test)

  IMSI ranges (5-card groups, 3 slots per group):
    A: S1=278772001000000–278772001000004  S2=278772002000000–278772002000004
       S3=278772003000000–278772003000004
    B: S1=278772001010000–278772001010004  S2=278772002010000–278772002010004
       S3=278772003010000–278772003010004  S4=278772004010000–278772004010004
    C: S1=278772001020000–278772001020004  S2=278772002020000–278772002020004
       S3=278772003020000–278772003020004
    D: S1=278772001030000–278772001030004  S2=278772002030000–278772002030004
       S3=278772003030000–278772003030004
    E: S1=278772001040000–278772001040004  S2=278772002040000–278772002040004
       S3=278772003040000–278772003040004
    F: S1=278772009000000–278772009000004 (5 cards)
       S2=278772009100000–278772009100002 (3 cards — mismatch)
"""
import asyncio
import os

import asyncpg
import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID, make_imsi, poll_until
from fixtures.pools import create_pool, delete_pool, get_pool_stats, _force_clear_range_profiles
from fixtures.range_configs import (
    create_iccid_range_config,
    add_imsi_slot,
    add_imsi_slot_apn_pool,
    delete_iccid_range_config,
)

MODULE = 20
CARDS  = 5

APN_INTERNET = "internet.operator.com"
APN_IMS      = "ims.operator.com"

# ── Subnets ───────────────────────────────────────────────────────────────────
SUBNET_A         = "119.175.230.0/24"
SUBNET_B_INET    = "119.175.231.0/24"
SUBNET_B_IMS     = "119.175.232.0/24"
SUBNET_C         = "119.175.233.0/24"
SUBNET_D_INET    = "119.175.234.0/24"
SUBNET_D_IMS     = "119.175.235.0/24"
SUBNET_E         = "119.175.236.0/24"
SUBNET_F         = "119.175.237.0/28"

# ── IMSI ranges (slot_group * 1_000_000 + class_offset) ──────────────────────
# Class A — imsi resolution
F_A_S1 = make_imsi(MODULE, 1_000_000);  T_A_S1 = make_imsi(MODULE, 1_000_004)
F_A_S2 = make_imsi(MODULE, 2_000_000);  T_A_S2 = make_imsi(MODULE, 2_000_004)
F_A_S3 = make_imsi(MODULE, 3_000_000);  T_A_S3 = make_imsi(MODULE, 3_000_004)

# Class B — imsi_apn resolution
F_B_S1 = make_imsi(MODULE, 1_010_000);  T_B_S1 = make_imsi(MODULE, 1_010_004)
F_B_S2 = make_imsi(MODULE, 2_010_000);  T_B_S2 = make_imsi(MODULE, 2_010_004)
F_B_S3 = make_imsi(MODULE, 3_010_000);  T_B_S3 = make_imsi(MODULE, 3_010_004)
F_B_S4 = make_imsi(MODULE, 4_010_000);  T_B_S4 = make_imsi(MODULE, 4_010_004)

# Class C — iccid resolution
F_C_S1 = make_imsi(MODULE, 1_020_000);  T_C_S1 = make_imsi(MODULE, 1_020_004)
F_C_S2 = make_imsi(MODULE, 2_020_000);  T_C_S2 = make_imsi(MODULE, 2_020_004)
F_C_S3 = make_imsi(MODULE, 3_020_000);  T_C_S3 = make_imsi(MODULE, 3_020_004)

# Class D — iccid_apn resolution
F_D_S1 = make_imsi(MODULE, 1_030_000);  T_D_S1 = make_imsi(MODULE, 1_030_004)
F_D_S2 = make_imsi(MODULE, 2_030_000);  T_D_S2 = make_imsi(MODULE, 2_030_004)
F_D_S3 = make_imsi(MODULE, 3_030_000);  T_D_S3 = make_imsi(MODULE, 3_030_004)

# Class E — deletion
F_E_S1 = make_imsi(MODULE, 1_040_000);  T_E_S1 = make_imsi(MODULE, 1_040_004)
F_E_S2 = make_imsi(MODULE, 2_040_000);  T_E_S2 = make_imsi(MODULE, 2_040_004)
F_E_S3 = make_imsi(MODULE, 3_040_000);  T_E_S3 = make_imsi(MODULE, 3_040_004)

# Class F — validation (cardinality mismatch)
F_F_S1 = make_imsi(MODULE, 9_000_000);  T_F_S1 = make_imsi(MODULE, 9_000_004)   # 5 cards
F_F_S2 = make_imsi(MODULE, 9_100_000);  T_F_S2 = make_imsi(MODULE, 9_100_002)   # 3 cards — mismatch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=30.0,
    )


def _wait_for_job(http: httpx.Client, job_id: str, timeout: float = 300.0) -> dict:
    """Poll GET /jobs/{job_id} until terminal status."""
    return poll_until(
        fn=lambda: http.get(f"/jobs/{job_id}").json(),
        condition=lambda r: r.get("status") in ("completed", "completed_with_errors", "failed"),
        timeout=timeout,
        interval=3.0,
        label=f"job {job_id}",
    )


_DB_URL = os.environ.get("DB_URL", "")


def _db_count(query: str, *args) -> int:
    """Run a COUNT query directly against the DB.  Returns -1 if DB_URL is not set."""
    if not _DB_URL:
        return -1

    async def _run():
        conn = await asyncpg.connect(_DB_URL)
        try:
            return await conn.fetchval(query, *args)
        finally:
            await conn.close()

    return asyncio.run(_run())


# ══════════════════════════════════════════════════════════════════════════════
# A — ip_resolution="imsi"
# ══════════════════════════════════════════════════════════════════════════════

class TestImsiOnlyImmediate_IMSI:
    """Tests A.1–A.9: IMSI-only immediate provisioning, ip_resolution='imsi'."""

    pool_id: str = ""
    range_id: int = 0
    job_id: str   = ""

    @classmethod
    def setup_class(cls):
        for f, t in [(F_A_S1, T_A_S1), (F_A_S2, T_A_S2), (F_A_S3, T_A_S3)]:
            _force_clear_range_profiles(f, t)
        with _new_client() as c:
            pool = create_pool(c, subnet=SUBNET_A, pool_name="t20a-pool",
                               account_name="TestAccount", replace_on_conflict=True)
            cls.pool_id = pool["pool_id"]

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_iccid_range_config(c, cls.range_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # A.1 ─────────────────────────────────────────────────────────────────────
    def test_01_create_config_no_iccid(self, http: httpx.Client):
        """POST /iccid-range-configs without f_iccid/t_iccid + immediate → 201, no job_id."""
        rc = create_iccid_range_config(
            http,
            ip_resolution="imsi",
            imsi_count=3,
            pool_id=self.pool_id,
            provisioning_mode="immediate",
        )
        assert "id" in rc, f"Missing id: {rc}"
        assert "job_id" not in rc, f"job_id should not appear at config creation: {rc}"
        TestImsiOnlyImmediate_IMSI.range_id = rc["id"]

    # A.2 ─────────────────────────────────────────────────────────────────────
    def test_02_add_slot1_no_job(self, http: httpx.Client):
        """Add slot 1 of 3 → 201, no job_id (not all slots present yet)."""
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_A_S1, t_imsi=T_A_S1,
                            imsi_slot=1, ip_resolution="imsi")
        assert "job_id" not in res, f"Unexpected job_id after slot 1/3: {res}"

    # A.3 ─────────────────────────────────────────────────────────────────────
    def test_03_add_slot2_no_job(self, http: httpx.Client):
        """Add slot 2 of 3 → 201, still no job_id."""
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_A_S2, t_imsi=T_A_S2,
                            imsi_slot=2, ip_resolution="imsi")
        assert "job_id" not in res, f"Unexpected job_id after slot 2/3: {res}"
        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] == 0, f"Pool should be untouched at slot 2/3: {stats}"

    # A.4 ─────────────────────────────────────────────────────────────────────
    def test_04_add_slot3_triggers_job(self, http: httpx.Client):
        """Add last slot (3 of 3) → job_id returned (provisioning triggered)."""
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_A_S3, t_imsi=T_A_S3,
                            imsi_slot=3, ip_resolution="imsi")
        assert "job_id" in res, f"Expected job_id after last slot: {res}"
        TestImsiOnlyImmediate_IMSI.job_id = res["job_id"]

    # A.5 ─────────────────────────────────────────────────────────────────────
    def test_05_job_completes(self, http: httpx.Client):
        """Bulk job reaches 'completed' with processed=CARDS, failed=0.
        Range config is marked 'provisioned' and job links back to it."""
        job = _wait_for_job(http, self.job_id)
        assert job["status"] == "completed", f"Job status={job['status']}: {job.get('errors')}"
        assert job["processed"] == CARDS, f"Expected {CARDS} processed: {job}"
        assert job["failed"] == 0, f"Expected 0 failed: {job}"
        assert job.get("range_config_id") == self.range_id, f"Job missing range_config_id link: {job}"
        rc = http.get(f"/iccid-range-configs/{self.range_id}").json()
        assert rc.get("status") == "provisioned", f"Range config not marked provisioned: {rc}"

    # A.6 ─────────────────────────────────────────────────────────────────────
    def test_06_pool_shows_allocated(self, http: httpx.Client):
        """Pool has CARDS×3 allocated IPs (one per IMSI)."""
        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] >= CARDS * 3, (
            f"Expected >= {CARDS * 3} allocated IPs: {stats}"
        )

    # A.7 ─────────────────────────────────────────────────────────────────────
    def test_07_lookup_slot1_returns_ip(self, http: httpx.Client, lookup_http: httpx.Client):
        """GET /lookup for slot-1 IMSI → 200, static_ip present (no first-connection needed)."""
        r = lookup_http.get("/lookup", params={
            "imsi": F_A_S1, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200, f"Slot-1 lookup failed: {r.status_code} {r.text}"
        assert r.json().get("static_ip") is not None, f"No static_ip: {r.json()}"

    # A.8 ─────────────────────────────────────────────────────────────────────
    def test_08_lookup_slot2_returns_ip(self, http: httpx.Client, lookup_http: httpx.Client):
        """GET /lookup for slot-2 IMSI → 200, distinct IP from slot 1."""
        r = lookup_http.get("/lookup", params={
            "imsi": F_A_S2, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200, f"Slot-2 lookup failed: {r.status_code} {r.text}"
        assert r.json().get("static_ip") is not None

    # A.9 ─────────────────────────────────────────────────────────────────────
    def test_09_lookup_slot3_returns_ip(self, http: httpx.Client, lookup_http: httpx.Client):
        """GET /lookup for slot-3 IMSI → 200, static_ip present."""
        r = lookup_http.get("/lookup", params={
            "imsi": F_A_S3, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200, f"Slot-3 lookup failed: {r.status_code} {r.text}"
        assert r.json().get("static_ip") is not None


# ══════════════════════════════════════════════════════════════════════════════
# B — ip_resolution="imsi_apn"
# ══════════════════════════════════════════════════════════════════════════════

class TestImsiOnlyImmediate_IMSI_APN:
    """Tests B.1–B.12: IMSI-only immediate, ip_resolution='imsi_apn', 2 APNs per slot.

    Uses 4 slots (imsi_count=4) so that slots 1-3 have APN pools fully configured
    before slot 4 triggers the background job — eliminating the race condition where
    the job could process a card before slot 3's APN pools were committed.
    """

    pool_internet_id: str = ""
    pool_ims_id:      str = ""
    range_id:         int = 0
    job_id:           str = ""

    @classmethod
    def setup_class(cls):
        for f, t in [(F_B_S1, T_B_S1), (F_B_S2, T_B_S2), (F_B_S3, T_B_S3), (F_B_S4, T_B_S4)]:
            _force_clear_range_profiles(f, t)
        with _new_client() as c:
            p1 = create_pool(c, subnet=SUBNET_B_INET, pool_name="t20b-internet",
                             account_name="TestAccount", replace_on_conflict=True)
            p2 = create_pool(c, subnet=SUBNET_B_IMS, pool_name="t20b-ims",
                             account_name="TestAccount", replace_on_conflict=True)
            cls.pool_internet_id = p1["pool_id"]
            cls.pool_ims_id      = p2["pool_id"]

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_iccid_range_config(c, cls.range_id)
            for pid in (cls.pool_internet_id, cls.pool_ims_id):
                if pid:
                    delete_pool(c, pid)

    # B.1
    def test_01_create_config(self, http: httpx.Client):
        """Create IMSI-only immediate config, ip_resolution=imsi_apn, imsi_count=4.

        Four slots so slots 1-3 can be fully configured (with APN pools) before
        slot 4 triggers the background job — no race condition on APN pool reads.
        """
        rc = create_iccid_range_config(
            http,
            ip_resolution="imsi_apn",
            imsi_count=4,
            provisioning_mode="immediate",
        )
        assert "id" in rc
        TestImsiOnlyImmediate_IMSI_APN.range_id = rc["id"]

    # B.2
    def test_02_add_slot1(self, http: httpx.Client):
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_B_S1, t_imsi=T_B_S1,
                            imsi_slot=1, ip_resolution="imsi_apn")
        assert "job_id" not in res

    # B.3
    def test_03_add_apn_pools_slot1(self, http: httpx.Client):
        """Add both APN pools to slot 1."""
        add_imsi_slot_apn_pool(http, iccid_range_id=self.range_id, slot=1,
                               apn=APN_INTERNET, pool_id=self.pool_internet_id)
        add_imsi_slot_apn_pool(http, iccid_range_id=self.range_id, slot=1,
                               apn=APN_IMS, pool_id=self.pool_ims_id)

    # B.4
    def test_04_add_slot2(self, http: httpx.Client):
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_B_S2, t_imsi=T_B_S2,
                            imsi_slot=2, ip_resolution="imsi_apn")
        assert "job_id" not in res

    # B.5
    def test_05_add_apn_pools_slot2(self, http: httpx.Client):
        add_imsi_slot_apn_pool(http, iccid_range_id=self.range_id, slot=2,
                               apn=APN_INTERNET, pool_id=self.pool_internet_id)
        add_imsi_slot_apn_pool(http, iccid_range_id=self.range_id, slot=2,
                               apn=APN_IMS, pool_id=self.pool_ims_id)

    # B.6
    def test_06_add_slot3_and_apn_pools(self, http: httpx.Client):
        """Add slot 3 (still 1 short of imsi_count=4 — no job yet) then its APN pools."""
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_B_S3, t_imsi=T_B_S3,
                            imsi_slot=3, ip_resolution="imsi_apn")
        assert "job_id" not in res, f"Unexpected early job trigger at slot 3/4: {res}"
        add_imsi_slot_apn_pool(http, iccid_range_id=self.range_id, slot=3,
                               apn=APN_INTERNET, pool_id=self.pool_internet_id)
        add_imsi_slot_apn_pool(http, iccid_range_id=self.range_id, slot=3,
                               apn=APN_IMS, pool_id=self.pool_ims_id)

    # B.7
    def test_07_add_slot4_triggers_job(self, http: httpx.Client):
        """Add last slot (4 of 4) → job triggered; APN pools for slots 1-3 already set."""
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_B_S4, t_imsi=T_B_S4,
                            imsi_slot=4, ip_resolution="imsi_apn")
        assert "job_id" in res, f"Expected job_id after last slot: {res}"
        TestImsiOnlyImmediate_IMSI_APN.job_id = res["job_id"]
        # APN pools for slot 4 added after trigger (best-effort; slots 1-3 guarantee >= CARDS*3)
        add_imsi_slot_apn_pool(http, iccid_range_id=self.range_id, slot=4,
                               apn=APN_INTERNET, pool_id=self.pool_internet_id)
        add_imsi_slot_apn_pool(http, iccid_range_id=self.range_id, slot=4,
                               apn=APN_IMS, pool_id=self.pool_ims_id)

    # B.8
    def test_08_job_completes(self, http: httpx.Client):
        job = _wait_for_job(http, self.job_id)
        assert job["status"] == "completed", f"Job status={job['status']}: {job.get('errors')}"
        assert job["processed"] == CARDS
        assert job["failed"] == 0
        assert job.get("range_config_id") == self.range_id, f"Job missing range_config_id link: {job}"
        rc = http.get(f"/iccid-range-configs/{self.range_id}").json()
        assert rc.get("status") == "provisioned", f"Range config not marked provisioned: {rc}"

    # B.9
    def test_09_internet_pool_allocated(self, http: httpx.Client):
        """Internet pool has >= CARDS×3 IPs allocated (slots 1-3 are race-free)."""
        stats = get_pool_stats(http, self.pool_internet_id)
        assert stats["allocated"] >= CARDS * 3, (
            f"Expected >= {CARDS * 3} internet IPs: {stats}"
        )

    # B.10
    def test_10_ims_pool_allocated(self, http: httpx.Client):
        """IMS pool has >= CARDS×3 IPs allocated (slots 1-3 are race-free)."""
        stats = get_pool_stats(http, self.pool_ims_id)
        assert stats["allocated"] >= CARDS * 3, (
            f"Expected >= {CARDS * 3} IMS IPs: {stats}"
        )

    # B.11
    def test_11_lookup_internet_apn(self, http: httpx.Client, lookup_http: httpx.Client):
        """Lookup slot-1 IMSI with internet APN → 200, IP from internet pool."""
        r = lookup_http.get("/lookup", params={
            "imsi": F_B_S1, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200
        assert r.json().get("static_ip") is not None

    # B.12
    def test_12_lookup_ims_apn(self, http: httpx.Client, lookup_http: httpx.Client):
        """Lookup slot-1 IMSI with IMS APN → 200, different IP from IMS pool."""
        r_inet = lookup_http.get("/lookup", params={
            "imsi": F_B_S1, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        r_ims = lookup_http.get("/lookup", params={
            "imsi": F_B_S1, "apn": APN_IMS, "use_case_id": USE_CASE_ID,
        })
        assert r_ims.status_code == 200
        ip_inet = r_inet.json().get("static_ip")
        ip_ims  = r_ims.json().get("static_ip")
        assert ip_ims is not None
        assert ip_inet != ip_ims, f"Expected different IPs per APN: inet={ip_inet} ims={ip_ims}"


# ══════════════════════════════════════════════════════════════════════════════
# C — ip_resolution="iccid"
# ══════════════════════════════════════════════════════════════════════════════

class TestImsiOnlyImmediate_ICCID:
    """Tests C.1–C.8: IMSI-only immediate, ip_resolution='iccid', card-level IP from slot 1."""

    pool_id:  str = ""
    range_id: int = 0
    job_id:   str = ""

    @classmethod
    def setup_class(cls):
        for f, t in [(F_C_S1, T_C_S1), (F_C_S2, T_C_S2), (F_C_S3, T_C_S3)]:
            _force_clear_range_profiles(f, t)
        with _new_client() as c:
            pool = create_pool(c, subnet=SUBNET_C, pool_name="t20c-pool",
                               account_name="TestAccount", replace_on_conflict=True)
            cls.pool_id = pool["pool_id"]

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_iccid_range_config(c, cls.range_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # C.1
    def test_01_create_config(self, http: httpx.Client):
        rc = create_iccid_range_config(
            http,
            ip_resolution="iccid",
            imsi_count=3,
            pool_id=self.pool_id,
            provisioning_mode="immediate",
        )
        assert "id" in rc
        TestImsiOnlyImmediate_ICCID.range_id = rc["id"]

    # C.2
    def test_02_add_slot1_no_job(self, http: httpx.Client):
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_C_S1, t_imsi=T_C_S1,
                            imsi_slot=1, ip_resolution="iccid",
                            pool_id=self.pool_id)
        assert "job_id" not in res

    # C.3
    def test_03_add_slot2_no_job(self, http: httpx.Client):
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_C_S2, t_imsi=T_C_S2,
                            imsi_slot=2, ip_resolution="iccid")
        assert "job_id" not in res

    # C.4
    def test_04_add_slot3_triggers_job(self, http: httpx.Client):
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_C_S3, t_imsi=T_C_S3,
                            imsi_slot=3, ip_resolution="iccid")
        assert "job_id" in res, f"Expected job_id after last slot: {res}"
        TestImsiOnlyImmediate_ICCID.job_id = res["job_id"]

    # C.5
    def test_05_job_completes(self, http: httpx.Client):
        """Processed=CARDS (5): one IP per card, from slot 1 only."""
        job = _wait_for_job(http, self.job_id)
        assert job["status"] == "completed", f"Job failed: {job.get('errors')}"
        assert job["processed"] == CARDS
        assert job["failed"] == 0
        assert job.get("range_config_id") == self.range_id, f"Job missing range_config_id link: {job}"
        rc = http.get(f"/iccid-range-configs/{self.range_id}").json()
        assert rc.get("status") == "provisioned", f"Range config not marked provisioned: {rc}"

    # C.6
    def test_06_pool_shows_card_level_allocation(self, http: httpx.Client):
        """Only CARDS IPs allocated (one per card, not per slot)."""
        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] == CARDS, (
            f"Expected {CARDS} allocated IPs for iccid mode: {stats}"
        )

    # C.7
    def test_07_lookup_slot1(self, http: httpx.Client, lookup_http: httpx.Client):
        """Lookup slot-1 IMSI → 200, static_ip present."""
        r = lookup_http.get("/lookup", params={
            "imsi": F_C_S1, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200, f"Slot-1 lookup: {r.status_code} {r.text}"
        assert r.json().get("static_ip") is not None
        TestImsiOnlyImmediate_ICCID._card0_ip = r.json()["static_ip"]

    # C.8
    def test_08_all_slots_same_card_ip(self, http: httpx.Client, lookup_http: httpx.Client):
        """Slot-2 and slot-3 IMSIs (same card offset 0) share the same IP as slot 1."""
        r2 = lookup_http.get("/lookup", params={
            "imsi": F_C_S2, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        r3 = lookup_http.get("/lookup", params={
            "imsi": F_C_S3, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        assert r2.status_code == 200
        assert r3.status_code == 200
        ip1 = getattr(TestImsiOnlyImmediate_ICCID, "_card0_ip", None)
        ip2 = r2.json().get("static_ip")
        ip3 = r3.json().get("static_ip")
        assert ip2 is not None and ip3 is not None
        assert ip1 == ip2 == ip3, (
            f"iccid mode: expected same IP for all slots on card 0: {ip1}, {ip2}, {ip3}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# D — ip_resolution="iccid_apn"
# ══════════════════════════════════════════════════════════════════════════════

class TestImsiOnlyImmediate_ICCID_APN:
    """Tests D.1–D.11: IMSI-only immediate, ip_resolution='iccid_apn'.

    APN pools are added to slot 1 only (card-level allocation).
    All IMSI slots on the same card get the same IP for a given APN.
    """

    pool_internet_id: str = ""
    pool_ims_id:      str = ""
    range_id:         int = 0
    job_id:           str = ""

    @classmethod
    def setup_class(cls):
        for f, t in [(F_D_S1, T_D_S1), (F_D_S2, T_D_S2), (F_D_S3, T_D_S3)]:
            _force_clear_range_profiles(f, t)
        with _new_client() as c:
            p1 = create_pool(c, subnet=SUBNET_D_INET, pool_name="t20d-internet",
                             account_name="TestAccount", replace_on_conflict=True)
            p2 = create_pool(c, subnet=SUBNET_D_IMS, pool_name="t20d-ims",
                             account_name="TestAccount", replace_on_conflict=True)
            cls.pool_internet_id = p1["pool_id"]
            cls.pool_ims_id      = p2["pool_id"]

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_iccid_range_config(c, cls.range_id)
            for pid in (cls.pool_internet_id, cls.pool_ims_id):
                if pid:
                    delete_pool(c, pid)

    # D.1
    def test_01_create_config(self, http: httpx.Client):
        rc = create_iccid_range_config(
            http,
            ip_resolution="iccid_apn",
            imsi_count=3,
            provisioning_mode="immediate",
        )
        assert "id" in rc
        TestImsiOnlyImmediate_ICCID_APN.range_id = rc["id"]

    # D.2
    def test_02_add_slot1(self, http: httpx.Client):
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_D_S1, t_imsi=T_D_S1,
                            imsi_slot=1, ip_resolution="iccid_apn",
                            pool_id=self.pool_internet_id)
        assert "job_id" not in res

    # D.3
    def test_03_add_apn_pools_slot1(self, http: httpx.Client):
        """Card-level APN pools: add to slot 1 — these define IPs for all slots on each card."""
        add_imsi_slot_apn_pool(http, iccid_range_id=self.range_id, slot=1,
                               apn=APN_INTERNET, pool_id=self.pool_internet_id)
        add_imsi_slot_apn_pool(http, iccid_range_id=self.range_id, slot=1,
                               apn=APN_IMS, pool_id=self.pool_ims_id)

    # D.4
    def test_04_add_slot2_no_job(self, http: httpx.Client):
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_D_S2, t_imsi=T_D_S2,
                            imsi_slot=2, ip_resolution="iccid_apn")
        assert "job_id" not in res

    # D.5
    def test_05_add_slot3_triggers_job(self, http: httpx.Client):
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_D_S3, t_imsi=T_D_S3,
                            imsi_slot=3, ip_resolution="iccid_apn")
        assert "job_id" in res, f"Expected job_id after last slot: {res}"
        TestImsiOnlyImmediate_ICCID_APN.job_id = res["job_id"]

    # D.6
    def test_06_job_completes(self, http: httpx.Client):
        job = _wait_for_job(http, self.job_id)
        assert job["status"] == "completed", f"Job failed: {job.get('errors')}"
        assert job["processed"] == CARDS
        assert job["failed"] == 0
        assert job.get("range_config_id") == self.range_id, f"Job missing range_config_id link: {job}"
        rc = http.get(f"/iccid-range-configs/{self.range_id}").json()
        assert rc.get("status") == "provisioned", f"Range config not marked provisioned: {rc}"

    # D.7
    def test_07_internet_pool_has_card_level_ips(self, http: httpx.Client):
        """Internet pool has CARDS IPs (one per card, not per slot)."""
        stats = get_pool_stats(http, self.pool_internet_id)
        assert stats["allocated"] == CARDS, (
            f"Expected {CARDS} internet IPs for iccid_apn mode: {stats}"
        )

    # D.8
    def test_08_ims_pool_has_card_level_ips(self, http: httpx.Client):
        stats = get_pool_stats(http, self.pool_ims_id)
        assert stats["allocated"] == CARDS, (
            f"Expected {CARDS} IMS IPs for iccid_apn mode: {stats}"
        )

    # D.9
    def test_09_lookup_slot1_internet(self, http: httpx.Client, lookup_http: httpx.Client):
        """Slot-1 IMSI with internet APN → 200, IP from internet pool."""
        r = lookup_http.get("/lookup", params={
            "imsi": F_D_S1, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert r.json().get("static_ip") is not None
        TestImsiOnlyImmediate_ICCID_APN._card0_inet_ip = r.json()["static_ip"]

    # D.10
    def test_10_lookup_slot2_same_card_ip(self, http: httpx.Client, lookup_http: httpx.Client):
        """Slot-2 IMSI (same card offset 0) → same IP as slot-1 for internet APN."""
        r = lookup_http.get("/lookup", params={
            "imsi": F_D_S2, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200
        ip1 = getattr(TestImsiOnlyImmediate_ICCID_APN, "_card0_inet_ip", None)
        ip2 = r.json().get("static_ip")
        assert ip2 is not None
        assert ip1 == ip2, f"iccid_apn: expected same card IP: slot1={ip1} slot2={ip2}"

    # D.11
    def test_11_lookup_ims_apn_different_ip(self, http: httpx.Client, lookup_http: httpx.Client):
        """IMS APN → different IP from internet APN (separate pool)."""
        r = lookup_http.get("/lookup", params={
            "imsi": F_D_S1, "apn": APN_IMS, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200
        ip_ims  = r.json().get("static_ip")
        ip_inet = getattr(TestImsiOnlyImmediate_ICCID_APN, "_card0_inet_ip", None)
        assert ip_ims is not None
        assert ip_ims != ip_inet, f"Expected different IPs: inet={ip_inet} ims={ip_ims}"


# ══════════════════════════════════════════════════════════════════════════════
# E — Deletion: all provisioned data cleaned up on DELETE /iccid-range-configs
# ══════════════════════════════════════════════════════════════════════════════

class TestImsiOnlyImmediateDeletion:
    """Tests E.1–E.9: DELETE /iccid-range-configs removes sim_profiles, IPs, imsi2sim rows."""

    pool_id:       str = ""
    range_id:      int = 0
    orig_range_id: int = 0   # preserved after delete for 404 check

    @classmethod
    def setup_class(cls):
        for f, t in [(F_E_S1, T_E_S1), (F_E_S2, T_E_S2), (F_E_S3, T_E_S3)]:
            _force_clear_range_profiles(f, t)
        with _new_client() as c:
            pool = create_pool(c, subnet=SUBNET_E, pool_name="t20e-pool",
                               account_name="TestAccount", replace_on_conflict=True)
            cls.pool_id = pool["pool_id"]
            # Create config + add all 3 slots; last slot triggers job
            rc = create_iccid_range_config(
                c,
                ip_resolution="imsi",
                imsi_count=3,
                pool_id=pool["pool_id"],
                provisioning_mode="immediate",
            )
            cls.range_id = rc["id"]
            cls.orig_range_id = rc["id"]
            add_imsi_slot(c, iccid_range_id=cls.range_id,
                          f_imsi=F_E_S1, t_imsi=T_E_S1,
                          imsi_slot=1, ip_resolution="imsi")
            add_imsi_slot(c, iccid_range_id=cls.range_id,
                          f_imsi=F_E_S2, t_imsi=T_E_S2,
                          imsi_slot=2, ip_resolution="imsi")
            res = add_imsi_slot(c, iccid_range_id=cls.range_id,
                                f_imsi=F_E_S3, t_imsi=T_E_S3,
                                imsi_slot=3, ip_resolution="imsi")
            # Wait for job to complete so provisioned data is in DB
            if "job_id" in res:
                poll_until(
                    fn=lambda: c.get(f"/jobs/{res['job_id']}").json(),
                    condition=lambda r: r.get("status") in (
                        "completed", "completed_with_errors", "failed"
                    ),
                    timeout=300.0,
                    interval=3.0,
                    label="setup E provisioning job",
                )

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_iccid_range_config(c, cls.range_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # E.1 ─────────────────────────────────────────────────────────────────────
    def test_01_config_exists_with_3_slots(self, http: httpx.Client):
        """Sanity: config is present with 3 IMSI slots before deletion."""
        r = http.get(f"/iccid-range-configs/{self.range_id}")
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert len(body.get("imsi_ranges", [])) == 3

    # E.2 ─────────────────────────────────────────────────────────────────────
    def test_02_pool_shows_allocated(self, http: httpx.Client):
        """Pool has CARDS×3 IPs allocated before deletion."""
        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] >= CARDS * 3, f"Expected provisioned IPs: {stats}"

    # E.3 ─────────────────────────────────────────────────────────────────────
    def test_03_delete_config(self, http: httpx.Client):
        """DELETE /iccid-range-configs/{id} → 204."""
        r = http.delete(f"/iccid-range-configs/{self.range_id}")
        assert r.status_code == 204, f"Delete failed: {r.status_code} {r.text}"
        TestImsiOnlyImmediateDeletion.range_id = 0

    # E.4 ─────────────────────────────────────────────────────────────────────
    def test_04_config_is_gone(self, http: httpx.Client):
        """GET /iccid-range-configs/{id} → 404 after deletion."""
        r = http.get(f"/iccid-range-configs/{self.orig_range_id}")
        assert r.status_code == 404, f"Expected 404 after delete: {r.status_code} {r.text}"

    # E.5 ─────────────────────────────────────────────────────────────────────
    def test_05_ips_returned_to_pool(self, http: httpx.Client):
        """All IPs are returned to the pool (allocated = 0)."""
        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] == 0, (
            f"Expected 0 allocated after delete, got {stats['allocated']}"
        )

    # E.6 ─────────────────────────────────────────────────────────────────────
    def test_06_db_imsi2sim_cleared(self):
        """[DB_URL required] imsi2sim rows for all provisioned IMSIs are gone."""
        if not _DB_URL:
            pytest.skip("DB_URL not set — skipping direct DB assertion")
        all_imsis = (
            [make_imsi(MODULE, 1_040_000 + i) for i in range(CARDS)]
            + [make_imsi(MODULE, 2_040_000 + i) for i in range(CARDS)]
            + [make_imsi(MODULE, 3_040_000 + i) for i in range(CARDS)]
        )
        count = _db_count(
            "SELECT COUNT(*) FROM imsi2sim WHERE imsi = ANY($1::text[])", all_imsis
        )
        assert count == 0, f"Expected 0 imsi2sim rows after delete, got {count}"

    # E.7 ─────────────────────────────────────────────────────────────────────
    def test_07_db_imsi_apn_ips_cleared(self):
        """[DB_URL required] imsi_apn_ips rows for all provisioned IMSIs are gone."""
        if not _DB_URL:
            pytest.skip("DB_URL not set — skipping direct DB assertion")
        all_imsis = (
            [make_imsi(MODULE, 1_040_000 + i) for i in range(CARDS)]
            + [make_imsi(MODULE, 2_040_000 + i) for i in range(CARDS)]
            + [make_imsi(MODULE, 3_040_000 + i) for i in range(CARDS)]
        )
        count = _db_count(
            "SELECT COUNT(*) FROM imsi_apn_ips WHERE imsi = ANY($1::text[])", all_imsis
        )
        assert count == 0, f"Expected 0 imsi_apn_ips after delete, got {count}"

    # E.8 ─────────────────────────────────────────────────────────────────────
    def test_08_lookup_returns_no_ip(self, http: httpx.Client, lookup_http: httpx.Client):
        """Lookup for a deleted IMSI → 404 (SIM gone from lookup service)."""
        r = lookup_http.get("/lookup", params={
            "imsi": F_E_S1, "apn": APN_INTERNET, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 404, (
            f"Expected 404 after config delete, got {r.status_code}: {r.text}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# F — Validation: cross-slot cardinality mismatch → 400
# ══════════════════════════════════════════════════════════════════════════════

class TestImsiOnlyImmediateValidation:
    """Tests F.1–F.3: cardinality mismatch across slots → 400 validation_failed."""

    pool_id:  str = ""
    range_id: int = 0

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            pool = create_pool(c, subnet=SUBNET_F, pool_name="t20f-pool",
                               account_name="TestAccount", replace_on_conflict=True)
            cls.pool_id = pool["pool_id"]

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_iccid_range_config(c, cls.range_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # F.1 ─────────────────────────────────────────────────────────────────────
    def test_01_create_config(self, http: httpx.Client):
        """Create IMSI-only immediate config with imsi_count=2."""
        rc = create_iccid_range_config(
            http,
            ip_resolution="imsi",
            imsi_count=2,
            pool_id=self.pool_id,
            provisioning_mode="immediate",
        )
        assert "id" in rc
        TestImsiOnlyImmediateValidation.range_id = rc["id"]

    # F.2 ─────────────────────────────────────────────────────────────────────
    def test_02_add_slot1_five_cards(self, http: httpx.Client):
        """Add slot 1 with 5-card range (cardinality=4) → 201."""
        res = add_imsi_slot(http, iccid_range_id=self.range_id,
                            f_imsi=F_F_S1, t_imsi=T_F_S1,
                            imsi_slot=1, ip_resolution="imsi",
                            pool_id=self.pool_id)
        assert "job_id" not in res

    # F.3 ─────────────────────────────────────────────────────────────────────
    def test_03_slot2_cardinality_mismatch_rejected(self, http: httpx.Client):
        """Add slot 2 with 3-card range (cardinality=2 ≠ 4) → 400 validation_failed."""
        resp = http.post(
            f"/iccid-range-configs/{self.range_id}/imsi-slots",
            json={
                "f_imsi":        F_F_S2,
                "t_imsi":        T_F_S2,
                "imsi_slot":     2,
                "ip_resolution": "imsi",
                "pool_id":       self.pool_id,
            },
        )
        assert resp.status_code == 400, (
            f"Expected 400 for cardinality mismatch, got {resp.status_code}: {resp.text}"
        )
        detail = resp.json()
        assert detail.get("error") == "validation_failed", f"Unexpected error: {detail}"
        messages = [d.get("message", "") for d in detail.get("details", [])]
        assert any("cardinality" in m for m in messages), (
            f"Expected 'cardinality' in error message: {messages}"
        )
