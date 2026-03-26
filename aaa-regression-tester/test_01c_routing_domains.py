"""
test_01c_routing_domains.py — Routing Domain CRUD + suggest-cidr + allowed_prefixes

Test cases cover:
  1c.1  Create routing domain → 201 with id and name
  1c.2  Duplicate name → 409 domain_name_conflict
  1c.3  GET /routing-domains/{id} → 200 with full object
  1c.4  GET /routing-domains/{id} not found → 404
  1c.5  PATCH name → 200; GET confirms rename
  1c.6  PATCH allowed_prefixes → 200; GET confirms update
  1c.7  DELETE empty domain → 204
  1c.8  DELETE domain with pools → 409 domain_in_use
  1c.9  suggest-cidr no allowed_prefixes → 422 no_allowed_prefixes
  1c.10 suggest-cidr returns valid free CIDR
  1c.11 suggest-cidr with existing pools skips occupied ranges
  1c.12 suggest-cidr domain not found → 404
  1c.13 POST /pools subnet outside allowed_prefixes → 409
  1c.14 POST /pools subnet inside allowed_prefixes → 201
  1c.15 POST /pools routing_domain_id by UUID → 201; response includes routing_domain_id
  1c.16 POST /routing-domains empty name → 400
  1c.17 POST /routing-domains invalid CIDR in allowed_prefixes → 400
"""
import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN
from fixtures.pools import create_pool, delete_pool


# ─── Helpers ──────────────────────────────────────────────────────────────────

def create_domain(
    http: httpx.Client,
    name: str,
    description: str | None = None,
    allowed_prefixes: list[str] | None = None,
) -> dict:
    """POST /routing-domains and assert 201. Returns response body."""
    body: dict = {"name": name}
    if description is not None:
        body["description"] = description
    if allowed_prefixes is not None:
        body["allowed_prefixes"] = allowed_prefixes
    resp = http.post("/routing-domains", json=body)
    assert resp.status_code == 201, f"create_domain failed: {resp.status_code} {resp.text}"
    return resp.json()


def delete_domain(http: httpx.Client, domain_id: str) -> None:
    """DELETE /routing-domains/{id} — best-effort teardown (ignores 404)."""
    resp = http.delete(f"/routing-domains/{domain_id}")
    if resp.status_code not in (204, 404, 409):
        raise AssertionError(
            f"delete_domain({domain_id}) returned unexpected {resp.status_code}: {resp.text}"
        )


# ─── Test constants ────────────────────────────────────────────────────────────

