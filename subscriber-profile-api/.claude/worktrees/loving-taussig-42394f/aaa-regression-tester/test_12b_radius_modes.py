"""
test_12b_radius_modes.py — RADIUS end-to-end coverage for all 4 ip_resolution modes.

Extends test_12_radius.py, which only exercises the imsi mode.
Every test sends real RADIUS UDP Access-Request packets to aaa-radius-server
and inspects the Access-Accept / Access-Reject response.

Gap filled vs test_12
─────────────────────
  iccid mode     — card-level IP returned regardless of APN (Called-Station-Id ignored)
  imsi_apn mode  — per-IMSI APN routing; wrong APN → Access-Reject (apn_not_found)
  iccid_apn mode — card-level APN routing; wrong APN → Access-Reject
  Per-IMSI suspend → Access-Reject while sibling IMSI on same card → Access-Accept
  First-connection for imsi_apn mode via RADIUS (APN catalog pre-allocation)
  Second-APN idempotency after imsi_apn first-connection

Production path exercised
──────────────────────────
  UE → RADIUS UDP → aaa-radius-server → GET /lookup → aaa-lookup-service → read replica
                                      → (on 404) POST /first-connection → subscriber-profile-api → primary
                                      → Access-Accept / Access-Reject

Resources (module = 17, IMSI prefix 2787717)
────────────────────────────────────────────
  iccid mode      pool-r12b-iccid     100.65.121.0/29    card IP = .1
    IMSI_ICCID_A  278771700000001  primary IMSI on card
    IMSI_ICCID_B  278771700000002  secondary IMSI — shares same card-level IP

  imsi_apn mode   pool-r12b-iapn-int  100.65.121.8/29   IP_IAPN_INT = .9
                  pool-r12b-iapn-ims  100.65.121.16/29  IP_IAPN_IMS = .17
    IMSI_IAPN     278771700000011

  iccid_apn mode  pool-r12b-icapn     100.65.121.24/29  IP_ICAPN_INT = .25, IP_ICAPN_IMS = .26
    IMSI_ICAPN_A  278771700000021
    IMSI_ICAPN_B  278771700000022

  first-connection imsi_apn
                  pool-r12b-fc-int    100.65.122.0/28   (dynamic)
                  pool-r12b-fc-ims    100.65.122.16/28  (dynamic)
    IMSI_FC_IAPN  278771700000100   not provisioned before test_12

Test cases 12b.1 – 12b.13
"""
import socket

import httpx
import pytest

from conftest import (
    ACCOUNT_NAME, PROVISION_BASE, JWT_TOKEN,
    RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET,
    make_imsi, make_iccid,
)
from fixtures.pools import create_pool, delete_pool, _force_clear_range_profiles
from fixtures.profiles import (
    create_profile_iccid,
    create_profile_imsi_apn,
    create_profile_iccid_apn,
    delete_profile,
    cleanup_stale_profiles,
)
from fixtures.range_configs import (
    create_range_config, delete_range_config,
    add_apn_pool,
)
from fixtures.radius import RadiusClient

# ── Module constants ──────────────────────────────────────────────────────────

MODULE = 17

APN_INTERNET = "internet.operator.com"
APN_IMS      = "ims.operator.com"
APN_GARBAGE  = "completely.unknown.apn"

# ── iccid mode ────────────────────────────────────────────────────────────────
ICCID_ICCID      = make_iccid(MODULE, 1)      # "8944501170000000001"
IMSI_ICCID_A     = make_imsi(MODULE, 1)        # "278771700000001"
IMSI_ICCID_B     = make_imsi(MODULE, 2)        # "278771700000002"
ICCID_STATIC_IP  = "100.65.121.1"

# ── imsi_apn mode (static profile) ────────────────────────────────────────────
IMSI_IAPN        = make_imsi(MODULE, 11)       # "278771700000011"
IP_IAPN_INT      = "100.65.121.9"
IP_IAPN_IMS      = "100.65.121.17"

