"""
test_16_lookup_fast_path.py — Fast-path validation gaps and cross-mode suspend behaviour.

Covers scenarios not addressed by existing profile-type tests or test_10_errors.
Three independent test classes; each creates only what it needs.

Gap analysis vs existing suite
────────────────────────────────
  test_10_errors  — covers missing IMSI/APN params in GET /lookup but NOT
                    malformed IMSI format (wrong length, non-digit chars).
  test_04_imsi_profile — tests per-IMSI suspend in imsi mode but NOT SIM-level
                         suspend (PATCH /profiles/{id} status=suspended).
  test_05_imsi_apn_profile — zero suspend coverage for imsi_apn mode.

Resources
─────────
  Module   : 16  → IMSI prefix 27877 16 xxxxxxxx  (no conflict with other modules)
  imsi mode pool : pool-fp16-imsi  100.65.180.0/24
    IMSI_IMSI_A  278771600000001  → IP_A 100.65.180.1
    IMSI_IMSI_B  278771600000002  → IP_B 100.65.180.2
  imsi_apn pool  : pool-fp16-iapn  100.65.181.0/24
    IMSI_IAPN_A  278771600000011  → internet IP_C 100.65.181.1, ims IP_D 100.65.181.2
    IMSI_IAPN_B  278771600000012  → internet IP_E 100.65.181.3, ims IP_F 100.65.181.4

Scenario matrix
───────────────
  TestLookupParamValidation  (no DB fixture required)
    16.1  [bad]  IMSI 14 digits → 400
    16.2  [bad]  IMSI 16 digits → 400
    16.3  [bad]  IMSI with non-digit chars → 400
    16.4  [bad]  Empty IMSI string → 400
    16.5  [bad]  Valid IMSI never registered → 404 not_found

  TestSimSuspendImsiMode
    16.6  [good] Both IMSIs resolve when SIM active
    16.7  [bad]  SIM-level suspend blocks ALL IMSIs → 403
    16.8  [good] Reactivate SIM restores both IMSIs

  TestSimSuspendImsiApnMode
    16.9  [good] All IMSI+APN combos resolve when SIM active
    16.10 [bad]  SIM-level suspend blocks all IMSI+APN combos → 403
    16.11 [good] Reactivate SIM restores all IMSI+APN combos
    16.12 [bad]  Per-IMSI suspend: IMSI_A 403 for all APNs; sibling IMSI_B unaffected
    16.13 [good] Concurrent lookups for IMSI_B's two APNs return correct IPs

Setup idempotency
─────────────────
  Each profile-creating setup_class calls cleanup_stale_profiles() (soft-delete
  active profiles) then _force_clear_range_profiles() (hard-delete terminated
  profiles via DB) before creating the pool and profile.  This ensures the test
  is safe to re-run even if a previous run was interrupted mid-teardown.
"""
import threading

import httpx

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID, make_imsi
from fixtures.pools import create_pool, delete_pool, _force_clear_range_profiles
from fixtures.profiles import (
    create_profile_imsi,
    create_profile_imsi_apn,
    delete_profile,
    cleanup_stale_profiles,
)

MODULE = 16

APN_INTERNET = "internet.operator.com"
APN_IMS      = "ims.operator.com"

# ── imsi-mode suspend test IMSIs ───────────────────────────────────────────
IMSI_IMSI_A = make_imsi(MODULE, 1)   # "278771600000001"
IMSI_IMSI_B = make_imsi(MODULE, 2)   # "278771600000002"
IP_A = "100.65.180.1"
IP_B = "100.65.180.2"

# ── imsi_apn-mode suspend test IMSIs ──────────────────────────────────────
IMSI_IAPN_A = make_imsi(MODULE, 11)  # "278771600000011"
IMSI_IAPN_B = make_imsi(MODULE, 12)  # "278771600000012"
IP_C = "100.65.181.1"   # IMSI_IAPN_A → APN_INTERNET
IP_D = "100.65.181.2"   # IMSI_IAPN_A → APN_IMS
IP_E = "100.65.181.3"   # IMSI_IAPN_B → APN_INTERNET
IP_F = "100.65.181.4"   # IMSI_IAPN_B → APN_IMS


