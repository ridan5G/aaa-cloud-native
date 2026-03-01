"""
test_02_range_configs.py — IMSI Range Config CRUD

Test cases 2.1 – 2.8  (plan-01 §test_02_range_configs)
"""
import httpx
import pytest

from fixtures.pools import create_pool, delete_pool
from fixtures.range_configs import create_range_config, delete_range_config

F_IMSI = "278773020000001"
T_IMSI = "278773020000999"


class TestRangeConfigs:
    pool_id:   str | None = None
    pool2_id:  str | None = None
    config_id: int | None = None

    @classmethod
    def setup_class(cls):
        """Create two pools used across all tests in this module."""
        # Pools created here; http fixture isn't available at class level,
        # so we use a temporary client.
        import os, httpx as _httpx
        base = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
        jwt  = os.getenv("TEST_JWT", "dev-skip-verify")
        with _httpx.Client(base_url=base,
                           headers={"Authorization": f"Bearer {jwt}"},
                           timeout=30.0) as c:
            p1 = create_pool(c, subnet="100.65.130.0/24",
                             pool_name="rc-pool-1", account_name="Melita")
            cls.pool_id  = p1["pool_id"]
            p2 = create_pool(c, subnet="100.65.131.0/24",
                             pool_name="rc-pool-2", account_name="Melita")
            cls.pool2_id = p2["pool_id"]

    @classmethod
    def teardown_class(cls):
        """Delete the pools created in setup_class."""
        import os, httpx as _httpx
        base = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
        jwt  = os.getenv("TEST_JWT", "dev-skip-verify")
        with _httpx.Client(base_url=base,
                           headers={"Authorization": f"Bearer {jwt}"},
                           timeout=30.0) as c:
            if cls.config_id:
                delete_range_config(c, cls.config_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)
            if cls.pool2_id:
                delete_pool(c, cls.pool2_id)

    # 2.1 ─────────────────────────────────────────────────────────────────────
    def test_01_create_range_config(self, http: httpx.Client):
        """POST /range-configs with valid fields → 201, id returned."""
        body = create_range_config(
            http,
            f_imsi=F_IMSI,
            t_imsi=T_IMSI,
            pool_id=TestRangeConfigs.pool_id,
            account_name="Melita",
        )
        assert "id" in body
        TestRangeConfigs.config_id = body["id"]

    # 2.2 ─────────────────────────────────────────────────────────────────────
    def test_02_get_range_config(self, http: httpx.Client):
        """GET /range-configs/{id} → 200, fields correct."""
        cid = TestRangeConfigs.config_id
        resp = http.get(f"/range-configs/{cid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["f_imsi"] == F_IMSI
        assert body["t_imsi"] == T_IMSI
        assert body["pool_id"] == TestRangeConfigs.pool_id
        assert body["ip_resolution"] == "imsi"
        assert body["status"] == "active"

    # 2.3 ─────────────────────────────────────────────────────────────────────
    def test_03_list_range_configs_by_account(self, http: httpx.Client):
        """GET /range-configs?account_name=Melita → includes created config."""
        resp = http.get("/range-configs", params={"account_name": "Melita"})
        assert resp.status_code == 200
        items = resp.json().get("items", resp.json())
        ids = [item["id"] for item in items]
        assert TestRangeConfigs.config_id in ids

    # 2.4 ─────────────────────────────────────────────────────────────────────
    def test_04_patch_range_config_pool_and_resolution(self, http: httpx.Client):
        """PATCH pool_id + ip_resolution → 200; GET confirms update."""
        cid = TestRangeConfigs.config_id
        resp = http.patch(f"/range-configs/{cid}", json={
            "pool_id":       TestRangeConfigs.pool2_id,
            "ip_resolution": "imsi_apn",
        })
        assert resp.status_code == 200
        verify = http.get(f"/range-configs/{cid}").json()
        assert verify["pool_id"]       == TestRangeConfigs.pool2_id
        assert verify["ip_resolution"] == "imsi_apn"

    # 2.5 ─────────────────────────────────────────────────────────────────────
    def test_05_suspend_range_config(self, http: httpx.Client):
        """PATCH status=suspended → 200."""
        cid = TestRangeConfigs.config_id
        resp = http.patch(f"/range-configs/{cid}", json={"status": "suspended"})
        assert resp.status_code == 200
        verify = http.get(f"/range-configs/{cid}").json()
        assert verify["status"] == "suspended"

    # 2.6 ─────────────────────────────────────────────────────────────────────
    def test_06_delete_range_config(self, http: httpx.Client):
        """DELETE /range-configs/{id} → 204."""
        cid = TestRangeConfigs.config_id
        resp = http.delete(f"/range-configs/{cid}")
        assert resp.status_code == 204
        TestRangeConfigs.config_id = None

    # 2.7 ─────────────────────────────────────────────────────────────────────
    def test_07_inverted_imsi_range(self, http: httpx.Client):
        """POST /range-configs with f_imsi > t_imsi → 400 validation_failed."""
        resp = http.post("/range-configs", json={
            "account_name":  "Melita",
            "f_imsi":        T_IMSI,
            "t_imsi":        F_IMSI,   # inverted
            "pool_id":       TestRangeConfigs.pool_id,
            "ip_resolution": "imsi",
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # 2.8 ─────────────────────────────────────────────────────────────────────
    def test_08_non_15_digit_imsi(self, http: httpx.Client):
        """POST /range-configs with 14-digit f_imsi → 400 validation_failed."""
        resp = http.post("/range-configs", json={
            "account_name":  "Melita",
            "f_imsi":        "27877302000000",   # 14 digits
            "t_imsi":        T_IMSI,
            "pool_id":       TestRangeConfigs.pool_id,
            "ip_resolution": "imsi",
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"
