"""
test_08b_bulk_actions.py — Bulk IP release and bulk IMSI delete.

Covers:
  POST /profiles/bulk-release-ips  — release IPs for a set of SIMs (by list or filter)
  POST /imsis/bulk-delete          — remove a batch of IMSIs, returning IPs to pool

Test cases 8b.1 – 8b.8
"""
import io
import time

import httpx

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID, poll_until
from fixtures.pools import create_pool, delete_pool
from fixtures.range_configs import create_range_config, delete_range_config

MODULE = 76   # distinct IMSI prefix to avoid collision with other modules

# /28 subnet → 14 usable IPs
POOL_SUBNET  = "100.65.197.0/28"
USABLE_COUNT = 14

F_IMSI = f"27877{MODULE:02d}00000001"
T_IMSI = f"27877{MODULE:02d}00000099"

# IMSIs used across tests
IMSIS_REL  = [f"27877{MODULE:02d}{i:08d}" for i in range(1, 5)]   # 8b.2 bulk release by list
IMSIS_FILT = [f"27877{MODULE:02d}{i:08d}" for i in range(5, 9)]   # 8b.4 bulk release by filter
IMSIS_DEL  = [f"27877{MODULE:02d}{i:08d}" for i in range(9, 13)]  # 8b.6/8b.7 bulk IMSI delete

JOB_TIMEOUT = 30.0


def _wait_job(http: httpx.Client, job_id: str) -> dict:
    return poll_until(
        fn=lambda: http.get(f"/jobs/{job_id}").json(),
        condition=lambda r: r.get("status") == "completed",
        timeout=JOB_TIMEOUT,
        interval=0.5,
        label=f"job {job_id}",
    )