TD_NAME    = "test-rd-1c-alpha"
TD_NAME_B  = "test-rd-1c-beta"
TD_PREFIX  = "10.99.0.0/16"           # allowed prefix for suggest-cidr tests
TD_SUBNET  = "10.99.0.0/24"           # inside TD_PREFIX
TD_SUBNET2 = "10.99.1.0/24"           # inside TD_PREFIX, non-overlapping
TD_OUTSIDE = "192.168.55.0/24"        # outside TD_PREFIX


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestRoutingDomainCRUD:
    """Routing domain CRUD — tests 1c.1 – 1c.8."""

    # Names used across all tests in this class — purged before the suite runs
    # so a previous crashed run cannot leave stale domains behind.
    _CLEANUP_NAMES = (TD_NAME, TD_NAME_B, TD_NAME + "-renamed")

    @classmethod
    def setup_class(cls):
        """Delete any routing domains left over from a previous interrupted run."""
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=15.0,
        ) as c:
            r = c.get("/routing-domains")
            if r.status_code != 200:
                return  # can't list — skip cleanup, individual tests will surface errors
            items = r.json()
            if isinstance(items, dict):
                items = items.get("items", [])
            for d in items:
                if d.get("name") in cls._CLEANUP_NAMES:
                    c.delete(f"/routing-domains/{d['id']}")

    # 1c.1 ────────────────────────────────────────────────────────────────────
    def test_01c_01_create_domain(self, http: httpx.Client):
        """POST /routing-domains → 201 with id (UUID) and name."""
        body = create_domain(http, TD_NAME, description="test domain alpha")
        try:
            assert "id" in body, "Response must contain id"
            assert len(body["id"]) == 36, "id must be a UUID (36 chars)"
            assert body["name"] == TD_NAME
        finally:
            delete_domain(http, body["id"])

    # 1c.2 ────────────────────────────────────────────────────────────────────
    def test_01c_02_duplicate_name_rejected(self, http: httpx.Client):
        """POST /routing-domains with existing name → 409 domain_name_conflict."""
        body = create_domain(http, TD_NAME)
        did = body["id"]
        try:
            resp = http.post("/routing-domains", json={"name": TD_NAME})
            assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
            assert resp.json().get("error") == "domain_name_conflict"
        finally:
            delete_domain(http, did)

    # 1c.3 ────────────────────────────────────────────────────────────────────
    def test_01c_03_get_domain(self, http: httpx.Client):
        """GET /routing-domains/{id} → 200 with full object including pool_count."""
        body = create_domain(
            http, TD_NAME, description="desc", allowed_prefixes=[TD_PREFIX]
        )
        did = body["id"]
        try:
            resp = http.get(f"/routing-domains/{did}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == did
            assert data["name"] == TD_NAME
            assert data["description"] == "desc"
            assert TD_PREFIX in data["allowed_prefixes"]
            assert "pool_count" in data
        finally:
            delete_domain(http, did)

    # 1c.4 ────────────────────────────────────────────────────────────────────
    def test_01c_04_get_domain_not_found(self, http: httpx.Client):
        """GET /routing-domains/{unknown-uuid} → 404 not_found."""
        resp = http.get("/routing-domains/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
        assert resp.json().get("error") == "not_found"

    # 1c.5 ────────────────────────────────────────────────────────────────────
    def test_01c_05_patch_name(self, http: httpx.Client):
        """PATCH name → 200; subsequent GET confirms new name."""
        body = create_domain(http, TD_NAME)
        did = body["id"]
        new_name = TD_NAME + "-renamed"
        try:
            resp = http.patch(f"/routing-domains/{did}", json={"name": new_name})
            assert resp.status_code == 200

            resp2 = http.get(f"/routing-domains/{did}")
            assert resp2.status_code == 200
            assert resp2.json()["name"] == new_name
        finally:
            delete_domain(http, did)

    # 1c.6 ────────────────────────────────────────────────────────────────────
    def test_01c_06_patch_allowed_prefixes(self, http: httpx.Client):
        """PATCH allowed_prefixes → 200; GET confirms update."""
        body = create_domain(http, TD_NAME)
        did = body["id"]
        try:
            resp = http.patch(
                f"/routing-domains/{did}",
                json={"allowed_prefixes": [TD_PREFIX, "172.16.0.0/12"]},
            )
            assert resp.status_code == 200

            resp2 = http.get(f"/routing-domains/{did}")
            assert resp2.status_code == 200
            prefixes = resp2.json()["allowed_prefixes"]
            assert TD_PREFIX in prefixes
            assert "172.16.0.0/12" in prefixes
        finally:
            delete_domain(http, did)

    # 1c.7 ────────────────────────────────────────────────────────────────────
    def test_01c_07_delete_empty_domain(self, http: httpx.Client):
        """DELETE /routing-domains/{id} with no pools → 204."""
        body = create_domain(http, TD_NAME)
        did = body["id"]
        resp = http.delete(f"/routing-domains/{did}")
        assert resp.status_code == 204
        # Confirm it's gone
        assert http.get(f"/routing-domains/{did}").status_code == 404

    # 1c.8 ────────────────────────────────────────────────────────────────────
    def test_01c_08_delete_domain_with_pools_rejected(self, http: httpx.Client):
        """DELETE /routing-domains/{id} with pools → 409 domain_in_use."""
        body = create_domain(http, TD_NAME)
        did = body["id"]
        pool = create_pool(
            http,
            subnet="10.200.0.0/24",
            pool_name="rd-1c-pool-blocked",
            account_name="TestAccount",
            routing_domain=TD_NAME,
        )
        pid = pool["pool_id"]
        try:
            resp = http.delete(f"/routing-domains/{did}")
            assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
            err = resp.json()
            assert err.get("error") == "domain_in_use"
            assert err.get("pool_count", 0) >= 1
        finally:
            delete_pool(http, pid)
            delete_domain(http, did)


class TestSuggestCidr:
    """suggest-cidr endpoint — tests 1c.9 – 1c.12."""

    # 1c.9 ────────────────────────────────────────────────────────────────────
    def test_01c_09_suggest_cidr_no_prefixes(self, http: httpx.Client):
        """GET suggest-cidr on domain with no allowed_prefixes → 422 no_allowed_prefixes."""
        body = create_domain(http, TD_NAME)
        did = body["id"]
        try:
            resp = http.get(f"/routing-domains/{did}/suggest-cidr", params={"size": 10})
            assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
            assert resp.json().get("error") == "no_allowed_prefixes"
        finally:
            delete_domain(http, did)

    # 1c.10 ───────────────────────────────────────────────────────────────────
    def test_01c_10_suggest_cidr_returns_free_block(self, http: httpx.Client):
        """GET suggest-cidr with size=50 → 200 with valid suggested_cidr within allowed_prefixes."""
        body = create_domain(http, TD_NAME, allowed_prefixes=[TD_PREFIX])
        did = body["id"]
        try:
            resp = http.get(
                f"/routing-domains/{did}/suggest-cidr", params={"size": 50}
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            data = resp.json()
            assert "suggested_cidr" in data
            assert "prefix_len" in data
            assert "usable_hosts" in data
            assert data["usable_hosts"] >= 50
            assert data["routing_domain_id"] == did
            # The suggested CIDR must be within the allowed prefix (10.99.0.0/16)
            suggested = data["suggested_cidr"]
            assert suggested.startswith("10.99."), \
                f"Suggested CIDR {suggested} not within allowed prefix {TD_PREFIX}"
        finally:
            delete_domain(http, did)

    # 1c.11 ───────────────────────────────────────────────────────────────────
    def test_01c_11_suggest_cidr_skips_occupied_ranges(self, http: httpx.Client):
        """suggest-cidr skips blocks already occupied by existing pools."""
        body = create_domain(http, TD_NAME, allowed_prefixes=[TD_PREFIX])
        did = body["id"]
        # Create a pool occupying the first /24 in the prefix (10.99.0.0/24)
        pool = create_pool(
            http,
            subnet=TD_SUBNET,
            pool_name="rd-1c-occupy",
            account_name="TestAccount",
            routing_domain=TD_NAME,
        )
        pid = pool["pool_id"]
        try:
            resp = http.get(
                f"/routing-domains/{did}/suggest-cidr", params={"size": 50}
            )
            assert resp.status_code == 200
            suggested = resp.json()["suggested_cidr"]
            # Must NOT suggest the already-occupied subnet
            assert suggested != TD_SUBNET, \
                f"suggest-cidr returned occupied subnet {TD_SUBNET}"
            # Must still be within the allowed prefix
            assert suggested.startswith("10.99."), \
                f"Suggested CIDR {suggested} not within allowed prefix {TD_PREFIX}"
        finally:
            delete_pool(http, pid)
            delete_domain(http, did)

    # 1c.12 ───────────────────────────────────────────────────────────────────
    def test_01c_12_suggest_cidr_domain_not_found(self, http: httpx.Client):
        """GET suggest-cidr for unknown domain UUID → 404 not_found."""
        resp = http.get(
            "/routing-domains/00000000-0000-0000-0000-000000000000/suggest-cidr",
            params={"size": 10},
        )
        assert resp.status_code == 404
        assert resp.json().get("error") == "not_found"


class TestAllowedPrefixesEnforcement:
    """allowed_prefixes pool validation — tests 1c.13 – 1c.15."""

    # 1c.13 ───────────────────────────────────────────────────────────────────
    def test_01c_13_subnet_outside_allowed_prefixes_rejected(self, http: httpx.Client):
        """POST /pools with subnet outside domain's allowed_prefixes → 409."""
        body = create_domain(http, TD_NAME, allowed_prefixes=[TD_PREFIX])
        did = body["id"]
        try:
            resp = http.post("/pools", json={
                "name":              "rd-1c-outside-pool",
                "account_name":      "TestAccount",
                "routing_domain_id": did,
                "subnet":            TD_OUTSIDE,  # 192.168.55.0/24 — outside 10.99.0.0/16
            })
            assert resp.status_code == 409, \
                f"Expected 409 subnet_outside_allowed_prefixes, got {resp.status_code}: {resp.text}"
            err = resp.json()
            assert err.get("error") == "subnet_outside_allowed_prefixes"
            assert "allowed_prefixes" in err
        finally:
            delete_domain(http, did)

    # 1c.14 ───────────────────────────────────────────────────────────────────
    def test_01c_14_subnet_inside_allowed_prefixes_accepted(self, http: httpx.Client):
        """POST /pools with subnet inside domain's allowed_prefixes → 201."""
        body = create_domain(http, TD_NAME, allowed_prefixes=[TD_PREFIX])
        did = body["id"]
        pool_id: str | None = None
        try:
            resp = http.post("/pools", json={
                "name":              "rd-1c-inside-pool",
                "account_name":      "TestAccount",
                "routing_domain_id": did,
                "subnet":            TD_SUBNET,  # 10.99.0.0/24 — inside 10.99.0.0/16
            })
            assert resp.status_code == 201, \
                f"Expected 201, got {resp.status_code}: {resp.text}"
            pool_id = resp.json()["pool_id"]
        finally:
            if pool_id:
                delete_pool(http, pool_id)
            delete_domain(http, did)

    # 1c.15 ───────────────────────────────────────────────────────────────────
    def test_01c_15_create_pool_by_routing_domain_id(self, http: httpx.Client):
        """POST /pools with routing_domain_id (UUID) → 201; response includes routing_domain_id."""
        body = create_domain(http, TD_NAME)
        did = body["id"]
        pool_id: str | None = None
        try:
            resp = http.post("/pools", json={
                "name":              "rd-1c-uuid-pool",
                "account_name":      "TestAccount",
                "routing_domain_id": did,
                "subnet":            "10.200.1.0/24",
            })
            assert resp.status_code == 201, \
                f"Expected 201, got {resp.status_code}: {resp.text}"
            pool_id = resp.json()["pool_id"]

            # GET the pool and confirm routing_domain_id matches
            get_resp = http.get(f"/pools/{pool_id}")
            assert get_resp.status_code == 200
            pdata = get_resp.json()
            assert pdata["routing_domain_id"] == did, \
                f"routing_domain_id mismatch: {pdata['routing_domain_id']} != {did}"
            assert pdata["routing_domain"] == TD_NAME
        finally:
            if pool_id:
                delete_pool(http, pool_id)
            delete_domain(http, did)


class TestRoutingDomainValidation:
    """Input validation — tests 1c.16 – 1c.17."""

    # 1c.16 ───────────────────────────────────────────────────────────────────
    def test_01c_16_empty_name_rejected(self, http: httpx.Client):
        """POST /routing-domains with empty name → 400 validation_failed."""
        resp = http.post("/routing-domains", json={"name": ""})
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # 1c.17 ───────────────────────────────────────────────────────────────────
    def test_01c_17_invalid_cidr_in_prefixes_rejected(self, http: httpx.Client):
        """POST /routing-domains with invalid CIDR in allowed_prefixes → 400."""
        resp = http.post("/routing-domains", json={
            "name":             TD_NAME,
            "allowed_prefixes": ["not-a-cidr"],
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"
