"""
test_10_errors.py — Validation, conflict, and authentication error handling.

Verifies that the API returns the correct HTTP status codes and error bodies
for every defined failure mode — invalid inputs, duplicate data, bad auth,
missing parameters, and state transitions.

Test cases 10.1 – 10.15  (plan-01 §test_10_errors)
"""
import httpx
import pytest

from conftest import make_imsi, make_iccid
from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import (
    create_profile_iccid,
    create_profile_imsi,
    delete_profile,
)

MODULE = 10

# Pool shared across all tests in this module
POOL_SUBNET = "100.65.230.0/24"

# Two IMSIs used to set up conflict scenarios
IMSI_EXISTING  = make_imsi(MODULE, 1)   # used in 10.5 / 10.6 conflict tests
ICCID_EXISTING = make_iccid(MODULE, 1)  # used in 10.5 / 10.9 conflict tests
IP_EXISTING    = "100.65.230.1"

IMSI_SECOND    = make_imsi(MODULE, 2)   # second profile for 10.9 ICCID conflict
IP_SECOND      = "100.65.230.2"

# Profile used across multiple tests (10.10 / 10.11 / 10.12)
IMSI_MAIN      = make_imsi(MODULE, 10)
IP_MAIN_A      = "100.65.230.10"
IP_MAIN_ICCID  = "100.65.230.11"
ICCID_MAIN     = make_iccid(MODULE, 10)


