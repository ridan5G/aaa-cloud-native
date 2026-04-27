"""
test_17_immediate_provisioning.py — Immediate provisioning mode for range configs.

Verifies that:
  - POST /range-configs with provisioning_mode="immediate" returns 202 + job_id
  - Background job provisions all SIMs and updates pool allocation correctly
  - GET /v1/lookup returns IP without requiring first-connection
  - POST /first-connection is idempotent for already-provisioned SIMs
  - DELETE range config returns IPs to pool and hard-deletes profiles
  - Invalid provisioning_mode value → 400 validation_failed
  - Pool capacity check blocks creation when pool is too small → 503

  - ICCID ranges: provisioning triggers when last IMSI slot is added
  - Slot response includes job_id on last-slot add
  - DELETE ICCID range cleans up profiles and IPs

Resources
─────────
  Module 17 → IMSI prefix 27877 17 xxxxxxxx  (no conflict with other modules)

  Single-IMSI tests:
    pool subnet:  100.65.195.0/24
    F_IMSI        278771700000001
    T_IMSI        278771700000005   (5 SIMs)

  ICCID range tests:
    pool subnet:  100.65.196.0/24
    F_ICCID       8944501170000000001
    T_ICCID       8944501170000000003  (3 cards × 2 slots)
    Slot 1:  F_IMSI_S1=278771700010001  T_IMSI_S1=278771700010003
    Slot 2:  F_IMSI_S2=278771700020001  T_IMSI_S2=278771700020003

  Capacity-check test:
    tiny pool:  100.65.197.0/30  (2 usable IPs)
    F_IMSI_TINY 278771700090001
    T_IMSI_TINY 278771700090005  (5 SIMs → needs 5 IPs → pool exhausted)
"""
import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID, make_imsi, make_iccid, poll_until
from fixtures.pools import create_pool, delete_pool, get_pool_stats, _force_clear_range_profiles
from fixtures.range_configs import (
    create_range_config,
    delete_range_config,
    create_iccid_range_config,
    add_imsi_slot,
    delete_iccid_range_config,
)

MODULE = 17

POOL_SUBNET    = "100.65.195.0/24"
ICCID_SUBNET   = "100.65.196.0/24"
TINY_SUBNET    = "100.65.197.0/30"

F_IMSI         = make_imsi(MODULE, 1)     # "278771700000001"
T_IMSI         = make_imsi(MODULE, 5)     # "278771700000005"

F_ICCID        = make_iccid(MODULE, 1)    # "8944501170000000001"
T_ICCID        = make_iccid(MODULE, 3)    # "8944501170000000003"
F_IMSI_S1      = make_imsi(MODULE, 10001) # "278771700010001"
T_IMSI_S1      = make_imsi(MODULE, 10003) # "278771700010003"
F_IMSI_S2      = make_imsi(MODULE, 20001) # "278771700020001"
T_IMSI_S2      = make_imsi(MODULE, 20003) # "278771700020003"

F_IMSI_TINY    = make_imsi(MODULE, 90001) # "278771700090001"
T_IMSI_TINY    = make_imsi(MODULE, 90005) # "278771700090005"

APN = "internet.operator.com"


def _wait_for_job(http: httpx.Client, job_id: str, timeout: float = 300.0) -> dict:
    """Poll GET /jobs/{job_id} until status is completed or failed."""
    return poll_until(
        fn=lambda: http.get(f"/jobs/{job_id}").json(),
        condition=lambda r: r.get("status") in ("completed", "completed_with_errors", "failed"),
        timeout=timeout,
        interval=3.0,
        label=f"job {job_id} completion",
    )


# ══════════════════════════════════════════════════════════════════════════════
# TestImmediateProvisioningSingleIMSI — IMSI range with provisioning_mode=immediate
# ══════════════════════════════════════════════════════════════════════════════