# ══════════════════════════════════════════════════════════════════════════════
# Parameter validation — no profile required
# ══════════════════════════════════════════════════════════════════════════════

class TestLookupParamValidation:
    """GET /lookup — malformed IMSI input rejected before DB access."""

    # 16.1 ────────────────────────────────────────────────────────────────────
    def test_01_imsi_14_digits(self, lookup_http: httpx.Client):
        """IMSI with 14 digits → 400.

        isValidImsi() in LookupController requires exactly 15 digits.
        """
        r = lookup_http.get("/lookup",
                            params={"imsi": "27877160000001",   # 14 digits
                                    "apn": APN_INTERNET})
        assert r.status_code == 400, \
            f"Expected 400 for 14-digit IMSI, got {r.status_code}: {r.text}"

    # 16.2 ────────────────────────────────────────────────────────────────────
    def test_02_imsi_16_digits(self, lookup_http: httpx.Client):
        """IMSI with 16 digits → 400.

        isValidImsi() checks size == 15 before the DB is ever touched.
        """
        r = lookup_http.get("/lookup",
                            params={"imsi": "2787716000000001",  # 16 digits
                                    "apn": APN_INTERNET})
        assert r.status_code == 400, \
            f"Expected 400 for 16-digit IMSI, got {r.status_code}: {r.text}"

    # 16.3 ────────────────────────────────────────────────────────────────────
    def test_03_imsi_with_non_digit_chars(self, lookup_http: httpx.Client):
        """IMSI containing letters → 400.

        isValidImsi() rejects any character outside '0'–'9'.
        """
        r = lookup_http.get("/lookup",
                            params={"imsi": "2787716ABCDE001",  # 15 chars, letters
                                    "apn": APN_INTERNET})
        assert r.status_code == 400, \
            f"Expected 400 for non-digit IMSI, got {r.status_code}: {r.text}"

    # 16.4 ────────────────────────────────────────────────────────────────────
    def test_04_empty_imsi(self, lookup_http: httpx.Client):
        """Empty IMSI string → 400.

        An empty string has length 0, which fails the size == 15 check in
        isValidImsi().  Ensures the controller treats an empty query param the
        same as a missing one rather than passing it to the DB.
        """
        r = lookup_http.get("/lookup",
                            params={"imsi": "", "apn": APN_INTERNET})
        assert r.status_code == 400, \
            f"Expected 400 for empty IMSI, got {r.status_code}: {r.text}"

    # 16.5 ────────────────────────────────────────────────────────────────────
    def test_05_unknown_imsi_returns_not_found(self, lookup_http: httpx.Client):
        """Valid 15-digit IMSI never registered → 404 {error: not_found}.

        The hot-path SQL returns no rows → Resolver returns NotFound.
        In production the RADIUS server would then call POST /first-connection,
        but a direct lookup call always returns 404 for an unknown IMSI.
        """
        r = lookup_http.get("/lookup",
                            params={"imsi": make_imsi(MODULE, 99999),  # never registered
                                    "apn": APN_INTERNET,
                                    "use_case_id": USE_CASE_ID})
        assert r.status_code == 404, \
            f"Expected 404 for unknown IMSI, got {r.status_code}: {r.text}"
        assert r.json()["error"] == "not_found"


# ══════════════════════════════════════════════════════════════════════════════
# SIM-level suspend in imsi mode
# (test_04 only covers per-IMSI suspend — SIM-level is untested)
# ══════════════════════════════════════════════════════════════════════════════