class TestErrors:
    pool_id:          str | None = None
    device_conflict:  str | None = None   # profile for conflict tests
    device_second:    str | None = None   # second profile for ICCID-conflict test
    device_main:      str | None = None   # profile for state-transition tests

    @classmethod
    def setup_class(cls):
        import os, httpx as _h
        base = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
        jwt  = os.getenv("TEST_JWT", "dev-skip-verify")
        with _h.Client(base_url=base,
                       headers={"Authorization": f"Bearer {jwt}"},
                       timeout=30.0) as c:
            p = create_pool(c, subnet=POOL_SUBNET,
                            pool_name="pool-err-10", account_name="TestAccount")
            cls.pool_id = p["pool_id"]

            # Profile for IMSI / ICCID conflict tests (10.5 / 10.6 / 10.9)
            b = create_profile_iccid(
                c, iccid=ICCID_EXISTING, account_name="TestAccount",
                imsis=[IMSI_EXISTING],
                static_ip=IP_EXISTING,
                pool_id=cls.pool_id,
            )
            cls.device_conflict = b["device_id"]

            # A second profile (different IMSI, different ICCID) for 10.9
            b2 = create_profile_imsi(
                c, iccid=None, account_name="TestAccount",
                imsis=[{"imsi": IMSI_SECOND, "static_ip": IP_SECOND,
                        "pool_id": cls.pool_id}],
            )
            cls.device_second = b2["device_id"]

            # Profile for suspend/transition tests (10.10 / 10.11 / 10.12)
            b3 = create_profile_imsi(
                c, iccid=None, account_name="TestAccount",
                imsis=[{"imsi": IMSI_MAIN, "static_ip": IP_MAIN_A,
                        "pool_id": cls.pool_id}],
            )
            cls.device_main = b3["device_id"]

    @classmethod
    def teardown_class(cls):
        import os, httpx as _h
        base = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
        jwt  = os.getenv("TEST_JWT", "dev-skip-verify")
        with _h.Client(base_url=base,
                       headers={"Authorization": f"Bearer {jwt}"},
                       timeout=30.0) as c:
            for did in (cls.device_conflict, cls.device_second, cls.device_main):
                if did:
                    delete_profile(c, did)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # 10.1 ────────────────────────────────────────────────────────────────────
    def test_01_post_profile_imsi_too_short(self, http: httpx.Client):
        """POST /profiles — IMSI with 14 digits → 400, field=imsi."""
        r = http.post("/profiles", json={
            "iccid": None, "account_name": "TestAccount",
            "status": "active", "ip_resolution": "imsi",
            "imsis": [
                {"imsi": "27877310000001",   # 14 digits (one short)
                 "apn_ips": [{"static_ip": "100.65.230.100",
                              "pool_id": TestErrors.pool_id}]},
            ],
        })
        assert r.status_code == 400, \
            f"Expected 400 for 14-digit IMSI, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("field") in ("imsi", "imsis") \
            or "imsi" in str(body).lower(), \
            f"Error body does not mention 'imsi': {body}"

    # 10.2 ────────────────────────────────────────────────────────────────────
    def test_02_post_profile_iccid_too_short(self, http: httpx.Client):
        """POST /profiles — ICCID with 10 digits → 400, field=iccid."""
        r = http.post("/profiles", json={
            "iccid": "8944501000",  # only 10 digits
            "account_name": "TestAccount",
            "status": "active", "ip_resolution": "iccid",
            "imsis": [{"imsi": make_imsi(MODULE, 901), "apn_ips": []}],
            "iccid_ips": [{"static_ip": "100.65.230.101",
                           "pool_id": TestErrors.pool_id,
                           "pool_name": "pool-err-10"}],
        })
        assert r.status_code == 400, \
            f"Expected 400 for 10-digit ICCID, got {r.status_code}: {r.text}"
        body = r.json()
        assert "iccid" in str(body).lower(), \
            f"Error body does not mention 'iccid': {body}"

    # 10.3 ────────────────────────────────────────────────────────────────────
    def test_03_post_profile_missing_ip_resolution(self, http: httpx.Client):
        """POST /profiles — missing ip_resolution → 400."""
        r = http.post("/profiles", json={
            "iccid": None,
            "account_name": "TestAccount",
            "status": "active",
            # ip_resolution intentionally omitted
            "imsis": [
                {"imsi": make_imsi(MODULE, 902),
                 "apn_ips": [{"static_ip": "100.65.230.102",
                              "pool_id": TestErrors.pool_id}]},
            ],
        })
        assert r.status_code == 400, \
            f"Expected 400 for missing ip_resolution, got {r.status_code}: {r.text}"

    # 10.4 ────────────────────────────────────────────────────────────────────
    def test_04_post_profile_bogus_ip_resolution(self, http: httpx.Client):
        """POST /profiles — ip_resolution=bogus_value → 400."""
        r = http.post("/profiles", json={
            "iccid": None,
            "account_name": "TestAccount",
            "status": "active",
            "ip_resolution": "bogus_value",
            "imsis": [
                {"imsi": make_imsi(MODULE, 903),
                 "apn_ips": [{"static_ip": "100.65.230.103",
                              "pool_id": TestErrors.pool_id}]},
            ],
        })
        assert r.status_code == 400, \
            f"Expected 400 for bogus ip_resolution, got {r.status_code}: {r.text}"

    # 10.5 ────────────────────────────────────────────────────────────────────
    def test_05_post_profile_duplicate_iccid(self, http: httpx.Client):
        """POST /profiles — ICCID already used by existing profile → 409 iccid_conflict."""
        r = http.post("/profiles", json={
            "iccid": ICCID_EXISTING,    # already taken
            "account_name": "TestAccount",
            "status": "active",
            "ip_resolution": "iccid",
            "imsis": [{"imsi": make_imsi(MODULE, 904), "apn_ips": []}],
            "iccid_ips": [{"static_ip": "100.65.230.104",
                           "pool_id": TestErrors.pool_id,
                           "pool_name": "pool-err-10"}],
        })
        assert r.status_code == 409, \
            f"Expected 409 iccid_conflict, got {r.status_code}: {r.text}"
        assert r.json().get("error") in ("iccid_conflict", "conflict"), \
            f"Unexpected error: {r.json()}"

    # 10.6 ────────────────────────────────────────────────────────────────────
    def test_06_post_profile_duplicate_imsi(self, http: httpx.Client):
        """POST /profiles — IMSI already assigned to another profile → 409 imsi_conflict."""
        r = http.post("/profiles", json={
            "iccid": None,
            "account_name": "TestAccount",
            "status": "active",
            "ip_resolution": "imsi",
            "imsis": [
                {"imsi": IMSI_EXISTING,   # already on device_conflict
                 "apn_ips": [{"static_ip": "100.65.230.105",
                              "pool_id": TestErrors.pool_id}]},
            ],
        })
        assert r.status_code == 409, \
            f"Expected 409 imsi_conflict, got {r.status_code}: {r.text}"
        assert r.json().get("error") in ("imsi_conflict", "conflict"), \
            f"Unexpected error: {r.json()}"

    # 10.7 ────────────────────────────────────────────────────────────────────
    def test_07_get_unknown_profile_returns_404(self, http: httpx.Client):
        """GET /profiles/{unknown_uuid} → 404."""
        r = http.get("/profiles/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404

    # 10.8 ────────────────────────────────────────────────────────────────────
    def test_08_delete_nonexistent_profile_returns_404(self, http: httpx.Client):
        """DELETE /profiles/{unknown_uuid} → 404."""
        r = http.delete("/profiles/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404

    # 10.9 ────────────────────────────────────────────────────────────────────
    def test_09_patch_iccid_already_used_by_other_profile(self, http: httpx.Client):
        """PATCH /profiles/{device_second} iccid=ICCID_EXISTING → 409 iccid_conflict."""
        r = http.patch(
            f"/profiles/{TestErrors.device_second}",
            json={"iccid": ICCID_EXISTING},  # belongs to device_conflict
        )
        assert r.status_code == 409, \
            f"Expected 409 for ICCID conflict on PATCH, got {r.status_code}: {r.text}"

    # 10.10 ───────────────────────────────────────────────────────────────────
    def test_10_lookup_suspended_sim_returns_403(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """PATCH status=suspended → GET /lookup → 403 {"error":"suspended"}."""
        r = http.patch(f"/profiles/{TestErrors.device_main}",
                       json={"status": "suspended"})
        assert r.status_code == 200

        r_lookup = lookup_http.get("/lookup",
                                   params={"imsi": IMSI_MAIN,
                                           "apn": "internet.operator.com"})
        assert r_lookup.status_code == 403
        assert r_lookup.json().get("error") == "suspended"

        # Reactivate for subsequent tests
        http.patch(f"/profiles/{TestErrors.device_main}",
                   json={"status": "active"})

    # 10.11 ───────────────────────────────────────────────────────────────────
    def test_11_patch_ip_resolution_imsi_to_imsi_apn_without_apn_field(
            self, http: httpx.Client):
        """PATCH ip_resolution=imsi→imsi_apn without supplying apn fields → 400."""
        r = http.patch(
            f"/profiles/{TestErrors.device_main}",
            json={"ip_resolution": "imsi_apn"},
            # No apn_ips with distinct APNs provided — must fail validation
        )
        assert r.status_code == 400, (
            f"Expected 400 when switching to imsi_apn without apn data, "
            f"got {r.status_code}: {r.text}"
        )

    # 10.12 ───────────────────────────────────────────────────────────────────
    def test_12_patch_ip_resolution_imsi_to_iccid(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """PATCH ip_resolution=imsi→iccid with valid iccid_ips → 200; GET /lookup returns iccid IP."""
        r = http.patch(
            f"/profiles/{TestErrors.device_main}",
            json={
                "ip_resolution": "iccid",
                "iccid": ICCID_MAIN,
                "iccid_ips": [
                    {"static_ip": IP_MAIN_ICCID,
                     "pool_id":   TestErrors.pool_id,
                     "pool_name": "pool-err-10"},
                ],
            },
        )
        assert r.status_code == 200, \
            f"Expected 200 on valid mode change, got {r.status_code}: {r.text}"

        # Lookup now returns the iccid IP regardless of APN
        r_lookup = lookup_http.get("/lookup",
                                   params={"imsi": IMSI_MAIN,
                                           "apn": "internet.operator.com"})
        assert r_lookup.status_code == 200
        assert r_lookup.json()["static_ip"] == IP_MAIN_ICCID

    # 10.13 ───────────────────────────────────────────────────────────────────
    def test_13_lookup_missing_apn_param(self, lookup_http: httpx.Client):
        """GET /lookup with missing apn parameter → 400."""
        r = lookup_http.get("/lookup", params={"imsi": IMSI_MAIN})
        assert r.status_code == 400, \
            f"Expected 400 for missing apn, got {r.status_code}: {r.text}"

    # 10.14 ───────────────────────────────────────────────────────────────────
    def test_14_lookup_missing_imsi_param(self, lookup_http: httpx.Client):
        """GET /lookup with missing imsi parameter → 400."""
        r = lookup_http.get("/lookup", params={"apn": "internet.operator.com"})
        assert r.status_code == 400, \
            f"Expected 400 for missing imsi, got {r.status_code}: {r.text}"

    # 10.15 ───────────────────────────────────────────────────────────────────
    def test_15_invalid_jwt_returns_401(self, unauthed_http: httpx.Client):
        """Any endpoint with invalid / missing JWT → 401."""
        # Provision API
        r1 = unauthed_http.get("/profiles")
        assert r1.status_code == 401, \
            f"Expected 401 on provision API, got {r1.status_code}"

        # Lookup service (needs its own unauthed client)
        import os, httpx as _h
        base_lookup = os.getenv("LOOKUP_URL", "http://localhost:8081/v1")
        with _h.Client(
            base_url=base_lookup,
            headers={"Authorization": "Bearer invalid-token"},
            timeout=10.0,
        ) as bad:
            r2 = bad.get("/lookup",
                         params={"imsi": IMSI_MAIN,
                                 "apn": "internet.operator.com"})
            assert r2.status_code == 401, \
                f"Expected 401 on lookup service, got {r2.status_code}"