# ── iccid_apn mode ────────────────────────────────────────────────────────────
ICCID_ICAPN      = make_iccid(MODULE, 3)       # "8944501170000000003"
IMSI_ICAPN_A     = make_imsi(MODULE, 21)       # "278771700000021"
IMSI_ICAPN_B     = make_imsi(MODULE, 22)       # "278771700000022"
IP_ICAPN_INT     = "100.65.121.25"
IP_ICAPN_IMS     = "100.65.121.26"

# ── first-connection imsi_apn ─────────────────────────────────────────────────
IMSI_FC_IAPN     = make_imsi(MODULE, 100)      # "278771700000100"
F_IMSI_FC_IAPN   = make_imsi(MODULE, 100)
T_IMSI_FC_IAPN   = make_imsi(MODULE, 199)      # "278771700000199"

# Verify all IMSIs are 15 digits at import time.
for _name, _imsi in [
    ("IMSI_ICCID_A",   IMSI_ICCID_A),
    ("IMSI_ICCID_B",   IMSI_ICCID_B),
    ("IMSI_IAPN",      IMSI_IAPN),
    ("IMSI_ICAPN_A",   IMSI_ICAPN_A),
    ("IMSI_ICAPN_B",   IMSI_ICAPN_B),
    ("IMSI_FC_IAPN",   IMSI_FC_IAPN),
    ("F_IMSI_FC_IAPN", F_IMSI_FC_IAPN),
    ("T_IMSI_FC_IAPN", T_IMSI_FC_IAPN),
]:
    assert len(_imsi) == 15, f"{_name}={_imsi!r} is {len(_imsi)} chars, expected 15"


# ── RADIUS availability helper ─────────────────────────────────────────────────

def _radius_available(host: str, port: int, secret: str) -> bool:
    """Return True if aaa-radius-server responds within 3 seconds."""
    rc = RadiusClient(host, port, secret, timeout=3.0)
    try:
        rc.authenticate("278770000000000", "health-check")
        return True
    except (socket.timeout, OSError):
        return False


# ── Test class ────────────────────────────────────────────────────────────────