class TestSimSuspendImsiMode:
    """SIM-level suspend in imsi mode blocks ALL IMSIs on the profile."""

    pool_id: str | None = None
    sim_id:  str | None = None

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            cleanup_stale_profiles(c, f"27877{MODULE:02d}")
        _force_clear_range_profiles(IMSI_IMSI_A, IMSI_IMSI_B)
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet="100.65.180.0/24",
                            pool_name="pool-fp16-imsi", account_name="TestAccount",
                            replace_on_conflict=True)
            cls.pool_id = p["pool_id"]
            b = create_profile_imsi(
                c,
                iccid=None,
                account_name="TestAccount",
                imsis=[
                    {"imsi": IMSI_IMSI_A, "static_ip": IP_A, "pool_id": cls.pool_id},
                    {"imsi": IMSI_IMSI_B, "static_ip": IP_B, "pool_id": cls.pool_id},
                ],
            )
            cls.sim_id = b["sim_id"]

    @classmethod
    def teardown_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            if cls.sim_id:
                delete_profile(c, cls.sim_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # 16.6 ────────────────────────────────────────────────────────────────────
    def test_06_both_imsis_resolve_when_active(self, lookup_http: httpx.Client):
        """Baseline: both IMSIs return their correct per-IMSI IPs when SIM is active.

        Establishes a known-good state before the suspend tests.
        """
        for imsi, ip in [(IMSI_IMSI_A, IP_A), (IMSI_IMSI_B, IP_B)]:
            r = lookup_http.get("/lookup",
                                params={"imsi": imsi, "apn": APN_INTERNET,
                                        "use_case_id": USE_CASE_ID})
            assert r.status_code == 200, \
                f"imsi={imsi}: expected 200, got {r.status_code}: {r.text}"
            assert r.json()["static_ip"] == ip

    # 16.7 — BAD scenario ─────────────────────────────────────────────────────
    def test_07_sim_level_suspend_blocks_all_imsis(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """PATCH SIM status=suspended → BOTH IMSI_A and IMSI_B return 403.

        SIM-level suspend sets sim_profiles.status = 'suspended'.
        Resolver checks sim_status first → Suspended (403) regardless of imsi_status.
        """
        r = http.patch(f"/profiles/{TestSimSuspendImsiMode.sim_id}",
                       json={"status": "suspended"})
        assert r.status_code == 200

        for imsi in (IMSI_IMSI_A, IMSI_IMSI_B):
            r_lkp = lookup_http.get("/lookup",
                                    params={"imsi": imsi, "apn": APN_INTERNET,
                                            "use_case_id": USE_CASE_ID})
            assert r_lkp.status_code == 403, \
                f"imsi={imsi}: expected 403 (SIM suspended), got {r_lkp.status_code}"
            assert r_lkp.json()["error"] == "suspended"

    # 16.8 ────────────────────────────────────────────────────────────────────
    def test_08_reactivate_sim_restores_both_imsis(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """PATCH SIM status=active → both IMSIs resolve again with original IPs.

        Verifies the suspend/reactivate cycle is fully reversible — IPs are
        unchanged and both IMSIs are unblocked immediately.
        """
        r = http.patch(f"/profiles/{TestSimSuspendImsiMode.sim_id}",
                       json={"status": "active"})
        assert r.status_code == 200

        for imsi, ip in [(IMSI_IMSI_A, IP_A), (IMSI_IMSI_B, IP_B)]:
            r_lkp = lookup_http.get("/lookup",
                                    params={"imsi": imsi, "apn": APN_INTERNET,
                                            "use_case_id": USE_CASE_ID})
            assert r_lkp.status_code == 200, \
                f"imsi={imsi}: expected 200 after reactivation, got {r_lkp.status_code}"
            assert r_lkp.json()["static_ip"] == ip


# ══════════════════════════════════════════════════════════════════════════════
# SIM-level and per-IMSI suspend in imsi_apn mode
# (test_05 has zero suspend tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestSimSuspendImsiApnMode:
    """SIM-level vs per-IMSI suspend in imsi_apn mode."""

    pool_id: str | None = None
    sim_id:  str | None = None

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            cleanup_stale_profiles(c, f"27877{MODULE:02d}")
        _force_clear_range_profiles(IMSI_IAPN_A, IMSI_IAPN_B)
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet="100.65.181.0/24",
                            pool_name="pool-fp16-iapn", account_name="TestAccount",
                            replace_on_conflict=True)
            cls.pool_id = p["pool_id"]
            b = create_profile_imsi_apn(
                c,
                iccid=None,
                account_name="TestAccount",
                imsis=[
                    {
                        "imsi": IMSI_IAPN_A,
                        "apn_ips": [
                            {"apn": APN_INTERNET, "static_ip": IP_C, "pool_id": cls.pool_id},
                            {"apn": APN_IMS,      "static_ip": IP_D, "pool_id": cls.pool_id},
                        ],
                    },
                    {
                        "imsi": IMSI_IAPN_B,
                        "apn_ips": [
                            {"apn": APN_INTERNET, "static_ip": IP_E, "pool_id": cls.pool_id},
                            {"apn": APN_IMS,      "static_ip": IP_F, "pool_id": cls.pool_id},
                        ],
                    },
                ],
            )
            cls.sim_id = b["sim_id"]

    @classmethod
    def teardown_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            if cls.sim_id:
                delete_profile(c, cls.sim_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # 16.9 ────────────────────────────────────────────────────────────────────
    def test_09_all_apns_resolve_when_active(self, lookup_http: httpx.Client):
        """Baseline: all four IMSI+APN combinations return correct IPs when SIM is active.

        Both IMSIs × both APNs verified before any suspend is applied.
        """
        cases = [
            (IMSI_IAPN_A, APN_INTERNET, IP_C),
            (IMSI_IAPN_A, APN_IMS,      IP_D),
            (IMSI_IAPN_B, APN_INTERNET, IP_E),
            (IMSI_IAPN_B, APN_IMS,      IP_F),
        ]
        for imsi, apn, expected_ip in cases:
            r = lookup_http.get("/lookup",
                                params={"imsi": imsi, "apn": apn,
                                        "use_case_id": USE_CASE_ID})
            assert r.status_code == 200, \
                f"imsi={imsi} apn={apn}: expected 200, got {r.status_code}: {r.text}"
            assert r.json()["static_ip"] == expected_ip

    # 16.10 — BAD scenario ────────────────────────────────────────────────────
    def test_10_sim_level_suspend_blocks_all_apns(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """PATCH SIM status=suspended → ALL IMSI+APN combinations return 403.

        SIM-level suspend in imsi_apn mode must block every APN of every IMSI.
        """
        r = http.patch(f"/profiles/{TestSimSuspendImsiApnMode.sim_id}",
                       json={"status": "suspended"})
        assert r.status_code == 200

        for imsi, apn in [
            (IMSI_IAPN_A, APN_INTERNET),
            (IMSI_IAPN_A, APN_IMS),
            (IMSI_IAPN_B, APN_INTERNET),
            (IMSI_IAPN_B, APN_IMS),
        ]:
            r_lkp = lookup_http.get("/lookup",
                                    params={"imsi": imsi, "apn": apn,
                                            "use_case_id": USE_CASE_ID})
            assert r_lkp.status_code == 403, \
                f"imsi={imsi} apn={apn}: expected 403, got {r_lkp.status_code}"
            assert r_lkp.json()["error"] == "suspended"

    # 16.11 ───────────────────────────────────────────────────────────────────
    def test_11_reactivate_sim_restores_all_apns(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """PATCH SIM status=active → all IMSI+APN combinations resolve again.

        Verifies full recovery: all four IMSI+APN combos return original IPs,
        no partial unblock (e.g. only the first IMSI or first APN restored).
        """
        r = http.patch(f"/profiles/{TestSimSuspendImsiApnMode.sim_id}",
                       json={"status": "active"})
        assert r.status_code == 200

        cases = [
            (IMSI_IAPN_A, APN_INTERNET, IP_C),
            (IMSI_IAPN_A, APN_IMS,      IP_D),
            (IMSI_IAPN_B, APN_INTERNET, IP_E),
            (IMSI_IAPN_B, APN_IMS,      IP_F),
        ]
        for imsi, apn, expected_ip in cases:
            r_lkp = lookup_http.get("/lookup",
                                    params={"imsi": imsi, "apn": apn,
                                            "use_case_id": USE_CASE_ID})
            assert r_lkp.status_code == 200, \
                f"imsi={imsi} apn={apn}: expected 200 after reactivation, got {r_lkp.status_code}"
            assert r_lkp.json()["static_ip"] == expected_ip

    # 16.12 — BAD scenario ────────────────────────────────────────────────────
    def test_12_per_imsi_suspend_in_imsi_apn_mode(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """Per-IMSI suspend: IMSI_A blocked for ALL its APNs; sibling IMSI_B unaffected.

        imsi_status is checked per-IMSI (Resolver: sim_status OR imsi_status != 'active').
        SIM status is active; only IMSI_A's row in imsi2sim is suspended.
        """
        r = http.patch(
            f"/profiles/{TestSimSuspendImsiApnMode.sim_id}/imsis/{IMSI_IAPN_A}",
            json={"status": "suspended"},
        )
        assert r.status_code == 200

        # IMSI_A must be blocked for every APN
        for apn in (APN_INTERNET, APN_IMS):
            r_a = lookup_http.get("/lookup",
                                  params={"imsi": IMSI_IAPN_A, "apn": apn,
                                          "use_case_id": USE_CASE_ID})
            assert r_a.status_code == 403, \
                f"IMSI_A apn={apn}: expected 403 (IMSI suspended), got {r_a.status_code}"
            assert r_a.json()["error"] == "suspended"

        # IMSI_B must still resolve correctly
        for apn, expected_ip in [(APN_INTERNET, IP_E), (APN_IMS, IP_F)]:
            r_b = lookup_http.get("/lookup",
                                  params={"imsi": IMSI_IAPN_B, "apn": apn,
                                          "use_case_id": USE_CASE_ID})
            assert r_b.status_code == 200, \
                f"IMSI_B apn={apn}: expected 200 (still active), got {r_b.status_code}"
            assert r_b.json()["static_ip"] == expected_ip

    # 16.13 ───────────────────────────────────────────────────────────────────
    def test_13_concurrent_lookups_active_imsi(self, lookup_http: httpx.Client):
        """Concurrent lookups for IMSI_B's two APNs return correct IPs simultaneously.

        IMSI_A is still suspended from test_12; IMSI_B is active.
        Tests that the hot-path SQL and Resolver handle concurrent queries without
        cross-contaminating results.
        """
        results: dict = {}

        def fetch(imsi: str, apn: str) -> None:
            r = lookup_http.get("/lookup",
                                params={"imsi": imsi, "apn": apn,
                                        "use_case_id": USE_CASE_ID})
            results[(imsi, apn)] = (r.status_code, r.json().get("static_ip"))

        t1 = threading.Thread(target=fetch, args=(IMSI_IAPN_B, APN_INTERNET))
        t2 = threading.Thread(target=fetch, args=(IMSI_IAPN_B, APN_IMS))
        t1.start(); t2.start()
        t1.join();  t2.join()

        assert results[(IMSI_IAPN_B, APN_INTERNET)] == (200, IP_E), \
            f"Expected (200, {IP_E}), got {results[(IMSI_IAPN_B, APN_INTERNET)]}"
        assert results[(IMSI_IAPN_B, APN_IMS)] == (200, IP_F), \
            f"Expected (200, {IP_F}), got {results[(IMSI_IAPN_B, APN_IMS)]}"
