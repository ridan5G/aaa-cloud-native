"""
test_04_profiles_b.py — Profile B: ip_resolution = "imsi"

Each IMSI has its own APN-agnostic IP.  APN is ignored.
Per-IMSI suspend is supported; SIM-level suspend affects all IMSIs.

Test cases 4.1 – 4.9  (plan-01 §test_04_profiles_b)
"""
import httpx

from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import create_profile_imsi, delete_profile

IMSI1 = "278773040000001"
IMSI2 = "278773040000002"
ICCID = "8944501040000000001"
IP1   = "100.65.150.5"
IP2   = "101.65.150.5"
IP_NEW = "100.65.150.99"
POOL_SUBNET = "100.65.150.0/24"


class TestProfileB:
    pool_id:   str | None = None
    device_id: str | None = None

    @classmethod
    def setup_class(cls):
        import os, httpx as _h
        base = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
        jwt  = os.getenv("TEST_JWT", "dev-skip-verify")
        with _h.Client(base_url=base,
                       headers={"Authorization": f"Bearer {jwt}"},
                       timeout=30.0) as c:
            p = create_pool(c, subnet=POOL_SUBNET,
                            pool_name="pool-b-04", account_name="TestAccount")
            cls.pool_id = p["pool_id"]

    @classmethod
    def teardown_class(cls):
        import os, httpx as _h
        base = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
        jwt  = os.getenv("TEST_JWT", "dev-skip-verify")
        with _h.Client(base_url=base,
                       headers={"Authorization": f"Bearer {jwt}"},
                       timeout=30.0) as c:
            if cls.device_id:
                delete_profile(c, cls.device_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # 4.1 ─────────────────────────────────────────────────────────────────────
    def test_01_create_profile_imsi(self, http: httpx.Client):
        """POST /profiles — imsi mode, iccid=null, 2 IMSIs with distinct IPs → 201."""
        body = create_profile_imsi(
            http,
            iccid=None,
            account_name="TestAccount",
            imsis=[
                {"imsi": IMSI1, "static_ip": IP1, "pool_id": TestProfileB.pool_id},
                {"imsi": IMSI2, "static_ip": IP2, "pool_id": TestProfileB.pool_id},
            ],
        )
        assert "device_id" in body
        TestProfileB.device_id = body["device_id"]

    # 4.2 ─────────────────────────────────────────────────────────────────────
    def test_02_lookup_imsi1(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI1&apn=internet → 200 with IP1."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI1, "apn": "internet.operator.com"})
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP1

    # 4.3 ─────────────────────────────────────────────────────────────────────
    def test_03_lookup_imsi1_different_apn(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI1&apn=ims → 200 with IP1 (APN ignored in imsi mode)."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI1, "apn": "ims.operator.com"})
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP1

    # 4.4 ─────────────────────────────────────────────────────────────────────
    def test_04_lookup_imsi2(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI2 → 200 with IP2 (distinct per-IMSI IP)."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI2, "apn": "internet.operator.com"})
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP2

    # 4.5 ─────────────────────────────────────────────────────────────────────
    def test_05_enrich_iccid(self, http: httpx.Client):
        """PATCH iccid → 200; GET confirms iccid populated."""
        r = http.patch(f"/profiles/{TestProfileB.device_id}", json={"iccid": ICCID})
        assert r.status_code == 200
        body = http.get(f"/profiles/{TestProfileB.device_id}").json()
        assert body["iccid"] == ICCID

    # 4.6 ─────────────────────────────────────────────────────────────────────
    def test_06_suspend_imsi1(self, http: httpx.Client):
        """PATCH /profiles/{device_id}/imsis/{imsi1} status=suspended → 200."""
        r = http.patch(f"/profiles/{TestProfileB.device_id}/imsis/{IMSI1}",
                       json={"status": "suspended"})
        assert r.status_code == 200

    # 4.7 ─────────────────────────────────────────────────────────────────────
    def test_07_lookup_suspended_imsi(self, lookup_http: httpx.Client):
        """GET /lookup for suspended IMSI1 → 403 {error: suspended}."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI1, "apn": "internet.operator.com"})
        assert r.status_code == 403
        assert r.json()["error"] == "suspended"

    # 4.8 ─────────────────────────────────────────────────────────────────────
    def test_08_lookup_imsi2_still_resolves(self, lookup_http: httpx.Client):
        """GET /lookup for IMSI2 → 200 while IMSI1 is suspended."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI2, "apn": "internet.operator.com"})
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP2

    # 4.9 ─────────────────────────────────────────────────────────────────────
    def test_09_update_imsi1_ip(self, http: httpx.Client, lookup_http: httpx.Client):
        """PATCH imsi1 static_ip → 200; subsequent GET /lookup returns new IP."""
        # Reactivate + change IP
        r = http.patch(f"/profiles/{TestProfileB.device_id}/imsis/{IMSI1}",
                       json={"status": "active", "static_ip": IP_NEW,
                             "pool_id": TestProfileB.pool_id})
        assert r.status_code == 200

        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI1, "apn": "internet.operator.com"})
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP_NEW