class TestBulkActions:
    pool_id:         str | None = None
    range_config_id: str | None = None
    alloc_sim_ids:   list[str]  = []

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet=POOL_SUBNET,
                            pool_name=f"pool-bulk-08b", account_name="BulkActionAccount",
                            replace_on_conflict=True)
            cls.pool_id = p["pool_id"]
            rc = create_range_config(
                c,
                f_imsi=F_IMSI,
                t_imsi=T_IMSI,
                pool_id=cls.pool_id,
                ip_resolution="imsi",
                account_name="BulkActionAccount",
            )
            cls.range_config_id = rc["id"]
            cls.alloc_sim_ids = []

    @classmethod
    def teardown_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            for did in cls.alloc_sim_ids:
                try:
                    c.delete(f"/profiles/{did}")
                except Exception:
                    pass
            if cls.range_config_id:
                delete_range_config(c, cls.range_config_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    @staticmethod
    def _first_connection(http: httpx.Client, imsi: str) -> dict:
        r = http.post(
            "/profiles/first-connection",
            json={"imsi": imsi, "apn": "internet.operator.com", "use_case_id": USE_CASE_ID},
        )
        assert r.status_code == 201, f"first-connection failed for {imsi}: {r.text}"
        return r.json()

    # 8b.1 ────────────────────────────────────────────────────────────────────
    def test_01_setup_and_allocate(self, http: httpx.Client):
        """Allocate IPs for all test IMSIs via first-connection."""
        all_imsis = IMSIS_REL + IMSIS_FILT + IMSIS_DEL
        for imsi in all_imsis:
            body = self._first_connection(http, imsi)
            TestBulkActions.alloc_sim_ids.append(body["sim_id"])

        stats = http.get(f"/pools/{TestBulkActions.pool_id}/stats").json()
        assert stats["allocated"] == len(all_imsis)

    # 8b.2 ────────────────────────────────────────────────────────────────────
    def test_02_bulk_release_by_sim_id_list(self, http: httpx.Client):
        """POST /profiles/bulk-release-ips with explicit sim_ids → 202, job completes."""
        # Collect sim_ids for IMSIS_REL
        sim_ids = []
        for imsi in IMSIS_REL:
            r = http.get("/profiles", params={"imsi": imsi})
            assert r.status_code == 200
            sim_ids.append(r.json()[0]["sim_id"])

        stats_before = http.get(f"/pools/{TestBulkActions.pool_id}/stats").json()

        r = http.post("/profiles/bulk-release-ips", json={"sim_ids": sim_ids})
        assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
        job_id = r.json()["job_id"]
        assert r.json()["submitted"] == len(sim_ids)

        job = _wait_job(http, job_id)
        assert job["status"] == "completed"
        assert job["processed"] == len(sim_ids)
        assert job["failed"] == 0

        stats_after = http.get(f"/pools/{TestBulkActions.pool_id}/stats").json()
        assert stats_after["available"] == stats_before["available"] + len(sim_ids), \
            "IPs were not returned to the pool"

        # Verify profiles still exist but have no IP bindings
        for imsi in IMSIS_REL:
            r = http.get("/profiles", params={"imsi": imsi})
            profile = r.json()[0]
            assert profile["imsis"][0]["apn_ips"] == [], \
                f"IP binding still present for IMSI {imsi} after release"

    # 8b.3 ────────────────────────────────────────────────────────────────────
    def test_03_bulk_release_idempotent(self, http: httpx.Client):
        """Releasing already-released SIMs → job completes with processed=N, failed=0."""
        sim_ids = []
        for imsi in IMSIS_REL:
            r = http.get("/profiles", params={"imsi": imsi})
            sim_ids.append(r.json()[0]["sim_id"])

        r = http.post("/profiles/bulk-release-ips", json={"sim_ids": sim_ids})
        assert r.status_code == 202
        job = _wait_job(http, r.json()["job_id"])
        assert job["status"] == "completed"
        assert job["processed"] == len(sim_ids)
        assert job["failed"] == 0

    # 8b.4 ────────────────────────────────────────────────────────────────────
    def test_04_bulk_release_by_filter(self, http: httpx.Client):
        """POST /profiles/bulk-release-ips with account_name filter → releases matching SIMs."""
        stats_before = http.get(f"/pools/{TestBulkActions.pool_id}/stats").json()
        allocated_before = stats_before["allocated"]
        assert allocated_before >= len(IMSIS_FILT), "Expected IMSIS_FILT to still have IPs"

        r = http.post("/profiles/bulk-release-ips", json={"account_name": "BulkActionAccount"})
        assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
        body = r.json()
        # submitted should cover all active BulkActionAccount SIMs
        assert body["submitted"] >= len(IMSIS_FILT)

        job = _wait_job(http, body["job_id"])
        assert job["status"] == "completed"
        assert job["failed"] == 0

        stats_after = http.get(f"/pools/{TestBulkActions.pool_id}/stats").json()
        # At minimum the IMSIS_FILT IPs must have been returned
        assert stats_after["available"] >= stats_before["available"] + len(IMSIS_FILT)

    # 8b.5 ────────────────────────────────────────────────────────────────────
    def test_05_bulk_release_validation_errors(self, http: httpx.Client):
        """bulk-release-ips with no body fields → 400; unknown sim_id in job → failed entry."""
        # Missing both sim_ids and filters
        r = http.post("/profiles/bulk-release-ips", json={})
        assert r.status_code == 400

        # Unknown sim_id → job records it as a failure, does not crash
        fake_id = "00000000-0000-0000-0000-000000000001"
        r = http.post("/profiles/bulk-release-ips", json={"sim_ids": [fake_id]})
        assert r.status_code == 202
        job = _wait_job(http, r.json()["job_id"])
        assert job["failed"] == 1
        assert job["errors"][0]["value"] == fake_id

    # 8b.6 ────────────────────────────────────────────────────────────────────
    def test_06_bulk_imsi_delete_json(self, http: httpx.Client):
        """POST /imsis/bulk-delete with JSON body → IMSIs removed, IPs returned to pool."""
        # Re-allocate IPs for IMSIS_DEL (released in 8b.4 via account filter)
        for imsi in IMSIS_DEL:
            r = http.get("/profiles", params={"imsi": imsi})
            sim_id = r.json()[0]["sim_id"]
            # Re-connect to get fresh IPs
            http.post(
                "/profiles/first-connection",
                json={"imsi": imsi, "apn": "internet.operator.com", "use_case_id": USE_CASE_ID},
            )

        stats_before = http.get(f"/pools/{TestBulkActions.pool_id}/stats").json()

        r = http.post("/imsis/bulk-delete", json={"imsis": IMSIS_DEL})
        assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
        body = r.json()
        assert body["submitted"] == len(IMSIS_DEL)

        job = _wait_job(http, body["job_id"])
        assert job["status"] == "completed"
        assert job["processed"] == len(IMSIS_DEL)
        assert job["failed"] == 0

        stats_after = http.get(f"/pools/{TestBulkActions.pool_id}/stats").json()
        assert stats_after["available"] == stats_before["available"] + len(IMSIS_DEL), \
            "IPs were not returned to pool after bulk IMSI delete"

        # IMSIs must no longer exist in imsi2sim
        for imsi in IMSIS_DEL:
            r = http.get("/profiles", params={"imsi": imsi})
            assert r.status_code == 404, f"IMSI {imsi} still found after bulk delete"

    # 8b.7 ────────────────────────────────────────────────────────────────────
    def test_07_bulk_imsi_delete_csv(self, http: httpx.Client):
        """POST /imsis/bulk-delete with CSV file → same behaviour as JSON."""
        # Use IMSIS_REL — they were already released (no IPs), but IMSIs still linked
        csv_content = "imsi\n" + "\n".join(IMSIS_REL)
        files = {"file": ("imsis.csv", io.BytesIO(csv_content.encode()), "text/csv")}

        r = http.post("/imsis/bulk-delete", files=files)
        assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
        assert r.json()["submitted"] == len(IMSIS_REL)

        job = _wait_job(http, r.json()["job_id"])
        assert job["status"] == "completed"
        assert job["processed"] == len(IMSIS_REL)
        assert job["failed"] == 0

        for imsi in IMSIS_REL:
            r = http.get("/profiles", params={"imsi": imsi})
            assert r.status_code == 404, f"IMSI {imsi} still found after CSV bulk delete"

    # 8b.8 ────────────────────────────────────────────────────────────────────
    def test_08_bulk_imsi_delete_validation_errors(self, http: httpx.Client):
        """Validation: invalid IMSI format and not-found IMSI → failures recorded in job."""
        bad_imsis = [
            "12345",                  # too short
            "9" * 15,                 # valid format but not in DB
        ]
        r = http.post("/imsis/bulk-delete", json={"imsis": bad_imsis})
        assert r.status_code == 202
        job = _wait_job(http, r.json()["job_id"])
        assert job["status"] == "completed"
        assert job["failed"] == 2
        assert job["processed"] == 0
        # Both errors must be reported
        error_values = {e["value"] for e in job["errors"]}
        assert error_values == set(bad_imsis)

        # Empty body → 400
        r = http.post("/imsis/bulk-delete", json={})
        assert r.status_code == 400
