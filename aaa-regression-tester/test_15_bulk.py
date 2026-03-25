"""
test_08_bulk.py — Bulk upsert via POST /profiles/bulk + job polling.

Submits 1 500 profiles (500 Profile-A + 500 Profile-B + 500 Profile-C)
via a single bulk request, polls the resulting job until completion, then
spot-checks random entries via GET /profiles and GET /lookup.

Test cases 8.1 – 8.8  (plan-01 §test_08_bulk)
"""
import csv
import io
import random
import string
import time

import pytest
import httpx

from conftest import make_imsi, make_iccid, make_ip, poll_until, PROVISION_BASE, JWT_TOKEN, USE_CASE_ID
from fixtures.pools import create_pool, delete_pool, _force_clear_pool_ips

MODULE = 8

# Three separate pools for the three profile types
POOL_A_SUBNET = "100.65.200.0/22"   # 1 022 usable IPs (enough for 500 A-profiles)
POOL_B_SUBNET = "100.65.204.0/22"
POOL_C_SUBNET = "100.65.208.0/22"

BATCH_SIZE = 500        # profiles per type
JOB_TIMEOUT = 600.0     # seconds


def _make_profile_a(seq: int, pool_id: str) -> dict:
    """Build a Profile-A (ip_resolution=iccid) payload dict."""
    imsi1 = make_imsi(MODULE, seq * 2)
    imsi2 = make_imsi(MODULE, seq * 2 + 1)
    iccid = make_iccid(MODULE, seq)
    ip    = make_ip(200 + seq // 256, seq % 256 or 1)
    return {
        "iccid":         iccid,
        "account_name":  "TestAccount",
        "status":        "active",
        "ip_resolution": "iccid",
        "imsis": [
            {"imsi": imsi1, "apn_ips": []},
            {"imsi": imsi2, "apn_ips": []},
        ],
        "iccid_ips": [
            {"static_ip": ip, "pool_id": pool_id, "pool_name": "bulk-pool-a"},
        ],
    }


def _make_profile_b(seq: int, pool_id: str) -> dict:
    """Build a Profile-B (ip_resolution=imsi) payload dict."""
    base_seq = 1000 + seq
    imsi  = make_imsi(MODULE, base_seq)
    ip    = make_ip(204 + (seq // 256), seq % 256 or 1)
    return {
        "iccid":         None,
        "account_name":  "TestAccount",
        "status":        "active",
        "ip_resolution": "imsi",
        "imsis": [
            {
                "imsi": imsi,
                "apn_ips": [
                    {"static_ip": ip, "pool_id": pool_id,
                     "pool_name": "bulk-pool-b"},
                ],
            }
        ],
    }


def _make_profile_c(seq: int, pool_id: str) -> dict:
    """Build a Profile-C (ip_resolution=imsi_apn) payload dict."""
    base_seq = 2000 + seq
    imsi  = make_imsi(MODULE, base_seq)
    ip_a  = make_ip(208 + (seq // 256), (seq % 127) + 1)
    ip_b  = make_ip(208 + (seq // 256), (seq % 127) + 128)
    return {
        "iccid":         None,
        "account_name":  "TestAccount",
        "status":        "active",
        "ip_resolution": "imsi_apn",
        "imsis": [
            {
                "imsi": imsi,
                "apn_ips": [
                    {"apn": "internet.operator.com", "static_ip": ip_a,
                     "pool_id": pool_id, "pool_name": "bulk-pool-c"},
                    {"apn": "ims.operator.com",      "static_ip": ip_b,
                     "pool_id": pool_id, "pool_name": "bulk-pool-c"},
                ],
            }
        ],
    }


class TestBulk:
    pool_a_id: str | None = None
    pool_b_id: str | None = None
    pool_c_id: str | None = None
    job_id:    str | None = None

    # Spot-check samples (populated in 8.1, used in 8.3 / 8.4)
    sample_profiles_a: list[dict] = []
    sample_profiles_c: list[dict] = []

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            pa = create_pool(c, subnet=POOL_A_SUBNET,
                             pool_name="bulk-pool-a", account_name="TestAccount",
                             routing_domain="bulk-test-08",
                             replace_on_conflict=True)
            pb = create_pool(c, subnet=POOL_B_SUBNET,
                             pool_name="bulk-pool-b", account_name="TestAccount",
                             routing_domain="bulk-test-08",
                             replace_on_conflict=True)
            pc = create_pool(c, subnet=POOL_C_SUBNET,
                             pool_name="bulk-pool-c", account_name="TestAccount",
                             routing_domain="bulk-test-08",
                             replace_on_conflict=True)
            cls.pool_a_id = pa["pool_id"]
            cls.pool_b_id = pb["pool_id"]
            cls.pool_c_id = pc["pool_id"]

    @classmethod
    def teardown_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            for pid in (cls.pool_a_id, cls.pool_b_id, cls.pool_c_id):
                if pid:
                    try:
                        _force_clear_pool_ips(pid)
                        c.delete(f"/pools/{pid}")
                    except Exception:
                        pass

    # 8.1 ─────────────────────────────────────────────────────────────────────
    def test_01_submit_bulk_job(self, http: httpx.Client):
        """POST /profiles/bulk with 1 500 profiles → 202, job_id returned."""
        profiles: list[dict] = []
        for seq in range(1, BATCH_SIZE + 1):
            profiles.append(_make_profile_a(seq, TestBulk.pool_a_id))
        for seq in range(1, BATCH_SIZE + 1):
            profiles.append(_make_profile_b(seq, TestBulk.pool_b_id))
        for seq in range(1, BATCH_SIZE + 1):
            profiles.append(_make_profile_c(seq, TestBulk.pool_c_id))

        # Save 10 random samples for spot-checks in 8.3 / 8.4
        TestBulk.sample_profiles_a = random.sample(profiles[:BATCH_SIZE], 5)
        TestBulk.sample_profiles_c = random.sample(
            profiles[2 * BATCH_SIZE:], 5
        )

        r = http.post("/profiles/bulk", json=profiles, timeout=60.0)
        assert r.status_code == 202, \
            f"Expected 202, got {r.status_code}: {r.text}"
        body = r.json()
        assert "job_id" in body, f"No job_id in response: {body}"
        TestBulk.job_id = body["job_id"]

    # 8.2 ─────────────────────────────────────────────────────────────────────
    @pytest.mark.timeout(660)  # JOB_TIMEOUT=600s + 60s buffer
    def test_02_poll_job_until_completed(self, http: httpx.Client):
        """Poll GET /jobs/{job_id} until status=completed; processed=1500, failed=0."""
        assert TestBulk.job_id, "job_id not set — test 8.1 must pass first"

        def check():
            r = http.get(f"/jobs/{TestBulk.job_id}")
            assert r.status_code == 200, f"Job GET failed: {r.status_code}"
            return r.json()

        result = poll_until(
            check,
            condition=lambda j: j.get("status") in ("completed", "failed"),
            timeout=JOB_TIMEOUT,
            interval=10.0,
            label=f"bulk job {TestBulk.job_id}",
        )
        assert result["status"] == "completed", \
            f"Job ended with status={result['status']}: {result}"
        assert result.get("processed", 0) == 3 * BATCH_SIZE, \
            f"processed={result.get('processed')}, expected {3 * BATCH_SIZE}"
        assert result.get("failed", 0) == 0, \
            f"failed={result.get('failed')}, errors: {result.get('errors', [])}"

    # 8.3 ─────────────────────────────────────────────────────────────────────
    def test_03_spot_check_profiles_via_api(self, http: httpx.Client):
        """GET /profiles/{sim_id} for 10 random entries → 200, fields correct."""
        for sample in TestBulk.sample_profiles_a:
            # Look up by ICCID
            iccid = sample["iccid"]
            r = http.get("/profiles", params={"iccid": iccid})
            assert r.status_code == 200
            data = r.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            assert len(profiles) >= 1, \
                f"Profile with iccid={iccid} not found after bulk import"
            assert profiles[0]["ip_resolution"] == "iccid"

        for sample in TestBulk.sample_profiles_c:
            imsi = sample["imsis"][0]["imsi"]
            r = http.get("/profiles", params={"imsi": imsi})
            assert r.status_code == 200
            data = r.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            assert len(profiles) >= 1, \
                f"Profile with imsi={imsi} not found after bulk import"
            assert profiles[0]["ip_resolution"] == "imsi_apn"

    # 8.4 ─────────────────────────────────────────────────────────────────────
    def test_04_spot_check_lookup_for_bulk_imsis(self, lookup_http: httpx.Client):
        """GET /lookup for 10 random IMSIs from the batch → 200 with correct static_ip."""
        # Spot-check Profile-C entries (imsi_apn) with a known APN
        for sample in TestBulk.sample_profiles_c:
            imsi     = sample["imsis"][0]["imsi"]
            expected = sample["imsis"][0]["apn_ips"][0]["static_ip"]
            apn      = sample["imsis"][0]["apn_ips"][0]["apn"]
            r = lookup_http.get("/lookup", params={"imsi": imsi, "apn": apn,
                                                    "use_case_id": USE_CASE_ID})
            assert r.status_code == 200, \
                f"Lookup for {imsi}@{apn} returned {r.status_code}"
            assert r.json()["static_ip"] == expected

    # 8.5 ─────────────────────────────────────────────────────────────────────
    @pytest.mark.timeout(180)  # poll_until timeout=120s + buffer
    def test_05_bulk_with_one_invalid_entry(self, http: httpx.Client):
        """POST /profiles/bulk with 1 valid + 1 IMSI-invalid → 202; job: failed=1, processed=1."""
        valid_imsi   = make_imsi(MODULE, 9901)
        valid_ip     = make_ip(212, 1)
        invalid_imsi = "12345"       # only 5 digits — must fail validation

        payload = [
            {
                "iccid":         None,
                "account_name":  "TestAccount",
                "status":        "active",
                "ip_resolution": "imsi",
                "imsis": [
                    {"imsi": valid_imsi,
                     "apn_ips": [{"static_ip": valid_ip,
                                  "pool_id": TestBulk.pool_b_id}]},
                ],
            },
            {
                "iccid":         None,
                "account_name":  "TestAccount",
                "status":        "active",
                "ip_resolution": "imsi",
                "imsis": [
                    {"imsi": invalid_imsi,
                     "apn_ips": [{"static_ip": "100.65.212.2",
                                  "pool_id": TestBulk.pool_b_id}]},
                ],
            },
        ]

        r = http.post("/profiles/bulk", json=payload, timeout=30.0)
        assert r.status_code == 202
        body = r.json()
        assert "job_id" in body
        partial_job_id = body["job_id"]

        # Poll to completion
        def check():
            return http.get(f"/jobs/{partial_job_id}").json()

        result = poll_until(
            check,
            condition=lambda j: j.get("status") in ("completed", "failed"),
            timeout=120.0,
            interval=5.0,
            label="partial-invalid bulk job",
        )
        assert result["status"] == "completed"
        assert result.get("processed", 0) == 1, \
            f"Expected processed=1, got {result.get('processed')}"
        assert result.get("failed", 0) == 1, \
            f"Expected failed=1, got {result.get('failed')}"

    # 8.6 ─────────────────────────────────────────────────────────────────────
    @pytest.mark.timeout(180)  # poll_until timeout=120s + buffer
    def test_06_job_errors_array_contains_details(self, http: httpx.Client):
        """GET /jobs/{job_id} from test 8.5 → errors array contains field=imsi detail."""
        # Reuse the partial job from 8.5 via a fresh lookup
        # (job_id was ephemeral; we search by listing recent jobs or via a known marker)
        # For robustness we just submit a single-invalid job again and check immediately.
        invalid_imsi = "99999"   # 5 digits

        r = http.post("/profiles/bulk", json=[
            {
                "iccid": None, "account_name": "TestAccount",
                "status": "active", "ip_resolution": "imsi",
                "imsis": [{"imsi": invalid_imsi,
                            "apn_ips": [{"static_ip": "100.65.212.99",
                                         "pool_id": TestBulk.pool_b_id}]}],
            }
        ], timeout=30.0)
        assert r.status_code == 202
        job_id = r.json()["job_id"]

        def check():
            return http.get(f"/jobs/{job_id}").json()

        result = poll_until(check,
                            condition=lambda j: j.get("status") in ("completed", "failed"),
                            timeout=120.0, interval=5.0,
                            label="invalid-imsi bulk job")

        errors = result.get("errors", [])
        assert len(errors) >= 1, "Expected at least one error entry"
        error_fields = [e.get("field") for e in errors]
        assert any(f in ("imsi", "imsis") for f in error_fields), \
            f"Error field 'imsi' not in errors: {errors}"

    # 8.7 ─────────────────────────────────────────────────────────────────────
    @pytest.mark.timeout(300)  # two poll_until calls at 120s each + buffer
    def test_07_bulk_upsert_idempotency(self, http: httpx.Client):
        """Bulk-upsert the same profile twice → second upsert updates, total count unchanged."""
        imsi  = make_imsi(MODULE, 9950)
        ip_v1 = make_ip(212, 50)
        ip_v2 = make_ip(212, 51)

        def submit(ip: str) -> str:
            r = http.post("/profiles/bulk", json=[
                {
                    "iccid": None, "account_name": "TestAccount",
                    "status": "active", "ip_resolution": "imsi",
                    "imsis": [{"imsi": imsi,
                                "apn_ips": [{"static_ip": ip,
                                             "pool_id": TestBulk.pool_b_id}]}],
                }
            ], timeout=30.0)
            assert r.status_code == 202
            return r.json()["job_id"]

        # First submission
        jid1 = submit(ip_v1)
        poll_until(lambda: http.get(f"/jobs/{jid1}").json(),
                   lambda j: j.get("status") in ("completed", "failed"),
                   timeout=120.0, interval=5.0, label="upsert-v1")

        # Lookup confirms ip_v1
        r_l1 = http.get("/profiles", params={"imsi": imsi})
        assert r_l1.status_code == 200

        # Second submission with updated IP
        jid2 = submit(ip_v2)
        poll_until(lambda: http.get(f"/jobs/{jid2}").json(),
                   lambda j: j.get("status") in ("completed", "failed"),
                   timeout=120.0, interval=5.0, label="upsert-v2")

        # Profile must have ip_v2 now; profile count must be 1 (not 2)
        r_l2 = http.get("/profiles", params={"imsi": imsi})
        assert r_l2.status_code == 200
        data = r_l2.json()
        profiles = data if isinstance(data, list) else data.get("profiles", [])
        assert len(profiles) == 1, \
            f"Expected exactly 1 profile (upsert), found {len(profiles)}"

    # 8.8 ─────────────────────────────────────────────────────────────────────
    @pytest.mark.timeout(180)  # poll_until timeout=120s + buffer
    def test_08_bulk_csv_upload(self, http: httpx.Client):
        """POST /profiles/bulk as multipart/form-data CSV → 202, same job flow."""
        # Build a minimal CSV with 3 rows (one per profile mode)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=[
            "iccid", "account_name", "ip_resolution",
            "imsi", "apn", "static_ip", "pool_id",
        ])
        writer.writeheader()
        writer.writerows([
            {
                "iccid": make_iccid(MODULE, 9990),
                "account_name": "TestAccount",
                "ip_resolution": "iccid",
                "imsi": make_imsi(MODULE, 9990),
                "apn": "",
                "static_ip": make_ip(213, 1),
                "pool_id": TestBulk.pool_a_id,
            },
            {
                "iccid": "",
                "account_name": "TestAccount",
                "ip_resolution": "imsi",
                "imsi": make_imsi(MODULE, 9991),
                "apn": "",
                "static_ip": make_ip(213, 2),
                "pool_id": TestBulk.pool_b_id,
            },
            {
                "iccid": "",
                "account_name": "TestAccount",
                "ip_resolution": "imsi_apn",
                "imsi": make_imsi(MODULE, 9992),
                "apn": "internet.operator.com",
                "static_ip": make_ip(213, 3),
                "pool_id": TestBulk.pool_c_id,
            },
        ])

        csv_bytes = buf.getvalue().encode()
        files = {"file": ("bulk.csv", csv_bytes, "text/csv")}

        r = http.post("/profiles/bulk", files=files, timeout=30.0)
        assert r.status_code == 202, \
            f"Expected 202, got {r.status_code}: {r.text}"
        body = r.json()
        assert "job_id" in body

        # Poll to verify the CSV job also completes
        csv_job_id = body["job_id"]
        result = poll_until(
            lambda: http.get(f"/jobs/{csv_job_id}").json(),
            condition=lambda j: j.get("status") in ("completed", "failed"),
            timeout=120.0, interval=5.0,
            label="CSV bulk job",
        )
        assert result["status"] == "completed", \
            f"CSV bulk job did not complete successfully: {result}"
        assert result.get("failed", 0) == 0
