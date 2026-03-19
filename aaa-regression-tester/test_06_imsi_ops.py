"""
test_06_imsi_ops.py — IMSI-level operations: add, remove, conflict detection.

Test cases 6.1 – 6.8  (plan-01 §test_06_imsi_ops)
"""
import httpx

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID
from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import create_profile_imsi, delete_profile

# Module 06 — prefix 278773 + 06 + sequence
IMSI1        = "278773060000001"
IMSI2        = "278773060000002"
NEW_IMSI     = "278773060000003"   # added in 6.2
CONFLICT_IMSI = "278773060000004"  # on sim_id2 — used to test 409 in 6.7

POOL_SUBNET = "100.65.170.0/24"

IP1     = "100.65.170.1"
IP2     = "100.65.170.2"
NEW_IP  = "100.65.170.10"
CONF_IP = "100.65.170.20"


class TestImsiOps:
    pool_id:    str | None = None
    sim_id:  str | None = None   # primary profile (IMSI1 + IMSI2)
    sim_id2: str | None = None   # secondary profile (CONFLICT_IMSI only)

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet=POOL_SUBNET,
                            pool_name="pool-ops-06", account_name="TestAccount")
            cls.pool_id = p["pool_id"]

            # Primary profile — imsi mode, 2 IMSIs
            body = create_profile_imsi(
                c, iccid=None, account_name="TestAccount",
                imsis=[
                    {"imsi": IMSI1, "static_ip": IP1, "pool_id": cls.pool_id},
                    {"imsi": IMSI2, "static_ip": IP2, "pool_id": cls.pool_id},
                ],
            )
            cls.sim_id = body["sim_id"]

            # Secondary profile — holds CONFLICT_IMSI (used for 6.7 conflict test)
            body2 = create_profile_imsi(
                c, iccid=None, account_name="TestAccount",
                imsis=[
                    {"imsi": CONFLICT_IMSI, "static_ip": CONF_IP,
                     "pool_id": cls.pool_id},
                ],
            )
            cls.sim_id2 = body2["sim_id"]

    @classmethod
    def teardown_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            if cls.sim_id2:
                delete_profile(c, cls.sim_id2)
            if cls.sim_id:
                delete_profile(c, cls.sim_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # 6.1 ─────────────────────────────────────────────────────────────────────
    def test_01_list_imsis(self, http: httpx.Client):
        """GET /profiles/{sim_id}/imsis → 200, list contains IMSI1 and IMSI2."""
        r = http.get(f"/profiles/{TestImsiOps.sim_id}/imsis")
        assert r.status_code == 200
        data = r.json()
        imsi_values = [entry["imsi"] for entry in data] \
            if isinstance(data, list) \
            else [entry["imsi"] for entry in data.get("imsis", [])]
        assert IMSI1 in imsi_values, f"IMSI1 not found in {imsi_values}"
        assert IMSI2 in imsi_values, f"IMSI2 not found in {imsi_values}"

    # 6.2 ─────────────────────────────────────────────────────────────────────
    def test_02_add_new_imsi(self, http: httpx.Client):
        """POST /profiles/{sim_id}/imsis — add NEW_IMSI with apn_ips → 201."""
        r = http.post(
            f"/profiles/{TestImsiOps.sim_id}/imsis",
            json={
                "imsi": NEW_IMSI,
                "apn_ips": [
                    {
                        "static_ip": NEW_IP,
                        "pool_id":   TestImsiOps.pool_id,
                    },
                ],
            },
        )
        assert r.status_code == 201, \
            f"Expected 201, got {r.status_code}: {r.text}"

    # 6.3 ─────────────────────────────────────────────────────────────────────
    def test_03_lookup_new_imsi_resolves(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=NEW_IMSI&apn=... → 200 with NEW_IP."""
        r = lookup_http.get("/lookup",
                            params={"imsi": NEW_IMSI, "apn": "internet.operator.com",
                                    "use_case_id": USE_CASE_ID})
        assert r.status_code == 200
        assert r.json()["static_ip"] == NEW_IP

    # 6.4 ─────────────────────────────────────────────────────────────────────
    def test_04_get_new_imsi_detail(self, http: httpx.Client):
        """GET /profiles/{sim_id}/imsis/{new_imsi} → 200, apn_ips contain NEW_IP."""
        r = http.get(f"/profiles/{TestImsiOps.sim_id}/imsis/{NEW_IMSI}")
        assert r.status_code == 200
        body = r.json()
        assert body["imsi"] == NEW_IMSI
        ips = [entry["static_ip"] for entry in body.get("apn_ips", [])]
        assert NEW_IP in ips, f"NEW_IP not found in apn_ips: {ips}"

    # 6.5 ─────────────────────────────────────────────────────────────────────
    def test_05_delete_new_imsi(self, http: httpx.Client):
        """DELETE /profiles/{sim_id}/imsis/{new_imsi} → 204."""
        r = http.delete(f"/profiles/{TestImsiOps.sim_id}/imsis/{NEW_IMSI}")
        assert r.status_code == 204, \
            f"Expected 204, got {r.status_code}: {r.text}"

    # 6.6 ─────────────────────────────────────────────────────────────────────
    def test_06_lookup_deleted_imsi_returns_404(self, lookup_http: httpx.Client):
        """GET /lookup for a deleted IMSI → 404."""
        r = lookup_http.get("/lookup",
                            params={"imsi": NEW_IMSI, "apn": "internet.operator.com",
                                    "use_case_id": USE_CASE_ID})
        assert r.status_code == 404

    # 6.7 ─────────────────────────────────────────────────────────────────────
    def test_07_add_conflicting_imsi_returns_409(self, http: httpx.Client):
        """POST /profiles/{sim_id}/imsis with IMSI already on another device → 409 imsi_conflict."""
        r = http.post(
            f"/profiles/{TestImsiOps.sim_id}/imsis",
            json={
                "imsi": CONFLICT_IMSI,     # already belongs to sim_id2
                "apn_ips": [
                    {"static_ip": "100.65.170.99",
                     "pool_id":   TestImsiOps.pool_id},
                ],
            },
        )
        assert r.status_code == 409, \
            f"Expected 409 (imsi_conflict), got {r.status_code}: {r.text}"
        assert r.json().get("error") in ("imsi_conflict", "conflict"), \
            f"Unexpected error body: {r.json()}"

    # 6.8 ─────────────────────────────────────────────────────────────────────
    def test_08_delete_last_imsi(self, http: httpx.Client):
        """DELETE last IMSI on a profile — 400 (must have ≥1) or 204 (allowed).

        The test documents whichever behaviour the API implements; either is
        acceptable.  A 400 with a clear error message is the recommended
        safeguard; 204 means the profile becomes IMSI-less (orphan).
        """
        # sim_id2 was created with only CONFLICT_IMSI.
        # After test 6.7 failed (409), sim_id2 still has exactly 1 IMSI.
        r = http.delete(
            f"/profiles/{TestImsiOps.sim_id2}/imsis/{CONFLICT_IMSI}"
        )
        assert r.status_code in (204, 400), (
            f"Expected 204 (allowed) or 400 (forbidden for last IMSI), "
            f"got {r.status_code}: {r.text}"
        )
