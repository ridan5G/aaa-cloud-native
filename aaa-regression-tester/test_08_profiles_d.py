"""
test_08_profiles_d.py — Profile D: ip_resolution = "iccid_apn"

All IMSIs on a physical card share a set of card-level IPs, one per APN.
APN resolution order (Resolver::resolveIccidApn):
  1. Exact match  — row where sim_apn_ips.apn = request APN
  2. Wildcard     — row where sim_apn_ips.apn IS NULL
  3. apn_not_found — no match at all → 404

This file is the counterpart to:
  test_03_profiles_a.py  (iccid mode   — card IP, APN ignored)
  test_05_profiles_c.py  (imsi_apn mode — per-IMSI+APN IP)
filling the gap for iccid_apn as a statically provisioned profile.

Resources
─────────
  ICCID : 8944501080000000001  (make_iccid(8, 1))
  IMSI1 : 278770800000001      (make_imsi(8, 1))  — primary IMSI on the card
  IMSI2 : 278770800000002      (make_imsi(8, 2))  — secondary IMSI on the same card
  Pool  : pool-d-08  100.65.170.0/24
  IPs   : .1 = internet APN, .2 = ims APN, .3 = wildcard (added in test_07)

Scenario matrix
───────────────
  8.1  [good] Create profile
  8.2  [good] GET profile — iccid_ips contains both APN entries
  8.3  [good] Lookup IMSI1 exact internet APN → IP_INTERNET
  8.4  [good] Lookup IMSI1 exact ims APN → IP_IMS
  8.5  [good] Lookup IMSI2 (same card) → same card-level IPs
  8.6  [bad]  Lookup unknown APN, no wildcard → 404 apn_not_found
  8.7  [good] Add wildcard iccid_ip (apn=null)
  8.8  [good] Lookup unknown APN after wildcard → 200 IP_WILDCARD
  8.9  [good] Lookup registered APN after wildcard → exact match wins (IP_INTERNET)
  8.10 [bad]  Suspend SIM
  8.11 [bad]  Suspended SIM → 403 for ALL APN variants
  8.12 [good] Reactivate SIM → lookup resolves again
  8.13 [bad]  Suspend IMSI1 at IMSI level
  8.14 [bad]  Suspended IMSI1 → 403 for every APN
  8.15 [good] IMSI2 resolves card IPs while IMSI1 is suspended
  8.16 [good] Reactivate IMSI1 → lookup resolves again
  8.17 [bad]  Delete profile → terminated SIM lookup → 403 suspended
"""
import httpx

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID, make_imsi, make_iccid
from fixtures.pools import create_pool, delete_pool, _force_clear_range_profiles
from fixtures.profiles import create_profile_iccid_apn, delete_profile, cleanup_stale_profiles

MODULE = 8

# Two IMSIs on the same physical card
IMSI1 = make_imsi(MODULE, 1)    # "278770800000001"
IMSI2 = make_imsi(MODULE, 2)    # "278770800000002"
ICCID = make_iccid(MODULE, 1)   # "8944501080000000001"

POOL_SUBNET = "100.65.170.0/24"

APN_INTERNET = "internet.operator.com"
APN_IMS      = "ims.operator.com"
APN_UNKNOWN  = "unknown.apn.nowhere"

IP_INTERNET = "100.65.170.1"   # card-level IP for APN_INTERNET
IP_IMS      = "100.65.170.2"   # card-level IP for APN_IMS
IP_WILDCARD = "100.65.170.3"   # wildcard card-level IP (added in test_07)