@pytest.mark.radius
class TestRadiusModes:
    """RADIUS end-to-end tests for iccid, imsi_apn, and iccid_apn resolution modes.

    Each test sends a real RADIUS UDP Access-Request and asserts on the response
    code and Framed-IP-Address attribute.  The provisioning API is used only in
    setup/teardown and the per-IMSI suspend test (12b.11).

    State shared across tests via class variables (set in setup_class, read by tests):
      pool_ids     — dict of pool_id per mode
      iccid_sim_id — sim_id for the iccid profile
      iapn_sim_id  — sim_id for the imsi_apn static profile
      icapn_sim_id — sim_id for the iccid_apn profile
      fc_range_id  — range config for first-connection imsi_apn tests
      fc_sim_id    — sim_id created during test_12 (stored for teardown)
    """

    pool_ids:      dict     = {}
    iccid_sim_id:  str | None = None
    iapn_sim_id:   str | None = None
    icapn_sim_id:  str | None = None
    fc_range_id:   int | None = None
    fc_sim_id:     str | None = None
    fc_internet_ip: str | None = None   # filled by test_12
    fc_ims_ip:      str | None = None   # filled by test_13

    @classmethod
    def setup_class(cls):
        if not _radius_available(RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET):
            pytest.skip(
                f"aaa-radius-server not reachable at {RADIUS_HOST}:{RADIUS_PORT} — "
                "skipping test_12b"
            )

        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            # ── Cleanup stale data from previous runs ──────────────────────────
            cleanup_stale_profiles(c, f"27877{MODULE:02d}")

        # Hard-delete terminated profiles that lock ICCIDs (not removed by soft-delete)
        _force_clear_range_profiles(IMSI_ICCID_A,  IMSI_ICCID_B)
        _force_clear_range_profiles(IMSI_IAPN,     IMSI_IAPN)
        _force_clear_range_profiles(IMSI_ICAPN_A,  IMSI_ICAPN_B)
        _force_clear_range_profiles(F_IMSI_FC_IAPN, T_IMSI_FC_IAPN)

        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            # ── iccid mode pool + profile ──────────────────────────────────────
            p_iccid = create_pool(c, subnet="100.65.121.0/29",
                                  pool_name="pool-r12b-iccid",
                                  account_name=ACCOUNT_NAME,
                                  replace_on_conflict=True)
            cls.pool_ids["iccid"] = p_iccid["pool_id"]

            b_iccid = create_profile_iccid(
                c,
                iccid=ICCID_ICCID,
                account_name=ACCOUNT_NAME,
                imsis=[IMSI_ICCID_A, IMSI_ICCID_B],
                static_ip=ICCID_STATIC_IP,
                pool_id=cls.pool_ids["iccid"],
                pool_name="pool-r12b-iccid",
            )
            cls.iccid_sim_id = b_iccid["sim_id"]

            # ── imsi_apn mode pools + static profile ───────────────────────────
            p_iapn_int = create_pool(c, subnet="100.65.121.8/29",
                                     pool_name="pool-r12b-iapn-int",
                                     account_name=ACCOUNT_NAME,
                                     replace_on_conflict=True)
            cls.pool_ids["iapn_int"] = p_iapn_int["pool_id"]

            p_iapn_ims = create_pool(c, subnet="100.65.121.16/29",
                                     pool_name="pool-r12b-iapn-ims",
                                     account_name=ACCOUNT_NAME,
                                     replace_on_conflict=True)
            cls.pool_ids["iapn_ims"] = p_iapn_ims["pool_id"]

            b_iapn = create_profile_imsi_apn(
                c,
                iccid=None,
                account_name=ACCOUNT_NAME,
                imsis=[{
                    "imsi": IMSI_IAPN,
                    "apn_ips": [
                        {"apn": APN_INTERNET, "static_ip": IP_IAPN_INT,
                         "pool_id": cls.pool_ids["iapn_int"]},
                        {"apn": APN_IMS,      "static_ip": IP_IAPN_IMS,
                         "pool_id": cls.pool_ids["iapn_ims"]},
                    ],
                }],
            )
            cls.iapn_sim_id = b_iapn["sim_id"]

            # ── iccid_apn mode pool + profile ──────────────────────────────────
            p_icapn = create_pool(c, subnet="100.65.121.24/29",
                                  pool_name="pool-r12b-icapn",
                                  account_name=ACCOUNT_NAME,
                                  replace_on_conflict=True)
            cls.pool_ids["icapn"] = p_icapn["pool_id"]

            b_icapn = create_profile_iccid_apn(
                c,
                iccid=ICCID_ICAPN,
                account_name=ACCOUNT_NAME,
                imsis=[IMSI_ICAPN_A, IMSI_ICAPN_B],
                apn_ips=[
                    {"apn": APN_INTERNET, "static_ip": IP_ICAPN_INT,
                     "pool_id": cls.pool_ids["icapn"]},
                    {"apn": APN_IMS,      "static_ip": IP_ICAPN_IMS,
                     "pool_id": cls.pool_ids["icapn"]},
                ],
                pool_name="pool-r12b-icapn",
            )
            cls.icapn_sim_id = b_icapn["sim_id"]

            # ── First-connection imsi_apn pools + range config ─────────────────
            p_fc_int = create_pool(c, subnet="100.65.122.0/28",
                                   pool_name="pool-r12b-fc-int",
                                   account_name=ACCOUNT_NAME,
                                   replace_on_conflict=True)
            cls.pool_ids["fc_int"] = p_fc_int["pool_id"]

            p_fc_ims = create_pool(c, subnet="100.65.122.16/28",
                                   pool_name="pool-r12b-fc-ims",
                                   account_name=ACCOUNT_NAME,
                                   replace_on_conflict=True)
            cls.pool_ids["fc_ims"] = p_fc_ims["pool_id"]

            rc_fc = create_range_config(
                c,
                f_imsi=F_IMSI_FC_IAPN,
                t_imsi=T_IMSI_FC_IAPN,
                pool_id=cls.pool_ids["fc_int"],
                ip_resolution="imsi_apn",
                account_name=ACCOUNT_NAME,
            )
            cls.fc_range_id = rc_fc["id"]

            # APN catalog: internet → fc_int pool, ims → fc_ims pool
            add_apn_pool(c, range_config_id=cls.fc_range_id,
                         apn=APN_INTERNET, pool_id=cls.pool_ids["fc_int"])
            add_apn_pool(c, range_config_id=cls.fc_range_id,
                         apn=APN_IMS,      pool_id=cls.pool_ids["fc_ims"])

    @classmethod
    def teardown_class(cls):
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            # Delete profiles (order does not matter; soft-delete is idempotent)
            for sim_id in filter(None, [
                cls.iccid_sim_id, cls.iapn_sim_id,
                cls.icapn_sim_id, cls.fc_sim_id,
            ]):
                try:
                    c.delete(f"/profiles/{sim_id}")
                except Exception:
                    pass

            # Delete range config before pools (FK constraint)
            if cls.fc_range_id:
                delete_range_config(c, cls.fc_range_id)

            # Delete pools last
            for pool_id in cls.pool_ids.values():
                if pool_id:
                    delete_pool(c, pool_id)

    @pytest.fixture(autouse=True)
    def rc(self) -> RadiusClient:
        """Per-test RADIUS client."""
        return RadiusClient(RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET)

    # ── iccid mode ─────────────────────────────────────────────────────────────

    # 12b.1 ───────────────────────────────────────────────────────────────────
    def test_01_iccid_imsi_a_accept(self, rc: RadiusClient):
        """iccid mode: IMSI_ICCID_A → Access-Accept with card-level IP.

        Production path: aaa-radius-server → GET /lookup → 200 with static_ip.
        Resolver::resolveIccid picks the row where sim_apn_ips.apn IS NULL.
        """
        resp = rc.authenticate(IMSI_ICCID_A, APN_INTERNET)
        assert resp.is_accept, \
            f"Expected Access-Accept for iccid IMSI_A, got code={resp.code}"
        assert resp.framed_ip == ICCID_STATIC_IP, \
            f"Framed-IP={resp.framed_ip!r}, expected {ICCID_STATIC_IP!r}"

    # 12b.2 ───────────────────────────────────────────────────────────────────
    def test_02_iccid_imsi_b_same_card_ip(self, rc: RadiusClient):
        """iccid mode: IMSI_ICCID_B (secondary IMSI on same card) → same Framed-IP.

        Both IMSIs share the single sim_apn_ips row keyed on sim_id.
        The APN in Called-Station-Id is irrelevant.
        """
        resp = rc.authenticate(IMSI_ICCID_B, APN_IMS)
        assert resp.is_accept, \
            f"Expected Access-Accept for iccid IMSI_B, got code={resp.code}"
        assert resp.framed_ip == ICCID_STATIC_IP, \
            f"IMSI_B Framed-IP={resp.framed_ip!r}, expected same card IP {ICCID_STATIC_IP!r}"

    # 12b.3 ───────────────────────────────────────────────────────────────────
    def test_03_iccid_apn_completely_ignored(self, rc: RadiusClient):
        """iccid mode: garbage APN in Called-Station-Id → card IP still returned.

        The Resolver does not inspect APN at all in iccid mode — the lookup
        service must ignore it and return the card-level IP regardless.
        """
        resp = rc.authenticate(IMSI_ICCID_A, APN_GARBAGE)
        assert resp.is_accept, \
            f"iccid mode must ignore APN; expected Accept, got code={resp.code}"
        assert resp.framed_ip == ICCID_STATIC_IP, \
            f"Framed-IP={resp.framed_ip!r}, expected {ICCID_STATIC_IP!r}"

    # ── imsi_apn mode ──────────────────────────────────────────────────────────

    # 12b.4 ───────────────────────────────────────────────────────────────────
    def test_04_imsi_apn_internet_accept(self, rc: RadiusClient):
        """imsi_apn mode: Called-Station-Id=internet → Access-Accept with IP_IAPN_INT.

        Resolver::resolveImsiApn finds the row with imsi_apn_ips.apn = APN_INTERNET.
        """
        resp = rc.authenticate(IMSI_IAPN, APN_INTERNET)
        assert resp.is_accept, \
            f"Expected Accept for imsi_apn+internet, got code={resp.code}"
        assert resp.framed_ip == IP_IAPN_INT, \
            f"Framed-IP={resp.framed_ip!r}, expected internet IP {IP_IAPN_INT!r}"

    # 12b.5 ───────────────────────────────────────────────────────────────────
    def test_05_imsi_apn_ims_accept_different_ip(self, rc: RadiusClient):
        """imsi_apn mode: Called-Station-Id=ims → Access-Accept with IP_IAPN_IMS.

        Different APN → different Framed-IP-Address for the same IMSI.
        Verifies the APN is correctly extracted from Called-Station-Id and forwarded
        to the lookup service by aaa-radius-server.
        """
        resp = rc.authenticate(IMSI_IAPN, APN_IMS)
        assert resp.is_accept, \
            f"Expected Accept for imsi_apn+ims, got code={resp.code}"
        assert resp.framed_ip == IP_IAPN_IMS, \
            f"Framed-IP={resp.framed_ip!r}, expected ims IP {IP_IAPN_IMS!r}"
        assert resp.framed_ip != IP_IAPN_INT, \
            "ims APN must return a different IP than internet APN"

    # 12b.6 ───────────────────────────────────────────────────────────────────
    def test_06_imsi_apn_unknown_apn_reject(self, rc: RadiusClient):
        """imsi_apn mode: unknown APN → Access-Reject.

        lookup returns 404 {error: apn_not_found} (no exact match, no wildcard).
        aaa-radius-server must translate this into Access-Reject (code=3).
        """
        resp = rc.authenticate(IMSI_IAPN, APN_GARBAGE)
        assert resp.is_reject, (
            f"Expected Access-Reject for unknown APN in imsi_apn mode, "
            f"got code={resp.code}. "
            "aaa-radius-server may not be mapping apn_not_found → Reject."
        )

    # ── iccid_apn mode ────────────────────────────────────────────────────────

    # 12b.7 ───────────────────────────────────────────────────────────────────
    def test_07_iccid_apn_internet_accept(self, rc: RadiusClient):
        """iccid_apn mode: Called-Station-Id=internet → Access-Accept with IP_ICAPN_INT.

        Card-level APN routing: the lookup resolves sim_apn_ips for sim_id+APN pair.
        """
        resp = rc.authenticate(IMSI_ICAPN_A, APN_INTERNET)
        assert resp.is_accept, \
            f"Expected Accept for iccid_apn+internet, got code={resp.code}"
        assert resp.framed_ip == IP_ICAPN_INT, \
            f"Framed-IP={resp.framed_ip!r}, expected {IP_ICAPN_INT!r}"

    # 12b.8 ───────────────────────────────────────────────────────────────────
    def test_08_iccid_apn_ims_accept(self, rc: RadiusClient):
        """iccid_apn mode: Called-Station-Id=ims → Access-Accept with IP_ICAPN_IMS."""
        resp = rc.authenticate(IMSI_ICAPN_A, APN_IMS)
        assert resp.is_accept, \
            f"Expected Accept for iccid_apn+ims, got code={resp.code}"
        assert resp.framed_ip == IP_ICAPN_IMS, \
            f"Framed-IP={resp.framed_ip!r}, expected {IP_ICAPN_IMS!r}"

    # 12b.9 ───────────────────────────────────────────────────────────────────
    def test_09_iccid_apn_sibling_imsi_same_card_ips(self, rc: RadiusClient):
        """iccid_apn mode: sibling IMSI on same card resolves identical card-level IPs.

        IMSI_ICAPN_B is a second IMSI bound to the same sim_id; it shares the same
        sim_apn_ips rows so the Framed-IP must be identical to IMSI_ICAPN_A for each APN.
        """
        for apn, expected_ip in [(APN_INTERNET, IP_ICAPN_INT), (APN_IMS, IP_ICAPN_IMS)]:
            resp = rc.authenticate(IMSI_ICAPN_B, apn)
            assert resp.is_accept, \
                f"IMSI_ICAPN_B apn={apn}: expected Accept, got code={resp.code}"
            assert resp.framed_ip == expected_ip, \
                f"IMSI_ICAPN_B apn={apn}: Framed-IP={resp.framed_ip!r}, expected {expected_ip!r}"

    # 12b.10 ──────────────────────────────────────────────────────────────────
    def test_10_iccid_apn_unknown_apn_reject(self, rc: RadiusClient):
        """iccid_apn mode: unknown APN → Access-Reject.

        Mirrors test_06 but for card-level APN routing.
        lookup returns 404 apn_not_found → aaa-radius-server emits Access-Reject.
        """
        resp = rc.authenticate(IMSI_ICAPN_A, APN_GARBAGE)
        assert resp.is_reject, (
            f"Expected Access-Reject for unknown APN in iccid_apn mode, "
            f"got code={resp.code}"
        )

    # ── per-IMSI suspend ──────────────────────────────────────────────────────

    # 12b.11 ──────────────────────────────────────────────────────────────────
    def test_11_per_imsi_suspend_reject_sibling_accept(
            self, http: httpx.Client, rc: RadiusClient):
        """Per-IMSI suspend → Access-Reject for suspended IMSI; sibling still Accept.

        Gaps covered vs test_12:
          - test_12 only tests SIM-level suspend (PATCH /profiles/{id}).
          - This test exercises per-IMSI suspend (PATCH /profiles/{id}/imsis/{imsi})
            which sets imsi2sim.status='suspended' while sim_profiles.status='active'.
          - The Resolver checks BOTH sim_status AND imsi_status; either non-active → 403.

        Uses the iccid mode profile (IMSI_ICCID_A and IMSI_ICCID_B):
          Suspend IMSI_ICCID_A → Access-Reject
          IMSI_ICCID_B (same card, still active) → Access-Accept with card IP
          Reactivate IMSI_ICCID_A → Access-Accept again
        """
        # Suspend IMSI_ICCID_A at IMSI level
        r = http.patch(
            f"/profiles/{TestRadiusModes.iccid_sim_id}/imsis/{IMSI_ICCID_A}",
            json={"status": "suspended"},
        )
        assert r.status_code == 200, f"PATCH imsi suspend failed: {r.status_code} {r.text}"

        # Suspended IMSI → Access-Reject
        resp_a = rc.authenticate(IMSI_ICCID_A, APN_INTERNET)
        assert resp_a.is_reject, (
            f"Expected Access-Reject for suspended IMSI_ICCID_A, got code={resp_a.code}. "
            "aaa-radius-server must treat imsi_status=suspended the same as sim_status=suspended."
        )

        # Sibling IMSI on same card → still Access-Accept (only its own imsi_status checked)
        resp_b = rc.authenticate(IMSI_ICCID_B, APN_INTERNET)
        assert resp_b.is_accept, \
            f"Expected Accept for active IMSI_ICCID_B while sibling suspended, got code={resp_b.code}"
        assert resp_b.framed_ip == ICCID_STATIC_IP, \
            f"IMSI_ICCID_B Framed-IP={resp_b.framed_ip!r}, expected {ICCID_STATIC_IP!r}"

        # Reactivate IMSI_ICCID_A → Accept again
        r2 = http.patch(
            f"/profiles/{TestRadiusModes.iccid_sim_id}/imsis/{IMSI_ICCID_A}",
            json={"status": "active"},
        )
        assert r2.status_code == 200, f"PATCH imsi reactivate failed: {r2.status_code} {r2.text}"

        resp_a2 = rc.authenticate(IMSI_ICCID_A, APN_INTERNET)
        assert resp_a2.is_accept, \
            f"Expected Accept after reactivation of IMSI_ICCID_A, got code={resp_a2.code}"
        assert resp_a2.framed_ip == ICCID_STATIC_IP

    # ── first-connection for imsi_apn mode ───────────────────────────────────

    # 12b.12 ──────────────────────────────────────────────────────────────────
    def test_12_first_connection_imsi_apn_internet_accept(
            self, http: httpx.Client, lookup_http: httpx.Client, rc: RadiusClient):
        """imsi_apn first-connection via RADIUS: internet APN → Accept + Framed-IP.

        IMSI_FC_IAPN has no profile before this test.  The full production path fires:
          RADIUS → aaa-radius-server → GET /lookup → 404 not_found
                 → POST /first-connection → allocates BOTH internet AND ims IPs
                 → 200/201 with internet static_ip
                 → aaa-radius-server → Access-Accept with Framed-IP-Address

        The APN catalog registered in setup_class contains both internet and ims,
        so first-connection must allocate both in a single transaction.
        """
        # Confirm no profile exists before the test
        r_pre = http.get("/profiles", params={"imsi": IMSI_FC_IAPN})
        if r_pre.status_code == 200:
            data = r_pre.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            assert not profiles, "Pre-condition: IMSI_FC_IAPN must not have a profile yet"

        resp = rc.authenticate(IMSI_FC_IAPN, APN_INTERNET,
                               imei="35812300000010", charging_chars="0800")
        assert resp.is_accept, (
            f"Expected Access-Accept via imsi_apn first-connection (internet), "
            f"got code={resp.code}. "
            "Check range config ip_resolution=imsi_apn and APN catalog in setup."
        )
        assert resp.framed_ip is not None, \
            "Access-Accept must carry Framed-IP-Address after imsi_apn first-connection"

        TestRadiusModes.fc_internet_ip = resp.framed_ip

        # Fetch the auto-created sim_id for teardown
        r_profile = http.get("/profiles", params={"imsi": IMSI_FC_IAPN})
        if r_profile.status_code == 200:
            data = r_profile.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            if profiles:
                TestRadiusModes.fc_sim_id = profiles[0]["sim_id"]

        # Lookup service must now return the internet IP directly (stage 1 succeeds)
        r_lkp = lookup_http.get("/lookup",
                                params={"imsi": IMSI_FC_IAPN, "apn": APN_INTERNET})
        assert r_lkp.status_code == 200
        assert r_lkp.json()["static_ip"] == resp.framed_ip

    # 12b.13 ──────────────────────────────────────────────────────────────────
    def test_13_first_connection_imsi_apn_ims_accept_different_ip(
            self, rc: RadiusClient):
        """imsi_apn first-connection: ims APN → Accept with different Framed-IP.

        Depends on test_12 having created the profile (APN catalog pre-allocated both
        internet and ims IPs in a single first-connection transaction).

        Sending the ims APN now hits stage 1 directly (profile already exists)
        and must return the ims IP that was pre-allocated — NOT trigger a second
        first-connection.

        This verifies that first-connection correctly allocates ALL configured APNs
        in the catalog, not just the APN that triggered the request.
        """
        assert TestRadiusModes.fc_internet_ip is not None, \
            "test_12 must run first (fc_internet_ip not set)"

        resp = rc.authenticate(IMSI_FC_IAPN, APN_IMS)
        assert resp.is_accept, \
            f"Expected Accept for ims APN (pre-allocated in first-connection), got code={resp.code}"
        assert resp.framed_ip is not None, \
            "Framed-IP must be present for ims APN"
        assert resp.framed_ip != TestRadiusModes.fc_internet_ip, (
            f"ims Framed-IP must differ from internet Framed-IP — "
            f"internet={TestRadiusModes.fc_internet_ip!r}, ims={resp.framed_ip!r}"
        )

        TestRadiusModes.fc_ims_ip = resp.framed_ip
