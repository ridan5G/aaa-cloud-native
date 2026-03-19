"""
test_03_profiles_a.py — Profile A: ip_resolution = "iccid"

All GET /lookup calls use IMSI + APN as input.
APN is IGNORED in iccid mode — the card-level IP is always returned.

Test cases 3.1 – 3.9  (plan-01 §test_03_profiles_a)
"""
import httpx

from conftest import PROVISION_BASE, JWT_TOKEN
from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import create_profile_iccid, delete_profile

IMSI1  = "278773030000001"
IMSI2  = "278773030000002"
ICCID  = "8944501030000000001"   # 19 digits
POOL_SUBNET = "100.65.140.0/24"
STATIC_IP   = "100.65.140.5"


class TestProfileA:
    pool_id:   str | None = None
    sim_id: str | None = None

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet=POOL_SUBNET,
                            pool_name="pool-a-03", account_name="TestAccount")
            cls.pool_id = p["pool_id"]

    @classmethod
    def teardown_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            if cls.sim_id:
                delete_profile(c, cls.sim_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # 3.1 ─────────────────────────────────────────────────────────────────────
    def test_01_create_profile_iccid(self, http: httpx.Client):
        """POST /profiles — iccid mode, 2 IMSIs, 1 iccid_ip → 201."""
        body = create_profile_iccid(
            http,
            iccid=ICCID,
            account_name="TestAccount",
            imsis=[IMSI1, IMSI2],
            static_ip=STATIC_IP,
            pool_id=TestProfileA.pool_id,
        )
        assert "sim_id" in body
        TestProfileA.sim_id = body["sim_id"]

    # 3.2 ─────────────────────────────────────────────────────────────────────
    def test_02_get_profile(self, http: httpx.Client):
        """GET /profiles/{sim_id} → 200; iccid_ips[0].static_ip correct."""
        resp = http.get(f"/profiles/{TestProfileA.sim_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["iccid"] == ICCID
        assert body["ip_resolution"] == "iccid"
        iccid_ips = body.get("iccid_ips", [])
        assert any(ip["static_ip"] == STATIC_IP for ip in iccid_ips), (
            f"Expected {STATIC_IP} in iccid_ips, got {iccid_ips}"
        )

    # 3.3 ─────────────────────────────────────────────────────────────────────
    def test_03_lookup_imsi1(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI1&apn=internet → 200 with STATIC_IP."""
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI1, "apn": "internet.operator.com"})
        assert resp.status_code == 200
        assert resp.json()["static_ip"] == STATIC_IP

    # 3.4 ─────────────────────────────────────────────────────────────────────
    def test_04_lookup_imsi2_different_apn(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI2&apn=ims → 200 with same card IP (APN ignored)."""
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI2, "apn": "ims.operator.com"})
        assert resp.status_code == 200
        assert resp.json()["static_ip"] == STATIC_IP

    # 3.5 ─────────────────────────────────────────────────────────────────────
    def test_05_lookup_garbage_apn(self, lookup_http: httpx.Client):
        """GET /lookup with garbage APN → 200 (iccid mode ignores APN)."""
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI1, "apn": "any.garbage.apn"})
        assert resp.status_code == 200
        assert resp.json()["static_ip"] == STATIC_IP

    # 3.6 ─────────────────────────────────────────────────────────────────────
    def test_06_suspend_sim(self, http: httpx.Client):
        """PATCH status=suspended → 200."""
        resp = http.patch(f"/profiles/{TestProfileA.sim_id}",
                          json={"status": "suspended"})
        assert resp.status_code == 200

    # 3.7 ─────────────────────────────────────────────────────────────────────
    def test_07_lookup_suspended(self, lookup_http: httpx.Client):
        """GET /lookup for suspended SIM → 403 {error: suspended}."""
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI1, "apn": "internet.operator.com"})
        assert resp.status_code == 403
        assert resp.json()["error"] == "suspended"

    # 3.8 ─────────────────────────────────────────────────────────────────────
    def test_08_reactivate_and_lookup(self, http: httpx.Client, lookup_http: httpx.Client):
        """PATCH status=active → 200; subsequent GET /lookup resolves again."""
        resp = http.patch(f"/profiles/{TestProfileA.sim_id}",
                          json={"status": "active"})
        assert resp.status_code == 200
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI1, "apn": "internet.operator.com"})
        assert resp.status_code == 200
        assert resp.json()["static_ip"] == STATIC_IP

    # 3.9 ─────────────────────────────────────────────────────────────────────
    def test_09_delete_profile(self, http: httpx.Client):
        """DELETE /profiles/{sim_id} → 204; subsequent GET returns 200 with status=terminated."""
        resp = http.delete(f"/profiles/{TestProfileA.sim_id}")
        assert resp.status_code == 204

        # Terminated profiles are still readable — status reflects the deletion
        resp = http.get(f"/profiles/{TestProfileA.sim_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "terminated"
        TestProfileA.sim_id = None