class TestProfileD:
    """End-to-end tests for a statically provisioned iccid_apn profile.

    Physical setup: one card (ICCID), two IMSIs, two named APNs provisioned as
    card-level IPs in sim_apn_ips.  A wildcard entry (apn=NULL) is added midway
    through the sequence to exercise the fallback path.

    Tests run in order and share state via class variables (pool_id, sim_id).
    Suspend/reactivate tests deliberately leave the profile in a known state for
    the next test so each docstring documents the preconditions it relies on.
    """

    pool_id: str | None = None
    sim_id:  str | None = None

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            # API-level soft-delete of any active profiles from a previous run.
            cleanup_stale_profiles(c, f"27877{MODULE:02d}")

        # DB-level hard-delete for terminated profiles that still lock our ICCID.
        # cleanup_stale_profiles skips terminated profiles (status='terminated'),
        # but the ICCID uniqueness constraint applies even to them. This force-removes
        # the sim_profiles rows for our IMSI range so the ICCID can be reused.
        _force_clear_range_profiles(IMSI1, IMSI2)

        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet=POOL_SUBNET,
                            pool_name="pool-d-08", account_name="TestAccount",
                            replace_on_conflict=True)
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

    # 8.1 ─────────────────────────────────────────────────────────────────────
    def test_01_create_profile_iccid_apn(self, http: httpx.Client):
        """POST /profiles — iccid_apn mode, 2 IMSIs, 2 card-level APN IPs → 201."""
        body = create_profile_iccid_apn(
            http,
            iccid=ICCID,
            account_name="TestAccount",
            imsis=[IMSI1, IMSI2],
            apn_ips=[
                {"apn": APN_INTERNET, "static_ip": IP_INTERNET,
                 "pool_id": TestProfileD.pool_id},
                {"apn": APN_IMS,      "static_ip": IP_IMS,
                 "pool_id": TestProfileD.pool_id},
            ],
        )
        assert "sim_id" in body
        TestProfileD.sim_id = body["sim_id"]

    # 8.2 ─────────────────────────────────────────────────────────────────────
    def test_02_get_profile(self, http: httpx.Client):
        """GET /profiles/{sim_id} → 200; iccid_ips contains both APN entries."""
        resp = http.get(f"/profiles/{TestProfileD.sim_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["iccid"] == ICCID
        assert body["ip_resolution"] == "iccid_apn"
        iccid_ips = body.get("iccid_ips", [])
        apn_map = {e["apn"]: e["static_ip"] for e in iccid_ips if e.get("apn")}
        assert apn_map.get(APN_INTERNET) == IP_INTERNET, \
            f"Expected {IP_INTERNET} for {APN_INTERNET}, got iccid_ips={iccid_ips}"
        assert apn_map.get(APN_IMS) == IP_IMS, \
            f"Expected {IP_IMS} for {APN_IMS}, got iccid_ips={iccid_ips}"

    # 8.3 ─────────────────────────────────────────────────────────────────────
    def test_03_lookup_imsi1_internet_apn(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI1&apn=internet → 200 with IP_INTERNET."""
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI1, "apn": APN_INTERNET,
                                       "use_case_id": USE_CASE_ID})
        assert resp.status_code == 200
        assert resp.json()["static_ip"] == IP_INTERNET

    # 8.4 ─────────────────────────────────────────────────────────────────────
    def test_04_lookup_imsi1_ims_apn(self, lookup_http: httpx.Client):
        """GET /lookup?imsi=IMSI1&apn=ims → 200 with IP_IMS (different APN, same IMSI)."""
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI1, "apn": APN_IMS,
                                       "use_case_id": USE_CASE_ID})
        assert resp.status_code == 200
        assert resp.json()["static_ip"] == IP_IMS

    # 8.5 ─────────────────────────────────────────────────────────────────────
    def test_05_imsi2_shares_card_level_ips(self, lookup_http: httpx.Client):
        """IMSI2 (same physical card) resolves identical card-level IPs for all APNs."""
        for apn, expected_ip in [(APN_INTERNET, IP_INTERNET), (APN_IMS, IP_IMS)]:
            resp = lookup_http.get("/lookup",
                                   params={"imsi": IMSI2, "apn": apn,
                                           "use_case_id": USE_CASE_ID})
            assert resp.status_code == 200, \
                f"IMSI2 apn={apn}: expected 200, got {resp.status_code}: {resp.text}"
            assert resp.json()["static_ip"] == expected_ip, \
                f"IMSI2 apn={apn}: expected {expected_ip}, got {resp.json()['static_ip']}"

    # 8.6 — BAD scenario ──────────────────────────────────────────────────────
    def test_06_lookup_unknown_apn_no_wildcard(self, lookup_http: httpx.Client):
        """GET /lookup with APN not in card-level entries and no wildcard → 404 apn_not_found.

        The Resolver iterates sim_apn_ips rows; no exact match and no wildcard
        (iccid_apn IS NULL) row → ResolveStatus::ApnNotFound.
        """
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI1, "apn": APN_UNKNOWN,
                                       "use_case_id": USE_CASE_ID})
        assert resp.status_code == 404, \
            f"Expected 404 apn_not_found, got {resp.status_code}: {resp.text}"
        assert resp.json()["error"] == "apn_not_found"

    # 8.7 ─────────────────────────────────────────────────────────────────────
    def test_07_add_wildcard_iccid_ip(self, http: httpx.Client):
        """PATCH — add wildcard entry (apn=null) to iccid_ips → 200.

        The full iccid_ips list is sent (replacing existing entries).
        """
        resp = http.patch(
            f"/profiles/{TestProfileD.sim_id}",
            json={
                "iccid_ips": [
                    {"apn": APN_INTERNET, "static_ip": IP_INTERNET,
                     "pool_id": TestProfileD.pool_id, "pool_name": "pool-d-08"},
                    {"apn": APN_IMS,      "static_ip": IP_IMS,
                     "pool_id": TestProfileD.pool_id, "pool_name": "pool-d-08"},
                    {"apn": None,         "static_ip": IP_WILDCARD,
                     "pool_id": TestProfileD.pool_id, "pool_name": "pool-d-08"},
                ],
            },
        )
        assert resp.status_code == 200, \
            f"Expected 200 on wildcard add, got {resp.status_code}: {resp.text}"

    # 8.8 ─────────────────────────────────────────────────────────────────────
    def test_08_unknown_apn_now_hits_wildcard(self, lookup_http: httpx.Client):
        """GET /lookup with unknown APN after wildcard added → 200 IP_WILDCARD.

        Resolver precedence: exact match → wildcard (apn IS NULL) → apn_not_found.
        """
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI1, "apn": APN_UNKNOWN,
                                       "use_case_id": USE_CASE_ID})
        assert resp.status_code == 200, \
            f"Expected 200 (wildcard), got {resp.status_code}: {resp.text}"
        assert resp.json()["static_ip"] == IP_WILDCARD

    # 8.9 ─────────────────────────────────────────────────────────────────────
    def test_09_exact_apn_wins_over_wildcard(self, lookup_http: httpx.Client):
        """GET /lookup with registered APN after wildcard added → 200 IP_INTERNET (exact wins).

        Resolver returns on first exact match — wildcard candidate is never promoted.
        """
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI1, "apn": APN_INTERNET,
                                       "use_case_id": USE_CASE_ID})
        assert resp.status_code == 200
        assert resp.json()["static_ip"] == IP_INTERNET, \
            f"Exact APN match must beat wildcard: expected {IP_INTERNET}, got {resp.json()['static_ip']}"

    # 8.10 — BAD scenario ─────────────────────────────────────────────────────
    def test_10_suspend_sim(self, http: httpx.Client):
        """PATCH status=suspended → 200."""
        resp = http.patch(f"/profiles/{TestProfileD.sim_id}",
                          json={"status": "suspended"})
        assert resp.status_code == 200

    # 8.11 — BAD scenario ─────────────────────────────────────────────────────
    def test_11_lookup_suspended_sim_all_apns(self, lookup_http: httpx.Client):
        """Suspended SIM → 403 {error: suspended} for ALL APN variants (internet, ims, unknown).

        sim_status='suspended' → Resolver returns Suspended regardless of APN mode.
        """
        for apn in (APN_INTERNET, APN_IMS, APN_UNKNOWN):
            resp = lookup_http.get("/lookup",
                                   params={"imsi": IMSI1, "apn": apn,
                                           "use_case_id": USE_CASE_ID})
            assert resp.status_code == 403, \
                f"apn={apn}: expected 403 for suspended SIM, got {resp.status_code}"
            assert resp.json()["error"] == "suspended"

    # 8.12 ────────────────────────────────────────────────────────────────────
    def test_12_reactivate_and_lookup(self, http: httpx.Client, lookup_http: httpx.Client):
        """PATCH status=active → 200; subsequent GET /lookup resolves again."""
        resp = http.patch(f"/profiles/{TestProfileD.sim_id}",
                          json={"status": "active"})
        assert resp.status_code == 200
        resp = lookup_http.get("/lookup",
                               params={"imsi": IMSI1, "apn": APN_INTERNET,
                                       "use_case_id": USE_CASE_ID})
        assert resp.status_code == 200
        assert resp.json()["static_ip"] == IP_INTERNET

    # 8.13 — BAD scenario ─────────────────────────────────────────────────────
    def test_13_suspend_individual_imsi1(self, http: httpx.Client):
        """PATCH /profiles/{sim_id}/imsis/{IMSI1} status=suspended → 200.

        Per-IMSI suspend: only IMSI1 is blocked; IMSI2 (same card) stays active.
        """
        resp = http.patch(f"/profiles/{TestProfileD.sim_id}/imsis/{IMSI1}",
                          json={"status": "suspended"})
        assert resp.status_code == 200

    # 8.14 — BAD scenario ─────────────────────────────────────────────────────
    def test_14_lookup_suspended_imsi1_all_apns(self, lookup_http: httpx.Client):
        """IMSI1 (suspended at IMSI level) → 403 for every APN while SIM is active."""
        for apn in (APN_INTERNET, APN_IMS, APN_UNKNOWN):
            resp = lookup_http.get("/lookup",
                                   params={"imsi": IMSI1, "apn": apn,
                                           "use_case_id": USE_CASE_ID})
            assert resp.status_code == 403, \
                f"apn={apn}: expected 403 for suspended IMSI1, got {resp.status_code}"
            assert resp.json()["error"] == "suspended"

    # 8.15 ────────────────────────────────────────────────────────────────────
    def test_15_imsi2_resolves_while_imsi1_suspended(self, lookup_http: httpx.Client):
        """IMSI2 (same card, distinct IMSI) still resolves shared card IPs while IMSI1 suspended.

        imsi_status is per-IMSI; the card-level IPs are shared but each IMSI row
        has its own status in imsi2sim.
        """
        for apn, expected_ip in [(APN_INTERNET, IP_INTERNET), (APN_IMS, IP_IMS)]:
            resp = lookup_http.get("/lookup",
                                   params={"imsi": IMSI2, "apn": apn,
                                           "use_case_id": USE_CASE_ID})
            assert resp.status_code == 200, \
                f"IMSI2 apn={apn}: expected 200, got {resp.status_code}: {resp.text}"
            assert resp.json()["static_ip"] == expected_ip

    # 8.16 ────────────────────────────────────────────────────────────────────
    def test_16_reactivate_imsi1_lookup_resolves(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """Reactivate IMSI1 → lookup resolves again for all APNs."""
        resp = http.patch(f"/profiles/{TestProfileD.sim_id}/imsis/{IMSI1}",
                          json={"status": "active"})
        assert resp.status_code == 200

        for apn, expected_ip in [(APN_INTERNET, IP_INTERNET), (APN_IMS, IP_IMS)]:
            resp = lookup_http.get("/lookup",
                                   params={"imsi": IMSI1, "apn": apn,
                                           "use_case_id": USE_CASE_ID})
            assert resp.status_code == 200, \
                f"IMSI1 apn={apn}: expected 200 after reactivation, got {resp.status_code}"
            assert resp.json()["static_ip"] == expected_ip

    # 8.17 ────────────────────────────────────────────────────────────────────
    def test_17_delete_profile_lookup_returns_suspended(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """DELETE → 204; terminated SIM lookup returns 403 {error: suspended}.

        Soft-delete sets sim_profiles.status = 'terminated' but keeps IMSI rows.
        The Resolver checks sim_status != 'active' → returns Suspended (403).
        A 404 (not_found) is also accepted if the implementation removes IMSI rows.
        """
        resp = http.delete(f"/profiles/{TestProfileD.sim_id}")
        assert resp.status_code == 204

        resp_lookup = lookup_http.get("/lookup",
                                      params={"imsi": IMSI1, "apn": APN_INTERNET,
                                              "use_case_id": USE_CASE_ID})
        assert resp_lookup.status_code in (403, 404), (
            f"Expected 403 (terminated≠active) or 404 (IMSI removed), "
            f"got {resp_lookup.status_code}: {resp_lookup.text}"
        )
        if resp_lookup.status_code == 403:
            assert resp_lookup.json()["error"] == "suspended"
        TestProfileD.sim_id = None
