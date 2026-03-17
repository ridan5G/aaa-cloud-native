"""
test_05_profiles_c.py — Profile C: ip_resolution = "imsi_apn"

Each IMSI has per-APN static IPs.
A wildcard entry (apn = null) acts as a catch-all fallback.

Test cases 5.1 – 5.9  (plan-01 §test_05_profiles_c)
"""
import threading

import httpx

from conftest import PROVISION_BASE, JWT_TOKEN
from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import create_profile_imsi_apn, delete_profile

IMSI1 = "278773050000001"
IMSI2 = "278773050000002"

POOL_SUBNET = "100.65.160.0/24"

IP_A = "100.65.160.1"    # IMSI1 → smf1
IP_B = "100.65.160.2"    # IMSI1 → smf2
IP_C = "100.65.160.3"    # IMSI2 → smf3
IP_D = "100.65.160.4"    # IMSI1 wildcard (added in 5.6)

APN_SMF1    = "smf1.operator.com"
APN_SMF2    = "smf2.operator.com"
APN_SMF3    = "smf3.operator.com"
APN_UNKNOWN = "smf9.unknown.com"


class TestProfileC:
    pool_id:   str | None = None
    sim_id: str | None = None

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet=POOL_SUBNET,
                            pool_name="pool-c-05", account_name="TestAccount")
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

    # 5.1 ─────────────────────────────────────────────────────────────────────
    def test_01_create_profile_imsi_apn(self, http: httpx.Client):
        """POST /profiles — imsi_apn mode; IMSI1 → [smf1→IP_A, smf2→IP_B]; IMSI2 → [smf3→IP_C] → 201."""
        body = create_profile_imsi_apn(
            http,
            iccid=None,
            account_name="TestAccount",
            imsis=[
                {
                    "imsi": IMSI1,
                    "apn_ips": [
                        {"apn": APN_SMF1, "static_ip": IP_A,
                         "pool_id": TestProfileC.pool_id},
                        {"apn": APN_SMF2, "static_ip": IP_B,
                         "pool_id": TestProfileC.pool_id},
                    ],
                },
                {
                    "imsi": IMSI2,
                    "apn_ips": [
                        {"apn": APN_SMF3, "static_ip": IP_C,
                         "pool_id": TestProfileC.pool_id},
                    ],
                },
            ],
        )
        assert "sim_id" in body
        TestProfileC.sim_id = body["sim_id"]

    # 5.2 ─────────────────────────────────────────────────────────────────────
    def test_02_lookup_imsi1_smf1(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI1&apn=smf1 → 200 with IP_A."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI1, "apn": APN_SMF1})
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP_A

    # 5.3 ─────────────────────────────────────────────────────────────────────
    def test_03_lookup_imsi1_smf2(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI1&apn=smf2 → 200 with IP_B."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI1, "apn": APN_SMF2})
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP_B

    # 5.4 ─────────────────────────────────────────────────────────────────────
    def test_04_lookup_imsi2_smf3(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI2&apn=smf3 → 200 with IP_C."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI2, "apn": APN_SMF3})
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP_C

    # 5.5 ─────────────────────────────────────────────────────────────────────
    def test_05_lookup_unknown_apn_no_wildcard(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI1&apn=smf9.unknown (no match, no wildcard) → 404 apn_not_found."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI1, "apn": APN_UNKNOWN})
        assert r.status_code == 404
        assert r.json()["error"] == "apn_not_found"

    # 5.6 ─────────────────────────────────────────────────────────────────────
    def test_06_add_wildcard_apn_entry(self, http: httpx.Client):
        """PATCH imsi1 — add {apn:null, static_ip:IP_D} wildcard entry → 200."""
        r = http.patch(
            f"/profiles/{TestProfileC.sim_id}/imsis/{IMSI1}",
            json={
                "apn_ips": [
                    {"apn": APN_SMF1, "static_ip": IP_A,
                     "pool_id": TestProfileC.pool_id},
                    {"apn": APN_SMF2, "static_ip": IP_B,
                     "pool_id": TestProfileC.pool_id},
                    {"apn": None,     "static_ip": IP_D,
                     "pool_id": TestProfileC.pool_id},
                ],
            },
        )
        assert r.status_code == 200

    # 5.7 ─────────────────────────────────────────────────────────────────────
    def test_07_unknown_apn_now_hits_wildcard(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI1&apn=smf9.unknown → 200 IP_D (wildcard fires)."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI1, "apn": APN_UNKNOWN})
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP_D

    # 5.8 ─────────────────────────────────────────────────────────────────────
    def test_08_exact_apn_wins_over_wildcard(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI1&apn=smf1 after wildcard added → 200 IP_A (exact wins)."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI1, "apn": APN_SMF1})
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP_A

    # 5.9 ─────────────────────────────────────────────────────────────────────
    def test_09_concurrent_lookups_same_imsi(self, lookup_http: httpx.Client):
        """Two concurrent GET /lookup for smf1 + smf2 (same IMSI) → both return correct IPs."""
        results: dict[str, tuple] = {}

        def fetch(apn: str) -> None:
            r = lookup_http.get("/lookup",
                                params={"imsi": IMSI1, "apn": apn})
            results[apn] = (r.status_code, r.json().get("static_ip"))

        t1 = threading.Thread(target=fetch, args=(APN_SMF1,))
        t2 = threading.Thread(target=fetch, args=(APN_SMF2,))
        t1.start(); t2.start()
        t1.join();  t2.join()

        assert results[APN_SMF1] == (200, IP_A), \
            f"smf1 expected (200, {IP_A}), got {results[APN_SMF1]}"
        assert results[APN_SMF2] == (200, IP_B), \
            f"smf2 expected (200, {IP_B}), got {results[APN_SMF2]}"