class TestImmediateProvisioningSingleIMSI:
    """Tests 17.1–17.8: immediate provisioning for a plain IMSI range."""

    pool_id: str = ""
    range_id: int = 0
    job_id: str = ""

    @classmethod
    def setup_class(cls):
        _force_clear_range_profiles(F_IMSI, T_IMSI)
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as http:
            pool = create_pool(http, pool_name="pool-imm17-imsi", subnet=POOL_SUBNET,
                               account_name="TestAccount", replace_on_conflict=True)
            cls.pool_id = pool["pool_id"]

    @classmethod
    def teardown_class(cls):
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as http:
            if cls.range_id:
                delete_range_config(http, cls.range_id)
            delete_pool(http, cls.pool_id)

    # 17.1 ────────────────────────────────────────────────────────────────────
    def test_01_create_immediate_returns_202(self, http: httpx.Client):
        """POST /range-configs with provisioning_mode=immediate → 202 + job_id."""
        rc = create_range_config(
            http,
            f_imsi=F_IMSI,
            t_imsi=T_IMSI,
            pool_id=self.pool_id,
            ip_resolution="imsi",
            provisioning_mode="immediate",
        )
        assert "id" in rc, f"Missing id in response: {rc}"
        assert "job_id" in rc, f"Missing job_id in 202 response: {rc}"
        TestImmediateProvisioningSingleIMSI.range_id = rc["id"]
        TestImmediateProvisioningSingleIMSI.job_id = rc["job_id"]

    # 17.2 ────────────────────────────────────────────────────────────────────
    def test_02_job_completes_successfully(self, http: httpx.Client):
        """Poll GET /jobs/{job_id} until completed — processed=5, failed=0."""
        job = _wait_for_job(http, self.job_id)
        assert job["status"] == "completed", \
            f"Job ended with status={job['status']}: {job.get('errors')}"
        assert job["processed"] == 5, f"Expected 5 processed, got {job['processed']}"
        assert job["failed"] == 0, f"Expected 0 failed, got {job['failed']}"

    # 17.3 ────────────────────────────────────────────────────────────────────
    def test_03_pool_stats_shows_5_allocated(self, http: httpx.Client):
        """Pool stats after job completes: allocated == 5."""
        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] >= 5, \
            f"Expected at least 5 allocated IPs, got {stats['allocated']}"

    # 17.4 ────────────────────────────────────────────────────────────────────
    def test_04_lookup_returns_ip_without_first_connection(
        self, http: httpx.Client, lookup_http: httpx.Client
    ):
        """GET /v1/lookup for F_IMSI → 200 + non-null static_ip (no first-connection needed)."""
        r = lookup_http.get("/lookup", params={"imsi": F_IMSI, "apn": APN,
                                                "use_case_id": USE_CASE_ID})
        assert r.status_code == 200, \
            f"Expected 200 from lookup, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("static_ip") is not None, \
            f"Expected non-null static_ip, got: {body}"

    # 17.5 ────────────────────────────────────────────────────────────────────
    def test_05_first_connection_is_idempotent(self, http: httpx.Client):
        """POST /first-connection for already-provisioned F_IMSI → 200 (idempotent path)."""
        r = http.post("/first-connection", json={
            "imsi": F_IMSI, "apn": APN, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200, \
            f"Expected 200 (idempotent), got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("static_ip") is not None, \
            f"Expected non-null static_ip in idempotent response: {body}"

    # 17.6 ────────────────────────────────────────────────────────────────────
    def test_06_delete_range_frees_pool(self, http: httpx.Client):
        """DELETE /range-configs/{id} → profiles hard-deleted, pool IPs returned."""
        delete_range_config(http, self.range_id)
        TestImmediateProvisioningSingleIMSI.range_id = 0

        # Profiles should be hard-deleted — GET /first-connection returns 404
        r = http.post("/first-connection", json={
            "imsi": F_IMSI, "apn": APN,
        })
        assert r.status_code == 404, \
            f"Expected 404 after profile deletion, got {r.status_code}: {r.text}"

        # Pool IPs should be returned
        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] == 0, \
            f"Expected 0 allocated after delete, got {stats['allocated']}"

    # 17.7 ────────────────────────────────────────────────────────────────────
    def test_07_invalid_provisioning_mode_returns_400(self, http: httpx.Client):
        """POST /range-configs with provisioning_mode='batch' → 400 validation_failed."""
        r = http.post("/range-configs", json={
            "account_name": "TestAccount",
            "f_imsi": F_IMSI,
            "t_imsi": T_IMSI,
            "pool_id": self.pool_id,
            "ip_resolution": "imsi",
            "provisioning_mode": "batch",
        })
        assert r.status_code == 400, \
            f"Expected 400 for invalid mode, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("error") == "validation_failed", \
            f"Expected validation_failed error: {body}"

    # 17.8 ────────────────────────────────────────────────────────────────────
    def test_08_capacity_check_blocks_exhausted_pool(self, http: httpx.Client):
        """POST immediate with /30 pool (2 IPs) for 5 SIMs → 503 pool_exhausted, range NOT created."""
        # Create tiny pool
        tiny_pool = create_pool(http, pool_name="pool-imm17-tiny", subnet=TINY_SUBNET,
                                account_name="TestAccount", replace_on_conflict=True)
        tiny_pool_id = tiny_pool["pool_id"]
        try:
            r = http.post("/range-configs", json={
                "account_name": "TestAccount",
                "f_imsi": F_IMSI_TINY,
                "t_imsi": T_IMSI_TINY,
                "pool_id": tiny_pool_id,
                "ip_resolution": "imsi",
                "provisioning_mode": "immediate",
            })
            assert r.status_code == 503, \
                f"Expected 503 for pool_exhausted, got {r.status_code}: {r.text}"
            body = r.json()
            assert body.get("error") == "pool_exhausted", \
                f"Expected pool_exhausted error: {body}"

            # Verify range was NOT created (transaction rolled back)
            list_r = http.get("/range-configs")
            ids = [c["id"] for c in (list_r.json().get("items") or [])]
            # The range for F_IMSI_TINY shouldn't exist in our range config list
            # (we can confirm by checking the response has no f_imsi matching F_IMSI_TINY)
            items = list_r.json().get("items", [])
            tiny_ranges = [c for c in items if c["f_imsi"] == F_IMSI_TINY]
            assert not tiny_ranges, \
                f"Range should have been rolled back but found: {tiny_ranges}"
        finally:
            delete_pool(http, tiny_pool_id)


# ══════════════════════════════════════════════════════════════════════════════
# TestImmediateProvisioningIccidRange — ICCID range with provisioning_mode=immediate
# ══════════════════════════════════════════════════════════════════════════════

class TestImmediateProvisioningIccidRange:
    """Tests 17.9–17.13: immediate provisioning for an ICCID range."""

    pool_id: str = ""
    iccid_range_id: int = 0
    job_id: str = ""
    slot1_range_config_id: int = 0

    @classmethod
    def setup_class(cls):
        _force_clear_range_profiles(F_IMSI_S1, T_IMSI_S1)
        _force_clear_range_profiles(F_IMSI_S2, T_IMSI_S2)
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as http:
            pool = create_pool(http, pool_name="pool-imm17-iccid", subnet=ICCID_SUBNET,
                               account_name="TestAccount", replace_on_conflict=True)
            cls.pool_id = pool["pool_id"]

    @classmethod
    def teardown_class(cls):
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as http:
            if cls.iccid_range_id:
                delete_iccid_range_config(http, cls.iccid_range_id)
            delete_pool(http, cls.pool_id)

    # 17.9 ────────────────────────────────────────────────────────────────────
    def test_09_create_iccid_range_immediate(self, http: httpx.Client):
        """POST /iccid-range-configs with provisioning_mode=immediate, imsi_count=2 → 201."""
        rc = create_iccid_range_config(
            http,
            f_iccid=F_ICCID,
            t_iccid=T_ICCID,
            ip_resolution="imsi",
            imsi_count=2,
            pool_id=self.pool_id,
            provisioning_mode="immediate",
        )
        assert "id" in rc, f"Missing id in response: {rc}"
        assert "job_id" not in rc, \
            f"job_id should NOT appear at ICCID range creation (wait for last slot): {rc}"
        TestImmediateProvisioningIccidRange.iccid_range_id = rc["id"]

    # 17.10 ───────────────────────────────────────────────────────────────────
    def test_10_add_slot1_no_provisioning_yet(self, http: httpx.Client):
        """POST first slot (1 of 2) → no job_id; pool still shows 0 allocated (job not triggered)."""
        res = add_imsi_slot(
            http,
            iccid_range_id=self.iccid_range_id,
            f_imsi=F_IMSI_S1,
            t_imsi=T_IMSI_S1,
            imsi_slot=1,
            ip_resolution="imsi",
            pool_id=self.pool_id,
        )
        assert "job_id" not in res, \
            f"job_id should not be returned after first slot: {res}"
        TestImmediateProvisioningIccidRange.slot1_range_config_id = res.get("range_config_id", 0)

        # Pool should be untouched — immediate job only fires when the last slot is added
        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] == 0, \
            f"Expected 0 allocated IPs after slot 1/2, got {stats['allocated']}"

    # 17.11 ───────────────────────────────────────────────────────────────────
    def test_11_add_last_slot_triggers_provisioning(self, http: httpx.Client):
        """POST last slot (2 of 2) → job_id returned; poll until completed; profiles exist."""
        res = add_imsi_slot(
            http,
            iccid_range_id=self.iccid_range_id,
            f_imsi=F_IMSI_S2,
            t_imsi=T_IMSI_S2,
            imsi_slot=2,
            ip_resolution="imsi",
            pool_id=self.pool_id,
        )
        assert "job_id" in res, \
            f"Expected job_id after last slot add (2 of 2), got: {res}"
        TestImmediateProvisioningIccidRange.job_id = res["job_id"]

        # Wait for job to complete
        job = _wait_for_job(http, res["job_id"])
        assert job["status"] == "completed", \
            f"ICCID provisioning job ended with status={job['status']}: {job.get('errors')}"

        # Verify profiles exist for F_IMSI_S1 (slot 1, card 0)
        r = http.post("/first-connection", json={"imsi": F_IMSI_S1, "apn": APN})
        assert r.status_code == 200, \
            f"Expected 200 (idempotent) for F_IMSI_S1, got {r.status_code}: {r.text}"
        assert r.json().get("static_ip") is not None, \
            f"Expected non-null IP for F_IMSI_S1: {r.json()}"

    # 17.12 ───────────────────────────────────────────────────────────────────
    def test_12_lookup_works_without_first_connection(
        self, http: httpx.Client, lookup_http: httpx.Client
    ):
        """GET /v1/lookup for F_IMSI_S1 → 200 (pre-provisioned, no first-connection required)."""
        r = lookup_http.get("/lookup", params={"imsi": F_IMSI_S1, "apn": APN,
                                                "use_case_id": USE_CASE_ID})
        assert r.status_code == 200, \
            f"Expected 200 from lookup for F_IMSI_S1, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("static_ip") is not None, \
            f"Expected non-null static_ip in lookup: {body}"

    # 17.13 ───────────────────────────────────────────────────────────────────
    def test_13_delete_iccid_range_frees_pool(self, http: httpx.Client):
        """DELETE /iccid-range-configs/{id} → profiles hard-deleted, IPs freed."""
        delete_iccid_range_config(http, self.iccid_range_id)
        TestImmediateProvisioningIccidRange.iccid_range_id = 0

        # Profiles should be hard-deleted — first-connection returns 404
        r = http.post("/first-connection", json={"imsi": F_IMSI_S1, "apn": APN})
        assert r.status_code == 404, \
            f"Expected 404 after profile deletion, got {r.status_code}: {r.text}"

        # Pool IPs should be returned
        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] == 0, \
            f"Expected 0 allocated after ICCID range delete, got {stats['allocated']}"
