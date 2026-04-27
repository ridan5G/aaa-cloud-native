"""
test_01_pools.py — IP Pool CRUD + Stats + Routing Domain

Test cases 1.1 – 1.8  (plan-01 §test_01_pools)
Test cases 1.9 – 1.16 (routing domain overlap enforcement)
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
        resp = http.patch(f"/pools/{TestPools.pool_id}", json={"name": "renamed-pool"})
        assert resp.status_code == 200

        resp = http.get(f"/pools/{TestPools.pool_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "renamed-pool"

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
    def test_07_delete_pool_with_ip_in_use(self, http: httpx.Client):
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
            "name":         "bad-pool",
            "account_name": "Melita",
            "subnet":       "not-a-cidr",
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # Teardown: ensure any leftover pool from test_01 is removed
    def teardown_method(self, _method):
        pass  # test_06 deletes the pool; test_07 has its own teardown


# ─────────────────────────────────────────────────────────────────────────────
# Tests 1.9 – 1.16  Routing Domain overlap enforcement
# ─────────────────────────────────────────────────────────────────────────────

# Subnets used in this section — kept separate from subnets used by TestPools
# to avoid any cross-test interference.
RD_DOMAIN_A = "rd-test-domain-alpha"
RD_DOMAIN_B = "rd-test-domain-beta"
RD_SUBNET_A  = "100.65.200.0/24"   # /24 — used as first pool in domain A
RD_SUBNET_A2 = "100.65.200.0/25"   # overlaps RD_SUBNET_A (first half)
RD_SUBNET_A3 = "100.65.200.128/25" # overlaps RD_SUBNET_A (second half)
RD_SUBNET_B  = "100.65.201.0/24"   # distinct — used for same-domain happy path
RD_SUBNET_C  = "100.65.202.0/24"   # used in different-domain test


class TestRoutingDomain:
    """Routing domain overlap enforcement — tests 1.9 – 1.16."""

    # 1.9 ─────────────────────────────────────────────────────────────────────
    def test_09_pool_includes_routing_domain_in_response(self, http: httpx.Client):
        """POST /pools with routing_domain → GET confirms routing_domain name and routing_domain_id UUID returned."""
        pool = create_pool(
            http,
            subnet=RD_SUBNET_B,
            pool_name="rd-test-pool-b",
            account_name="Melita",
            routing_domain=RD_DOMAIN_A,
        )
        pid = pool["pool_id"]
        try:
            resp = http.get(f"/pools/{pid}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["routing_domain"] == RD_DOMAIN_A
            assert "routing_domain_id" in data, "routing_domain_id must be present"
            assert len(data["routing_domain_id"]) == 36, "routing_domain_id must be a UUID"
        finally:
            delete_pool(http, pid)

    # 1.10 ────────────────────────────────────────────────────────────────────
    def test_10_identical_subnet_same_domain_rejected(self, http: httpx.Client):
        """Two pools with identical subnets in the same routing domain → second returns 409."""
        pool = create_pool(
            http,
            subnet=RD_SUBNET_A,
            pool_name="rd-first-pool",
            account_name="Melita",
            routing_domain=RD_DOMAIN_A,
        )
        pid = pool["pool_id"]
        try:
            resp = http.post("/pools", json={
                "name":           "rd-duplicate-pool",
                "account_name":   "Melita",
                "routing_domain": RD_DOMAIN_A,
                "subnet":         RD_SUBNET_A,
            })
            assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert body.get("error") == "pool_overlap"
            assert "conflicting_pool_id" in body
            assert body["conflicting_pool_id"] == pid
        finally:
            delete_pool(http, pid)

    # 1.11 ────────────────────────────────────────────────────────────────────
    def test_11_overlapping_subnet_same_domain_rejected(self, http: httpx.Client):
        """A /25 that is a sub-range of an existing /24 in the same domain → 409."""
        pool = create_pool(
            http,
            subnet=RD_SUBNET_A,
            pool_name="rd-parent-pool",
            account_name="Melita",
            routing_domain=RD_DOMAIN_A,
        )
        pid = pool["pool_id"]
        try:
            # RD_SUBNET_A2 is 100.65.200.0/25 — entirely within 100.65.200.0/24
            resp = http.post("/pools", json={
                "name":           "rd-child-pool",
                "account_name":   "Melita",
                "routing_domain": RD_DOMAIN_A,
                "subnet":         RD_SUBNET_A2,
            })
            assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert body.get("error") == "pool_overlap"
            assert body.get("conflicting_pool_id") == pid

            # Also test the upper half
            resp2 = http.post("/pools", json={
                "name":           "rd-child-pool-upper",
                "account_name":   "Melita",
                "routing_domain": RD_DOMAIN_A,
                "subnet":         RD_SUBNET_A3,
            })
            assert resp2.status_code == 409
            assert resp2.json().get("error") == "pool_overlap"
        finally:
            delete_pool(http, pid)

    # 1.12 ────────────────────────────────────────────────────────────────────
    def test_12_same_subnet_different_domains_allowed(self, http: httpx.Client):
        """Same subnet in two different routing domains → both succeed (201)."""
        pool_a = create_pool(
            http,
            subnet=RD_SUBNET_C,
            pool_name="rd-domain-a-pool",
            account_name="Melita",
            routing_domain=RD_DOMAIN_A,
        )
        pool_b = create_pool(
            http,
            subnet=RD_SUBNET_C,
            pool_name="rd-domain-b-pool",
            account_name="Melita",
            routing_domain=RD_DOMAIN_B,
        )
        try:
            assert pool_a["pool_id"] != pool_b["pool_id"], "Different pools must have different IDs"
            # Both should be reachable
            for pid, expected_domain in [
                (pool_a["pool_id"], RD_DOMAIN_A),
                (pool_b["pool_id"], RD_DOMAIN_B),
            ]:
                resp = http.get(f"/pools/{pid}")
                assert resp.status_code == 200
                assert resp.json()["routing_domain"] == expected_domain
        finally:
            delete_pool(http, pool_a["pool_id"])
            delete_pool(http, pool_b["pool_id"])

    # 1.13 ────────────────────────────────────────────────────────────────────
    def test_13_list_pools_filtered_by_routing_domain(self, http: httpx.Client):
        """GET /pools?routing_domain=... returns only pools in that domain."""
        pool_a = create_pool(
            http,
            subnet=RD_SUBNET_A,
            pool_name="rd-filter-a",
            account_name="Melita",
            routing_domain=RD_DOMAIN_A,
        )
        pool_b = create_pool(
            http,
            subnet=RD_SUBNET_C,
            pool_name="rd-filter-b",
            account_name="Melita",
            routing_domain=RD_DOMAIN_B,
        )
        try:
            resp = http.get("/pools", params={"routing_domain": RD_DOMAIN_A})
            assert resp.status_code == 200
            ids_in_a = {p["pool_id"] for p in resp.json()["items"]}
            assert pool_a["pool_id"] in ids_in_a
            assert pool_b["pool_id"] not in ids_in_a

            resp2 = http.get("/pools", params={"routing_domain": RD_DOMAIN_B})
            assert resp2.status_code == 200
            ids_in_b = {p["pool_id"] for p in resp2.json()["items"]}
            assert pool_b["pool_id"] in ids_in_b
            assert pool_a["pool_id"] not in ids_in_b
        finally:
            delete_pool(http, pool_a["pool_id"])
            delete_pool(http, pool_b["pool_id"])

    # 1.14 ────────────────────────────────────────────────────────────────────
    def test_14_routing_domains_endpoint(self, http: httpx.Client):
        """GET /routing-domains returns a list containing the domains we created."""
        pool_a = create_pool(
            http,
            subnet=RD_SUBNET_A,
            pool_name="rd-domains-a",
            account_name="Melita",
            routing_domain=RD_DOMAIN_A,
        )
        pool_b = create_pool(
            http,
            subnet=RD_SUBNET_C,
            pool_name="rd-domains-b",
            account_name="Melita",
            routing_domain=RD_DOMAIN_B,
        )
        try:
            resp = http.get("/routing-domains")
            assert resp.status_code == 200
            # items is now a list of routing domain objects (not strings)
            domain_names = [d["name"] for d in resp.json()["items"]]
            assert RD_DOMAIN_A in domain_names, f"{RD_DOMAIN_A} not in {domain_names}"
            assert RD_DOMAIN_B in domain_names, f"{RD_DOMAIN_B} not in {domain_names}"
        finally:
            delete_pool(http, pool_a["pool_id"])
            delete_pool(http, pool_b["pool_id"])

    # 1.15 ────────────────────────────────────────────────────────────────────
    def test_15_routing_domain_immutable_via_patch(self, http: httpx.Client):
        """PATCH /pools/{id} with routing_domain field → field ignored, domain unchanged."""
        pool = create_pool(
            http,
            subnet=RD_SUBNET_A,
            pool_name="rd-immutable-test",
            account_name="Melita",
            routing_domain=RD_DOMAIN_A,
        )
        pid = pool["pool_id"]
        try:
            # PoolPatch model does not include routing_domain — extra fields are ignored by Pydantic.
            resp = http.patch(f"/pools/{pid}", json={
                "name":           "rd-immutable-renamed",
                "routing_domain": RD_DOMAIN_B,  # must be silently ignored
            })
            assert resp.status_code == 200

            resp2 = http.get(f"/pools/{pid}")
            assert resp2.status_code == 200
            data = resp2.json()
            assert data["name"] == "rd-immutable-renamed", "Rename should succeed"
            assert data["routing_domain"] == RD_DOMAIN_A, "routing_domain must not change"
        finally:
            delete_pool(http, pid)

    # 1.16 ────────────────────────────────────────────────────────────────────
    def test_16_default_routing_domain_when_omitted(self, http: httpx.Client):
        """POST /pools without routing_domain → GET returns routing_domain='default'."""
        # create_pool fixture sends no routing_domain when None is passed
        pool = create_pool(
            http,
            subnet=RD_SUBNET_A,
            pool_name="rd-default-domain",
            account_name="Melita",
            replace_on_conflict=True,
        )
        pid = pool["pool_id"]
        try:
            resp = http.get(f"/pools/{pid}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["routing_domain"] == "default"
            assert "routing_domain_id" in data, "routing_domain_id must be present"
            assert len(data["routing_domain_id"]) == 36, "routing_domain_id must be a UUID"
        finally:
            delete_pool(http, pid)
