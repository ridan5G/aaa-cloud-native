"""
test_01_pools.py — IP Pool CRUD + Stats

Test cases 1.1 – 1.8  (plan-01 §test_01_pools)
"""
import httpx
import pytest

from fixtures.pools import create_pool, delete_pool, get_pool_stats

SUBNET = "100.65.120.0/24"
USABLE = 253   # plan specifies 253 for a /24 (excludes network + broadcast + .254 gateway)


class TestPools:
    pool_id: str | None = None

    # pool_id is set by test_01 and shared across tests 02-06 (sequential).
    # Do NOT add setup_method here — it would wipe the pool_id before each test.

    # 1.1 ─────────────────────────────────────────────────────────────────────
    def test_01_create_pool(self, http: httpx.Client):
        """POST /pools with valid subnet → 201, pool_id UUID returned."""
        body = create_pool(
            http,
            subnet=SUBNET,
            pool_name="test-pool-01",
            account_name="Melita",
        )
        assert "pool_id" in body, "Response must contain pool_id"
        assert len(body["pool_id"]) == 36, "pool_id must be a UUID"
        TestPools.pool_id = body["pool_id"]

    # 1.2 ─────────────────────────────────────────────────────────────────────
    def test_02_get_pool(self, http: httpx.Client):
        """GET /pools/{pool_id} → 200, subnet / start_ip / end_ip correct."""
        assert TestPools.pool_id, "pool_id not set — test_01 must run first"
        resp = http.get(f"/pools/{TestPools.pool_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["subnet"] == SUBNET
        assert body["start_ip"].startswith("100.65.120.")
        assert body["end_ip"].startswith("100.65.120.")

    # 1.3 ─────────────────────────────────────────────────────────────────────
    def test_03_pool_stats_after_creation(self, http: httpx.Client):
        """GET /pools/{pool_id}/stats immediately after creation → available=253, allocated=0."""
        assert TestPools.pool_id
        stats = get_pool_stats(http, TestPools.pool_id)
        assert stats["allocated"] == 0,       f"Expected allocated=0, got {stats['allocated']}"
        assert stats["available"] == USABLE,  f"Expected available={USABLE}, got {stats['available']}"

    # 1.4 ─────────────────────────────────────────────────────────────────────
    def test_04_rename_pool(self, http: httpx.Client):
        """PATCH /pools/{pool_id} → rename; GET confirms new name."""
        assert TestPools.pool_id
        resp = http.patch(f"/pools/{TestPools.pool_id}", json={"pool_name": "renamed-pool"})
        assert resp.status_code == 200

        resp = http.get(f"/pools/{TestPools.pool_id}")
        assert resp.status_code == 200
        assert resp.json()["pool_name"] == "renamed-pool"

    # 1.5 ─────────────────────────────────────────────────────────────────────
    def test_05_list_pools_by_account(self, http: httpx.Client):
        """GET /pools?account_name=Melita → list includes created pool."""
        assert TestPools.pool_id
        resp = http.get("/pools", params={"account_name": "Melita"})
        assert resp.status_code == 200
        pool_ids = [p["pool_id"] for p in resp.json().get("items", resp.json())]
        assert TestPools.pool_id in pool_ids

    # 1.6 ─────────────────────────────────────────────────────────────────────
    def test_06_delete_pool_with_zero_allocations(self, http: httpx.Client):
        """DELETE /pools/{pool_id} with 0 allocations → 204."""
        assert TestPools.pool_id
        resp = http.delete(f"/pools/{TestPools.pool_id}")
        assert resp.status_code == 204
        TestPools.pool_id = None  # already deleted

    # 1.7 ─────────────────────────────────────────────────────────────────────
    def test_07_delete_pool_with_active_allocations(self, http: httpx.Client):
        """DELETE pool with active allocations → 409 pool_in_use."""
        # Create a pool and a profile that allocates from it
        pool = create_pool(http, subnet="100.65.121.0/24",
                           pool_name="pool-with-alloc", account_name="Melita")
        pid = pool["pool_id"]
        try:
            # Provision a profile that uses this pool
            from fixtures.profiles import create_profile_imsi, delete_profile
            pdata = create_profile_imsi(
                http,
                account_name="Melita",
                imsis=[{
                    "imsi":      "278773000099001",
                    "static_ip": "100.65.121.5",
                    "pool_id":   pid,
                }],
            )
            sim_id = pdata["sim_id"]
            # Now try to delete the pool — must fail with 409
            resp = http.delete(f"/pools/{pid}")
            assert resp.status_code == 409
            body = resp.json()
            assert body.get("error") == "pool_in_use"
        finally:
            # Teardown: delete profile first, then pool
            try:
                from fixtures.profiles import delete_profile
                delete_profile(http, sim_id)
            except Exception:
                pass
            delete_pool(http, pid)

    # 1.8 ─────────────────────────────────────────────────────────────────────
    def test_08_create_pool_invalid_subnet(self, http: httpx.Client):
        """POST /pools with invalid CIDR → 400 validation_failed."""
        resp = http.post("/pools", json={
            "pool_name":    "bad-pool",
            "account_name": "Melita",
            "subnet":       "not-a-cidr",
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # Teardown: ensure any leftover pool from test_01 is removed
    def teardown_method(self, _method):
        pass  # test_06 deletes the pool; test_07 has its own teardown
