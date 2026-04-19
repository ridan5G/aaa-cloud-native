"""
test_12c_radius_3imsi_modes.py — RADIUS end-to-end: all 4 ip_resolution modes
with 3 IMSIs per SIM and per-slot first-connection via ICCID range configs.

Coverage beyond test_12b
─────────────────────────
  imsi mode       — 3 IMSIs, each with its own static IP; APN ignored.
                    FC via ICCID range config (3 slots, each with its own pool):
                    slot-1 first-connect pre-provisions slots 2 and 3 with
                    DIFFERENT IPs (one per slot pool).
  iccid mode      — 3 IMSIs on same card share a single card-level IP.
                    FC via ICCID range config: slot-1 first-connect
                    pre-provisions slots 2 and 3 with the SAME card IP.
  imsi_apn mode   — 3 IMSIs × smf1 + smf2; each IMSI×APN pair has its own IP.
                    FC via ICCID range config: slot-1 first-connect allocates
                    ALL APN IPs for ALL slots in one transaction
                    (each slot gets its own per-APN IPs).
  iccid_apn mode  — 3 IMSIs × smf1 + smf2; card-level APN IPs shared by all IMSIs.
                    FC via ICCID range config: slot-1 first-connect allocates
                    one smf1 and one smf2 card-level IP; slots 2 and 3 return
                    the SAME card-level IPs.

  Per-IMSI suspend/reactivate for all 4 modes.
  RFC 2865 response-authenticator verification.
  Out-of-range IMSI → Access-Reject.

Production path exercised
──────────────────────────
  UE → RADIUS UDP → aaa-radius-server → GET /lookup → aaa-lookup-service → read replica
                                      → (on 404) POST /first-connection → subscriber-profile-api
                                      → Access-Accept / Access-Reject

Resources (module = 22, IMSI prefix 2787722)
────────────────────────────────────────────
  Subnets: 100.178.244.0/22 (static) · 100.178.245.x/28 (FC dynamic pools)

  imsi mode       pool-r12c-imsi          100.178.244.0/29  IPs: .1 .2 .3
    IMSI_IMSI_A   278772200000001
    IMSI_IMSI_B   278772200000002
    IMSI_IMSI_C   278772200000003

  iccid mode      pool-r12c-iccid         100.178.244.8/29  card IP = .9
    IMSI_ICCID_A  278772200000011
    IMSI_ICCID_B  278772200000012
    IMSI_ICCID_C  278772200000013

  imsi_apn mode   pool-r12c-iapn-smf1     100.178.244.16/29 IPs: .17 .18 .19
                  pool-r12c-iapn-smf2     100.178.244.24/29 IPs: .25 .26 .27
    IMSI_IAPN_A   278772200000021
    IMSI_IAPN_B   278772200000022
    IMSI_IAPN_C   278772200000023

  iccid_apn mode  pool-r12c-icapn-smf1    100.178.244.32/29 card smf1 IP = .33
                  pool-r12c-icapn-smf2    100.178.244.40/29 card smf2 IP = .41
    IMSI_ICAPN_A  278772200000031
    IMSI_ICAPN_B  278772200000032
    IMSI_ICAPN_C  278772200000033

  FC imsi (3-slot ICCID range config, each slot its own pool):
    pool-r12c-fc-imsi-s1  100.178.245.0/28   slot-1 IPs (dynamic)
    pool-r12c-fc-imsi-s2  100.178.245.16/28  slot-2 IPs (different from s1)
    pool-r12c-fc-imsi-s3  100.178.245.32/28  slot-3 IPs

  FC imsi_apn (3-slot ICCID range config, per-slot per-APN pools):
    pool-r12c-fc-iapn-s1-smf1  100.178.245.48/28
    pool-r12c-fc-iapn-s1-smf2  100.178.245.64/28
    pool-r12c-fc-iapn-s2-smf1  100.178.245.80/28
    pool-r12c-fc-iapn-s2-smf2  100.178.245.96/28
    pool-r12c-fc-iapn-s3-smf1  100.178.245.112/28
    pool-r12c-fc-iapn-s3-smf2  100.178.245.128/28

  FC iccid (3-slot ICCID range config, one shared pool):
    pool-r12c-fc-iccid  100.178.245.144/28

  FC iccid_apn (3-slot ICCID range config, shared card-level pools):
    pool-r12c-fc-icapn-smf1  100.178.245.160/28
    pool-r12c-fc-icapn-smf2  100.178.245.176/28

Test cases 12c.1 – 12c.41
"""
import socket

import httpx
import pytest

from conftest import (
    ACCOUNT_NAME, PROVISION_BASE, JWT_TOKEN,
    RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET,
    make_imsi, make_iccid, make_imsi_range, make_iccid_range,
)
from fixtures.pools import create_pool, delete_pool, _force_clear_range_profiles, _force_clear_pool_ips
from fixtures.profiles import (
    create_profile_imsi,
    create_profile_iccid,
    create_profile_imsi_apn,
    create_profile_iccid_apn,
    delete_profile,
    cleanup_stale_profiles,
)
from fixtures.range_configs import (
    create_iccid_range_config, delete_iccid_range_config,
    add_imsi_slot, add_apn_pool,
)
from fixtures.radius import (
    RadiusClient,
    build_access_request,
    parse_response,
    verify_response_auth,
)

# ── Module constants ──────────────────────────────────────────────────────────

MODULE      = 22
APN_SMF1    = "smf1"
APN_SMF2    = "smf2"
APN_GARBAGE = "unknown.garbage.apn"

# ── imsi mode: 3 IMSIs, each with its own APN-agnostic IP ────────────────────
IMSI_IMSI_A = make_imsi(MODULE,  1)   # 278772200000001
IMSI_IMSI_B = make_imsi(MODULE,  2)   # 278772200000002
IMSI_IMSI_C = make_imsi(MODULE,  3)   # 278772200000003

IP_IMSI_A   = "100.178.244.1"
IP_IMSI_B   = "100.178.244.2"
IP_IMSI_C   = "100.178.244.3"

# ── iccid mode: 3 IMSIs on one card, shared card-level IP ────────────────────
ICCID_ICCID  = make_iccid(MODULE,  1)  # 8944501220000000001
IMSI_ICCID_A = make_imsi(MODULE, 11)   # 278772200000011
IMSI_ICCID_B = make_imsi(MODULE, 12)   # 278772200000012
IMSI_ICCID_C = make_imsi(MODULE, 13)   # 278772200000013

IP_ICCID_CARD = "100.178.244.9"

# ── imsi_apn mode: 3 IMSIs × smf1 + smf2 ────────────────────────────────────
IMSI_IAPN_A  = make_imsi(MODULE, 21)   # 278772200000021
IMSI_IAPN_B  = make_imsi(MODULE, 22)   # 278772200000022
IMSI_IAPN_C  = make_imsi(MODULE, 23)   # 278772200000023

IP_IAPN_A_SMF1 = "100.178.244.17"
IP_IAPN_B_SMF1 = "100.178.244.18"
IP_IAPN_C_SMF1 = "100.178.244.19"
IP_IAPN_A_SMF2 = "100.178.244.25"
IP_IAPN_B_SMF2 = "100.178.244.26"
IP_IAPN_C_SMF2 = "100.178.244.27"

# ── iccid_apn mode: 3 IMSIs on one card, card-level APN IPs ──────────────────
ICCID_ICAPN  = make_iccid(MODULE,  2)  # 8944501220000000002
IMSI_ICAPN_A = make_imsi(MODULE, 31)   # 278772200000031
IMSI_ICAPN_B = make_imsi(MODULE, 32)   # 278772200000032
IMSI_ICAPN_C = make_imsi(MODULE, 33)   # 278772200000033

IP_ICAPN_SMF1 = "100.178.244.33"
IP_ICAPN_SMF2 = "100.178.244.41"

# ── FC imsi: 3-slot ICCID range config, each slot has its own pool ────────────
# Single source of truth for cardinality — change _FC_IMSI_SIZE and all bounds update.
_FC_IMSI_SIZE      = 99
F_ICCID_FC_IMSI,   T_ICCID_FC_IMSI   = make_iccid_range(MODULE, 101,   _FC_IMSI_SIZE)
F_IMSI_FC_IMSI_S1, T_IMSI_FC_IMSI_S1 = make_imsi_range( MODULE, 1001,  _FC_IMSI_SIZE)
F_IMSI_FC_IMSI_S2, T_IMSI_FC_IMSI_S2 = make_imsi_range( MODULE, 2001,  _FC_IMSI_SIZE)
F_IMSI_FC_IMSI_S3, T_IMSI_FC_IMSI_S3 = make_imsi_range( MODULE, 3001,  _FC_IMSI_SIZE)
# Representative test IMSIs (first in each slot range)
IMSI_FC_IMSI_S1    = F_IMSI_FC_IMSI_S1
IMSI_FC_IMSI_S2    = F_IMSI_FC_IMSI_S2
IMSI_FC_IMSI_S3    = F_IMSI_FC_IMSI_S3

# ── FC imsi_apn: 3-slot ICCID range config, per-slot per-APN pools ───────────
_FC_IAPN_SIZE      = 99
F_ICCID_FC_IAPN,   T_ICCID_FC_IAPN   = make_iccid_range(MODULE, 201,   _FC_IAPN_SIZE)
F_IMSI_FC_IAPN_S1, T_IMSI_FC_IAPN_S1 = make_imsi_range( MODULE, 4001,  _FC_IAPN_SIZE)
F_IMSI_FC_IAPN_S2, T_IMSI_FC_IAPN_S2 = make_imsi_range( MODULE, 5001,  _FC_IAPN_SIZE)
F_IMSI_FC_IAPN_S3, T_IMSI_FC_IAPN_S3 = make_imsi_range( MODULE, 6001,  _FC_IAPN_SIZE)
IMSI_FC_IAPN_S1    = F_IMSI_FC_IAPN_S1
IMSI_FC_IAPN_S2    = F_IMSI_FC_IAPN_S2
IMSI_FC_IAPN_S3    = F_IMSI_FC_IAPN_S3

# ── FC iccid: 3-slot ICCID range config, single shared card pool ──────────────
_FC_ICCID_SIZE      = 99
F_ICCID_FC_ICCID,   T_ICCID_FC_ICCID   = make_iccid_range(MODULE, 301,   _FC_ICCID_SIZE)
F_IMSI_FC_ICCID_S1, T_IMSI_FC_ICCID_S1 = make_imsi_range( MODULE, 7001,  _FC_ICCID_SIZE)
F_IMSI_FC_ICCID_S2, T_IMSI_FC_ICCID_S2 = make_imsi_range( MODULE, 8001,  _FC_ICCID_SIZE)
F_IMSI_FC_ICCID_S3, T_IMSI_FC_ICCID_S3 = make_imsi_range( MODULE, 9001,  _FC_ICCID_SIZE)
IMSI_FC_ICCID_S1    = F_IMSI_FC_ICCID_S1
IMSI_FC_ICCID_S2    = F_IMSI_FC_ICCID_S2
IMSI_FC_ICCID_S3    = F_IMSI_FC_ICCID_S3

# ── FC iccid_apn: 3-slot ICCID range config, shared card-level APN pools ──────
_FC_ICAPN_SIZE      = 99
F_ICCID_FC_ICAPN,   T_ICCID_FC_ICAPN   = make_iccid_range(MODULE, 401,   _FC_ICAPN_SIZE)
F_IMSI_FC_ICAPN_S1, T_IMSI_FC_ICAPN_S1 = make_imsi_range( MODULE, 10001, _FC_ICAPN_SIZE)
F_IMSI_FC_ICAPN_S2, T_IMSI_FC_ICAPN_S2 = make_imsi_range( MODULE, 20001, _FC_ICAPN_SIZE)
F_IMSI_FC_ICAPN_S3, T_IMSI_FC_ICAPN_S3 = make_imsi_range( MODULE, 30001, _FC_ICAPN_SIZE)
IMSI_FC_ICAPN_S1    = F_IMSI_FC_ICAPN_S1
IMSI_FC_ICAPN_S2    = F_IMSI_FC_ICAPN_S2
IMSI_FC_ICAPN_S3    = F_IMSI_FC_ICAPN_S3

# ── Out-of-range IMSI (module 99 — deliberately outside all module-22 configs) ─
IMSI_OOB = "278779900000001"   # module-99 prefix: no range configs exist for it

# ── Validate all IMSIs are 15 digits ─────────────────────────────────────────
for _name, _imsi in [
    ("IMSI_IMSI_A",     IMSI_IMSI_A),
    ("IMSI_IMSI_B",     IMSI_IMSI_B),
    ("IMSI_IMSI_C",     IMSI_IMSI_C),
    ("IMSI_ICCID_A",    IMSI_ICCID_A),
    ("IMSI_ICCID_B",    IMSI_ICCID_B),
    ("IMSI_ICCID_C",    IMSI_ICCID_C),
    ("IMSI_IAPN_A",     IMSI_IAPN_A),
    ("IMSI_IAPN_B",     IMSI_IAPN_B),
    ("IMSI_IAPN_C",     IMSI_IAPN_C),
    ("IMSI_ICAPN_A",    IMSI_ICAPN_A),
    ("IMSI_ICAPN_B",    IMSI_ICAPN_B),
    ("IMSI_ICAPN_C",    IMSI_ICAPN_C),
    ("IMSI_FC_IMSI_S1", IMSI_FC_IMSI_S1),
    ("IMSI_FC_IMSI_S2", IMSI_FC_IMSI_S2),
    ("IMSI_FC_IMSI_S3", IMSI_FC_IMSI_S3),
    ("IMSI_FC_IAPN_S1", IMSI_FC_IAPN_S1),
    ("IMSI_FC_IAPN_S2", IMSI_FC_IAPN_S2),
    ("IMSI_FC_IAPN_S3", IMSI_FC_IAPN_S3),
    ("IMSI_FC_ICCID_S1", IMSI_FC_ICCID_S1),
    ("IMSI_FC_ICCID_S2", IMSI_FC_ICCID_S2),
    ("IMSI_FC_ICCID_S3", IMSI_FC_ICCID_S3),
    ("IMSI_FC_ICAPN_S1", IMSI_FC_ICAPN_S1),
    ("IMSI_FC_ICAPN_S2", IMSI_FC_ICAPN_S2),
    ("IMSI_FC_ICAPN_S3", IMSI_FC_ICAPN_S3),
    ("IMSI_OOB",        IMSI_OOB),
]:
    assert len(_imsi) == 15, f"{_name}={_imsi!r} is {len(_imsi)} chars, expected 15"


# ── RADIUS availability helper ────────────────────────────────────────────────

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
class TestRadius3ImsiModes:
    """RADIUS end-to-end: all 4 ip_resolution modes with 3-IMSI SIMs.

    Each test sends a real RADIUS UDP Access-Request and asserts on the
    response code and Framed-IP-Address attribute.

    State shared across tests via class variables (set in setup_class):
      pool_ids           — dict of pool_id strings keyed by pool label
      imsi_sim_id        — sim_id for the imsi-mode pre-provisioned profile
      iccid_sim_id       — sim_id for the iccid-mode profile
      iapn_sim_id        — sim_id for the imsi_apn-mode static profile
      icapn_sim_id       — sim_id for the iccid_apn-mode profile
      fc_imsi_rc_id      — ICCID range config id for FC imsi tests
      fc_iapn_rc_id      — ICCID range config id for FC imsi_apn tests
      fc_iccid_rc_id     — ICCID range config id for FC iccid tests
      fc_icapn_rc_id     — ICCID range config id for FC iccid_apn tests
      fc_imsi_sim_id     — sim_id auto-created by imsi FC (teardown)
      fc_iapn_sim_id     — sim_id auto-created by imsi_apn FC (teardown)
      fc_iccid_sim_id    — sim_id auto-created by iccid FC (teardown)
      fc_icapn_sim_id    — sim_id auto-created by iccid_apn FC (teardown)
    """

    pool_ids:        dict       = {}
    imsi_sim_id:     str | None = None
    iccid_sim_id:    str | None = None
    iapn_sim_id:     str | None = None
    icapn_sim_id:    str | None = None

    fc_imsi_rc_id:   int | None = None
    fc_iapn_rc_id:   int | None = None
    fc_iccid_rc_id:  int | None = None
    fc_icapn_rc_id:  int | None = None

    fc_imsi_sim_id:  str | None = None
    fc_iapn_sim_id:  str | None = None
    fc_iccid_sim_id: str | None = None
    fc_icapn_sim_id: str | None = None

    # Stored IPs from FC tests (read by later FC sub-tests)
    ip_fc_imsi_s1:      str | None = None
    ip_fc_imsi_s2:      str | None = None
    ip_fc_imsi_s3:      str | None = None
    ip_fc_iapn_s1_smf1: str | None = None
    ip_fc_iapn_s1_smf2: str | None = None
    ip_fc_iapn_s2_smf1: str | None = None
    ip_fc_iapn_s3_smf2: str | None = None
    ip_fc_iccid_card:   str | None = None
    ip_fc_icapn_smf1:   str | None = None
    ip_fc_icapn_smf2:   str | None = None

    @classmethod
    def setup_class(cls):
        if not _radius_available(RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET):
            pytest.skip(
                f"aaa-radius-server not reachable at {RADIUS_HOST}:{RADIUS_PORT} — "
                "skipping test_12c"
            )

        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            # ── Cleanup stale data from previous runs ──────────────────────────
            cleanup_stale_profiles(c, f"27877{MODULE:02d}")

        # Hard-delete terminated profiles that lock ICCIDs (not removed by soft-delete)
        _force_clear_range_profiles(IMSI_IMSI_A,      IMSI_IMSI_C)
        _force_clear_range_profiles(IMSI_ICCID_A,     IMSI_ICCID_C)
        _force_clear_range_profiles(IMSI_IAPN_A,      IMSI_IAPN_C)
        _force_clear_range_profiles(IMSI_ICAPN_A,     IMSI_ICAPN_C)
        # FC ranges
        _force_clear_range_profiles(F_IMSI_FC_IMSI_S1,  T_IMSI_FC_IMSI_S3)
        _force_clear_range_profiles(F_IMSI_FC_IAPN_S1,  T_IMSI_FC_IAPN_S3)
        _force_clear_range_profiles(F_IMSI_FC_ICCID_S1, T_IMSI_FC_ICCID_S3)
        _force_clear_range_profiles(F_IMSI_FC_ICAPN_S1, T_IMSI_FC_ICAPN_S3)

        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:

            # ── imsi mode: pool + 3-IMSI profile ──────────────────────────────
            p_imsi = create_pool(c, subnet="100.178.244.0/29",
                                 pool_name="pool-r12c-imsi",
                                 account_name=ACCOUNT_NAME,
                                 replace_on_conflict=True)
            cls.pool_ids["imsi"] = p_imsi["pool_id"]

            b_imsi = create_profile_imsi(
                c,
                iccid=None,
                account_name=ACCOUNT_NAME,
                imsis=[
                    {"imsi": IMSI_IMSI_A, "static_ip": IP_IMSI_A,
                     "pool_id": cls.pool_ids["imsi"]},
                    {"imsi": IMSI_IMSI_B, "static_ip": IP_IMSI_B,
                     "pool_id": cls.pool_ids["imsi"]},
                    {"imsi": IMSI_IMSI_C, "static_ip": IP_IMSI_C,
                     "pool_id": cls.pool_ids["imsi"]},
                ],
                pool_name="pool-r12c-imsi",
            )
            cls.imsi_sim_id = b_imsi["sim_id"]

            # ── iccid mode: pool + 3-IMSI card profile ────────────────────────
            p_iccid = create_pool(c, subnet="100.178.244.8/29",
                                  pool_name="pool-r12c-iccid",
                                  account_name=ACCOUNT_NAME,
                                  replace_on_conflict=True)
            cls.pool_ids["iccid"] = p_iccid["pool_id"]

            b_iccid = create_profile_iccid(
                c,
                iccid=ICCID_ICCID,
                account_name=ACCOUNT_NAME,
                imsis=[IMSI_ICCID_A, IMSI_ICCID_B, IMSI_ICCID_C],
                static_ip=IP_ICCID_CARD,
                pool_id=cls.pool_ids["iccid"],
                pool_name="pool-r12c-iccid",
            )
            cls.iccid_sim_id = b_iccid["sim_id"]

            # ── imsi_apn mode: 2 pools + 3-IMSI profile (3 IMSIs × 2 APNs) ───
            p_iapn_smf1 = create_pool(c, subnet="100.178.244.16/29",
                                      pool_name="pool-r12c-iapn-smf1",
                                      account_name=ACCOUNT_NAME,
                                      replace_on_conflict=True)
            cls.pool_ids["iapn_smf1"] = p_iapn_smf1["pool_id"]

            p_iapn_smf2 = create_pool(c, subnet="100.178.244.24/29",
                                      pool_name="pool-r12c-iapn-smf2",
                                      account_name=ACCOUNT_NAME,
                                      replace_on_conflict=True)
            cls.pool_ids["iapn_smf2"] = p_iapn_smf2["pool_id"]

            b_iapn = create_profile_imsi_apn(
                c,
                iccid=None,
                account_name=ACCOUNT_NAME,
                imsis=[
                    {
                        "imsi": IMSI_IAPN_A,
                        "apn_ips": [
                            {"apn": APN_SMF1, "static_ip": IP_IAPN_A_SMF1,
                             "pool_id": cls.pool_ids["iapn_smf1"]},
                            {"apn": APN_SMF2, "static_ip": IP_IAPN_A_SMF2,
                             "pool_id": cls.pool_ids["iapn_smf2"]},
                        ],
                    },
                    {
                        "imsi": IMSI_IAPN_B,
                        "apn_ips": [
                            {"apn": APN_SMF1, "static_ip": IP_IAPN_B_SMF1,
                             "pool_id": cls.pool_ids["iapn_smf1"]},
                            {"apn": APN_SMF2, "static_ip": IP_IAPN_B_SMF2,
                             "pool_id": cls.pool_ids["iapn_smf2"]},
                        ],
                    },
                    {
                        "imsi": IMSI_IAPN_C,
                        "apn_ips": [
                            {"apn": APN_SMF1, "static_ip": IP_IAPN_C_SMF1,
                             "pool_id": cls.pool_ids["iapn_smf1"]},
                            {"apn": APN_SMF2, "static_ip": IP_IAPN_C_SMF2,
                             "pool_id": cls.pool_ids["iapn_smf2"]},
                        ],
                    },
                ],
                pool_name="pool-r12c-iapn",
            )
            cls.iapn_sim_id = b_iapn["sim_id"]

            # ── iccid_apn mode: 2 pools + card profile (3 IMSIs × 2 APNs) ────
            p_icapn_smf1 = create_pool(c, subnet="100.178.244.32/29",
                                       pool_name="pool-r12c-icapn-smf1",
                                       account_name=ACCOUNT_NAME,
                                       replace_on_conflict=True)
            cls.pool_ids["icapn_smf1"] = p_icapn_smf1["pool_id"]

            p_icapn_smf2 = create_pool(c, subnet="100.178.244.40/29",
                                       pool_name="pool-r12c-icapn-smf2",
                                       account_name=ACCOUNT_NAME,
                                       replace_on_conflict=True)
            cls.pool_ids["icapn_smf2"] = p_icapn_smf2["pool_id"]

            b_icapn = create_profile_iccid_apn(
                c,
                iccid=ICCID_ICAPN,
                account_name=ACCOUNT_NAME,
                imsis=[IMSI_ICAPN_A, IMSI_ICAPN_B, IMSI_ICAPN_C],
                apn_ips=[
                    {"apn": APN_SMF1, "static_ip": IP_ICAPN_SMF1,
                     "pool_id": cls.pool_ids["icapn_smf1"]},
                    {"apn": APN_SMF2, "static_ip": IP_ICAPN_SMF2,
                     "pool_id": cls.pool_ids["icapn_smf2"]},
                ],
                pool_name="pool-r12c-icapn",
            )
            cls.icapn_sim_id = b_icapn["sim_id"]

            # ── FC imsi: pools + 3-slot ICCID range config ────────────────────
            # Each slot has its own pool so slot-1 FC allocates IP_a (pool s1),
            # sibling loop allocates IP_b (pool s2) and IP_c (pool s3) — all distinct.
            for label, subnet in [
                ("fc_imsi_s1", "100.178.245.0/28"),
                ("fc_imsi_s2", "100.178.245.16/28"),
                ("fc_imsi_s3", "100.178.245.32/28"),
            ]:
                p = create_pool(c, subnet=subnet,
                                pool_name=f"pool-r12c-{label}",
                                account_name=ACCOUNT_NAME,
                                replace_on_conflict=True)
                cls.pool_ids[label] = p["pool_id"]

            fc_imsi_rc = create_iccid_range_config(
                c,
                f_iccid=F_ICCID_FC_IMSI,
                t_iccid=T_ICCID_FC_IMSI,
                ip_resolution="imsi",
                imsi_count=3,
                account_name=ACCOUNT_NAME,
            )
            cls.fc_imsi_rc_id = fc_imsi_rc["id"]

            for slot_num, (f_imsi, t_imsi, pool_key) in enumerate([
                (F_IMSI_FC_IMSI_S1, T_IMSI_FC_IMSI_S1, "fc_imsi_s1"),
                (F_IMSI_FC_IMSI_S2, T_IMSI_FC_IMSI_S2, "fc_imsi_s2"),
                (F_IMSI_FC_IMSI_S3, T_IMSI_FC_IMSI_S3, "fc_imsi_s3"),
            ], start=1):
                add_imsi_slot(
                    c,
                    iccid_range_id=cls.fc_imsi_rc_id,
                    f_imsi=f_imsi,
                    t_imsi=t_imsi,
                    imsi_slot=slot_num,
                    ip_resolution="imsi",
                    pool_id=cls.pool_ids[pool_key],
                )

            # ── FC imsi_apn: pools + 3-slot ICCID range config (per-slot per-APN) ──
            # Each slot has its own smf1 + smf2 pool → 6 distinct IPs after FC.
            for label, subnet in [
                ("fc_iapn_s1_smf1", "100.178.245.48/28"),
                ("fc_iapn_s1_smf2", "100.178.245.64/28"),
                ("fc_iapn_s2_smf1", "100.178.245.80/28"),
                ("fc_iapn_s2_smf2", "100.178.245.96/28"),
                ("fc_iapn_s3_smf1", "100.178.245.112/28"),
                ("fc_iapn_s3_smf2", "100.178.245.128/28"),
            ]:
                p = create_pool(c, subnet=subnet,
                                pool_name=f"pool-r12c-{label}",
                                account_name=ACCOUNT_NAME,
                                replace_on_conflict=True)
                cls.pool_ids[label] = p["pool_id"]

            fc_iapn_rc = create_iccid_range_config(
                c,
                f_iccid=F_ICCID_FC_IAPN,
                t_iccid=T_ICCID_FC_IAPN,
                ip_resolution="imsi_apn",
                imsi_count=3,
                account_name=ACCOUNT_NAME,
            )
            cls.fc_iapn_rc_id = fc_iapn_rc["id"]

            for slot_num, (f_imsi, t_imsi, smf1_key, smf2_key) in enumerate([
                (F_IMSI_FC_IAPN_S1, T_IMSI_FC_IAPN_S1, "fc_iapn_s1_smf1", "fc_iapn_s1_smf2"),
                (F_IMSI_FC_IAPN_S2, T_IMSI_FC_IAPN_S2, "fc_iapn_s2_smf1", "fc_iapn_s2_smf2"),
                (F_IMSI_FC_IAPN_S3, T_IMSI_FC_IAPN_S3, "fc_iapn_s3_smf1", "fc_iapn_s3_smf2"),
            ], start=1):
                slot_resp = add_imsi_slot(
                    c,
                    iccid_range_id=cls.fc_iapn_rc_id,
                    f_imsi=f_imsi,
                    t_imsi=t_imsi,
                    imsi_slot=slot_num,
                    ip_resolution="imsi_apn",
                )
                slot_rc_id = slot_resp["range_config_id"]
                add_apn_pool(c, range_config_id=slot_rc_id,
                             apn=APN_SMF1, pool_id=cls.pool_ids[smf1_key])
                add_apn_pool(c, range_config_id=slot_rc_id,
                             apn=APN_SMF2, pool_id=cls.pool_ids[smf2_key])

            # ── FC iccid: pool + 3-slot ICCID range config (shared card IP) ───
            # All 3 slots inherit the parent pool; slot-1 FC allocates one card IP,
            # sibling loop pre-provisions slots 2 and 3 with the SAME card IP.
            p_fc_iccid = create_pool(c, subnet="100.178.245.144/28",
                                     pool_name="pool-r12c-fc-iccid",
                                     account_name=ACCOUNT_NAME,
                                     replace_on_conflict=True)
            cls.pool_ids["fc_iccid"] = p_fc_iccid["pool_id"]

            fc_iccid_rc = create_iccid_range_config(
                c,
                f_iccid=F_ICCID_FC_ICCID,
                t_iccid=T_ICCID_FC_ICCID,
                ip_resolution="iccid",
                imsi_count=3,
                pool_id=cls.pool_ids["fc_iccid"],
                account_name=ACCOUNT_NAME,
            )
            cls.fc_iccid_rc_id = fc_iccid_rc["id"]

            for slot_num, (f_imsi, t_imsi) in enumerate([
                (F_IMSI_FC_ICCID_S1, T_IMSI_FC_ICCID_S1),
                (F_IMSI_FC_ICCID_S2, T_IMSI_FC_ICCID_S2),
                (F_IMSI_FC_ICCID_S3, T_IMSI_FC_ICCID_S3),
            ], start=1):
                add_imsi_slot(
                    c,
                    iccid_range_id=cls.fc_iccid_rc_id,
                    f_imsi=f_imsi,
                    t_imsi=t_imsi,
                    imsi_slot=slot_num,
                    ip_resolution="iccid",
                    # pool_id=None: slot inherits parent's fc_iccid pool
                )

            # ── FC iccid_apn: pools + 3-slot ICCID range config (shared card APN IPs) ──
            # All 3 slots reference the same smf1/smf2 pools; the card-level IPs
            # allocated for slot-1 are shared by all sibling slots.
            p_fc_icapn_smf1 = create_pool(c, subnet="100.178.245.160/28",
                                           pool_name="pool-r12c-fc-icapn-smf1",
                                           account_name=ACCOUNT_NAME,
                                           replace_on_conflict=True)
            cls.pool_ids["fc_icapn_smf1"] = p_fc_icapn_smf1["pool_id"]

            p_fc_icapn_smf2 = create_pool(c, subnet="100.178.245.176/28",
                                           pool_name="pool-r12c-fc-icapn-smf2",
                                           account_name=ACCOUNT_NAME,
                                           replace_on_conflict=True)
            cls.pool_ids["fc_icapn_smf2"] = p_fc_icapn_smf2["pool_id"]

            fc_icapn_rc = create_iccid_range_config(
                c,
                f_iccid=F_ICCID_FC_ICAPN,
                t_iccid=T_ICCID_FC_ICAPN,
                ip_resolution="iccid_apn",
                imsi_count=3,
                account_name=ACCOUNT_NAME,
            )
            cls.fc_icapn_rc_id = fc_icapn_rc["id"]

            for slot_num, (f_imsi, t_imsi) in enumerate([
                (F_IMSI_FC_ICAPN_S1, T_IMSI_FC_ICAPN_S1),
                (F_IMSI_FC_ICAPN_S2, T_IMSI_FC_ICAPN_S2),
                (F_IMSI_FC_ICAPN_S3, T_IMSI_FC_ICAPN_S3),
            ], start=1):
                slot_resp = add_imsi_slot(
                    c,
                    iccid_range_id=cls.fc_icapn_rc_id,
                    f_imsi=f_imsi,
                    t_imsi=t_imsi,
                    imsi_slot=slot_num,
                    ip_resolution="iccid_apn",
                )
                slot_rc_id = slot_resp["range_config_id"]
                # All slots reference the same card-level pools
                add_apn_pool(c, range_config_id=slot_rc_id,
                             apn=APN_SMF1, pool_id=cls.pool_ids["fc_icapn_smf1"])
                add_apn_pool(c, range_config_id=slot_rc_id,
                             apn=APN_SMF2, pool_id=cls.pool_ids["fc_icapn_smf2"])

    @classmethod
    def teardown_class(cls):
        # Force-delete all profiles by IMSI range so teardown is robust against
        # tests that failed before capturing a sim_id, and against FC paths that
        # auto-create sibling profiles not tracked in cls.*_sim_id attributes.
        _force_clear_range_profiles(IMSI_IMSI_A,       IMSI_IMSI_C)
        _force_clear_range_profiles(IMSI_ICCID_A,      IMSI_ICCID_C)
        _force_clear_range_profiles(IMSI_IAPN_A,       IMSI_IAPN_C)
        _force_clear_range_profiles(IMSI_ICAPN_A,      IMSI_ICAPN_C)
        _force_clear_range_profiles(F_IMSI_FC_IMSI_S1,  T_IMSI_FC_IMSI_S3)
        _force_clear_range_profiles(F_IMSI_FC_IAPN_S1,  T_IMSI_FC_IAPN_S3)
        _force_clear_range_profiles(F_IMSI_FC_ICCID_S1, T_IMSI_FC_ICCID_S3)
        _force_clear_range_profiles(F_IMSI_FC_ICAPN_S1, T_IMSI_FC_ICAPN_S3)

        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            # Delete ICCID range configs (cascades to imsi slots and APN-pool entries).
            for rc_id in filter(None, [
                cls.fc_imsi_rc_id, cls.fc_iapn_rc_id,
                cls.fc_iccid_rc_id, cls.fc_icapn_rc_id,
            ]):
                delete_iccid_range_config(c, rc_id)

            # Force-clear any remaining IP allocations before deleting pools so
            # DELETE /pools never silently fails with 409 and strands the subnet.
            for pool_id in cls.pool_ids.values():
                if pool_id:
                    _force_clear_pool_ips(pool_id)
                    resp = c.delete(f"/pools/{pool_id}")
                    assert resp.status_code in (204, 404), (
                        f"delete_pool({pool_id}) returned {resp.status_code}: {resp.text}"
                    )

    @pytest.fixture(autouse=True)
    def rc(self) -> RadiusClient:
        """Per-test RADIUS client."""
        return RadiusClient(RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET)

    # ════════════════════════════════════════════════════════════════════════════
    # SECTION A — imsi mode (APN-agnostic; each IMSI has its own IP)
    # ════════════════════════════════════════════════════════════════════════════

    def test_01_imsi_preconditions(self, lookup_http: httpx.Client):
        """imsi mode: all 3 IMSIs are pre-provisioned and resolvable via GET /lookup."""
        for imsi, expected_ip in [
            (IMSI_IMSI_A, IP_IMSI_A),
            (IMSI_IMSI_B, IP_IMSI_B),
            (IMSI_IMSI_C, IP_IMSI_C),
        ]:
            r = lookup_http.get("/lookup", params={"imsi": imsi, "apn": APN_SMF1,
                                                   "use_case_id": "0800"})
            assert r.status_code == 200, \
                f"Pre-condition: /lookup for {imsi} failed: {r.status_code} {r.text}"
            assert r.json()["static_ip"] == expected_ip, \
                f"Pre-condition: {imsi} expected {expected_ip}, got {r.json()['static_ip']!r}"

    def test_02_imsi_all_three_accept(self, rc: RadiusClient):
        """imsi mode: all 3 IMSIs → Access-Accept."""
        for imsi in [IMSI_IMSI_A, IMSI_IMSI_B, IMSI_IMSI_C]:
            resp = rc.authenticate(imsi, APN_SMF1)
            assert resp.is_accept, \
                f"imsi mode: expected Accept for {imsi}, got code={resp.code}"

    def test_03_imsi_framed_ip_per_imsi(self, rc: RadiusClient):
        """imsi mode: each IMSI returns its own distinct Framed-IP-Address."""
        for imsi, expected_ip in [
            (IMSI_IMSI_A, IP_IMSI_A),
            (IMSI_IMSI_B, IP_IMSI_B),
            (IMSI_IMSI_C, IP_IMSI_C),
        ]:
            resp = rc.authenticate(imsi, APN_SMF1)
            assert resp.is_accept
            assert resp.framed_ip == expected_ip, \
                f"{imsi}: Framed-IP={resp.framed_ip!r}, expected {expected_ip!r}"

    def test_04_imsi_apn_agnostic(self, rc: RadiusClient):
        """imsi mode: smf1 and smf2 both return the same IP for IMSI_IMSI_A.

        APN is completely ignored in imsi mode — only the IMSI determines the IP.
        """
        resp1 = rc.authenticate(IMSI_IMSI_A, APN_SMF1)
        resp2 = rc.authenticate(IMSI_IMSI_A, APN_SMF2)
        assert resp1.is_accept and resp2.is_accept
        assert resp1.framed_ip == IP_IMSI_A, \
            f"smf1: Framed-IP={resp1.framed_ip!r}, expected {IP_IMSI_A!r}"
        assert resp2.framed_ip == IP_IMSI_A, \
            f"smf2: Framed-IP={resp2.framed_ip!r}, expected {IP_IMSI_A!r} (APN must be ignored)"

    def test_05_imsi_suspend_sibling_accept(self, http: httpx.Client, rc: RadiusClient):
        """imsi mode: suspending IMSI_A rejects only IMSI_A; siblings B and C stay active."""
        r = http.patch(
            f"/profiles/{TestRadius3ImsiModes.imsi_sim_id}/imsis/{IMSI_IMSI_A}",
            json={"status": "suspended"},
        )
        assert r.status_code == 200, f"PATCH imsi suspend failed: {r.status_code} {r.text}"

        resp_a = rc.authenticate(IMSI_IMSI_A, APN_SMF1)
        assert resp_a.is_reject, \
            f"Expected Reject for suspended IMSI_IMSI_A, got code={resp_a.code}"

        for imsi, ip in [(IMSI_IMSI_B, IP_IMSI_B), (IMSI_IMSI_C, IP_IMSI_C)]:
            resp = rc.authenticate(imsi, APN_SMF1)
            assert resp.is_accept, \
                f"{imsi} (sibling of suspended A): expected Accept, got code={resp.code}"
            assert resp.framed_ip == ip

    def test_06_imsi_reactivate(self, http: httpx.Client, rc: RadiusClient):
        """imsi mode: reactivating IMSI_A restores Access-Accept."""
        r = http.patch(
            f"/profiles/{TestRadius3ImsiModes.imsi_sim_id}/imsis/{IMSI_IMSI_A}",
            json={"status": "active"},
        )
        assert r.status_code == 200, f"PATCH imsi reactivate failed: {r.status_code} {r.text}"

        resp = rc.authenticate(IMSI_IMSI_A, APN_SMF1)
        assert resp.is_accept, \
            f"Expected Accept after reactivation of IMSI_IMSI_A, got code={resp.code}"
        assert resp.framed_ip == IP_IMSI_A

    def test_07_imsi_fc_slot1_allocates(self, http: httpx.Client, rc: RadiusClient):
        """imsi mode FC: slot-1 IMSI first-connects, allocating its own IP.

        first_connection.py sibling loop also allocates DIFFERENT IPs from slot-2 and
        slot-3 pools in the same transaction.  This test only confirms slot-1 gets Accept.
        """
        resp = rc.authenticate(IMSI_FC_IMSI_S1, APN_SMF1,
                               imei="35812300000071", charging_chars="0800")
        assert resp.is_accept, \
            f"imsi FC slot-1: expected Accept, got code={resp.code}"
        assert resp.framed_ip is not None, \
            "imsi FC slot-1: Access-Accept must carry Framed-IP-Address"

        TestRadius3ImsiModes.ip_fc_imsi_s1 = resp.framed_ip

        r_profile = http.get("/profiles", params={"imsi": IMSI_FC_IMSI_S1})
        if r_profile.status_code == 200:
            data = r_profile.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            if profiles:
                TestRadius3ImsiModes.fc_imsi_sim_id = profiles[0]["sim_id"]

    def test_08_imsi_fc_slot2_pre_provisioned(self, rc: RadiusClient):
        """imsi mode FC: slot-2 IMSI was pre-provisioned by slot-1's transaction.

        The sibling loop allocated a fresh IP from the slot-2 pool — different from
        slot-1's IP.  IMSI_FC_IMSI_S2's RADIUS request must return that pre-allocated IP.
        """
        assert TestRadius3ImsiModes.ip_fc_imsi_s1 is not None, \
            "test_07 must run first (ip_fc_imsi_s1 not set)"

        resp = rc.authenticate(IMSI_FC_IMSI_S2, APN_SMF1)
        assert resp.is_accept, \
            f"imsi FC slot-2: expected Accept (pre-provisioned), got code={resp.code}"
        assert resp.framed_ip is not None
        assert resp.framed_ip != TestRadius3ImsiModes.ip_fc_imsi_s1, (
            f"imsi FC: slot-2 IP must differ from slot-1 IP "
            f"(each slot has its own pool). s1={TestRadius3ImsiModes.ip_fc_imsi_s1!r}, "
            f"s2={resp.framed_ip!r}"
        )

        TestRadius3ImsiModes.ip_fc_imsi_s2 = resp.framed_ip

    def test_09_imsi_fc_slot3_pre_provisioned(self, rc: RadiusClient):
        """imsi mode FC: slot-3 IMSI was pre-provisioned with a third distinct IP."""
        assert TestRadius3ImsiModes.ip_fc_imsi_s1 is not None, \
            "test_07 must run first"

        resp = rc.authenticate(IMSI_FC_IMSI_S3, APN_SMF1)
        assert resp.is_accept, \
            f"imsi FC slot-3: expected Accept (pre-provisioned), got code={resp.code}"
        assert resp.framed_ip is not None

        s1 = TestRadius3ImsiModes.ip_fc_imsi_s1
        s2 = TestRadius3ImsiModes.ip_fc_imsi_s2
        assert resp.framed_ip != s1, f"slot-3 IP must differ from slot-1 IP: {s1!r}"
        if s2 is not None:
            assert resp.framed_ip != s2, f"slot-3 IP must differ from slot-2 IP: {s2!r}"

        TestRadius3ImsiModes.ip_fc_imsi_s3 = resp.framed_ip

    def test_10_imsi_fc_idempotent(self, rc: RadiusClient):
        """imsi mode FC: second RADIUS request for slot-1 returns the same IP (idempotent)."""
        assert TestRadius3ImsiModes.ip_fc_imsi_s1 is not None, \
            "test_07 must run first"

        resp = rc.authenticate(IMSI_FC_IMSI_S1, APN_SMF1)
        assert resp.is_accept
        assert resp.framed_ip == TestRadius3ImsiModes.ip_fc_imsi_s1, (
            f"imsi FC idempotent: expected same IP {TestRadius3ImsiModes.ip_fc_imsi_s1!r}, "
            f"got {resp.framed_ip!r}"
        )

    def test_11_out_of_range_reject(self, rc: RadiusClient):
        """Out-of-range IMSI (module-99) → Access-Reject; no Framed-IP-Address.

        IMSI_OOB has no range config and no profile in the system.
        aaa-radius-server must translate the 404 not_found into Access-Reject (code=3).
        """
        resp = rc.authenticate(IMSI_OOB, APN_SMF1)
        assert resp.is_reject, \
            f"Expected Access-Reject for out-of-range IMSI, got code={resp.code}"
        assert resp.framed_ip is None, \
            "Access-Reject must not contain Framed-IP-Address"

    # ════════════════════════════════════════════════════════════════════════════
    # SECTION B — iccid mode (card-level shared IP for all 3 IMSIs)
    # ════════════════════════════════════════════════════════════════════════════

    def test_12_iccid_all_three_accept(self, rc: RadiusClient):
        """iccid mode: all 3 IMSIs on the same card → Access-Accept."""
        for imsi in [IMSI_ICCID_A, IMSI_ICCID_B, IMSI_ICCID_C]:
            resp = rc.authenticate(imsi, APN_SMF1)
            assert resp.is_accept, \
                f"iccid mode: expected Accept for {imsi}, got code={resp.code}"

    def test_13_iccid_shared_card_ip(self, rc: RadiusClient):
        """iccid mode: all 3 IMSIs return the same card-level Framed-IP-Address."""
        for imsi in [IMSI_ICCID_A, IMSI_ICCID_B, IMSI_ICCID_C]:
            resp = rc.authenticate(imsi, APN_SMF1)
            assert resp.is_accept
            assert resp.framed_ip == IP_ICCID_CARD, \
                f"{imsi}: Framed-IP={resp.framed_ip!r}, expected card IP {IP_ICCID_CARD!r}"

    def test_14_iccid_apn_ignored(self, rc: RadiusClient):
        """iccid mode: APN is irrelevant — smf1, smf2, and a garbage APN all return card IP."""
        for apn in [APN_SMF1, APN_SMF2, APN_GARBAGE]:
            resp = rc.authenticate(IMSI_ICCID_A, apn)
            assert resp.is_accept, \
                f"iccid mode must ignore APN={apn!r}; expected Accept, got code={resp.code}"
            assert resp.framed_ip == IP_ICCID_CARD, \
                f"APN={apn!r}: Framed-IP={resp.framed_ip!r}, expected {IP_ICCID_CARD!r}"

    def test_15_iccid_suspend_sibling_accept(self, http: httpx.Client, rc: RadiusClient):
        """iccid mode: suspending IMSI_ICCID_A rejects only IMSI_A; siblings B and C stay active."""
        r = http.patch(
            f"/profiles/{TestRadius3ImsiModes.iccid_sim_id}/imsis/{IMSI_ICCID_A}",
            json={"status": "suspended"},
        )
        assert r.status_code == 200, f"PATCH iccid imsi suspend failed: {r.status_code} {r.text}"

        resp_a = rc.authenticate(IMSI_ICCID_A, APN_SMF1)
        assert resp_a.is_reject, \
            f"Expected Reject for suspended IMSI_ICCID_A, got code={resp_a.code}"

        for imsi in [IMSI_ICCID_B, IMSI_ICCID_C]:
            resp = rc.authenticate(imsi, APN_SMF1)
            assert resp.is_accept, \
                f"{imsi} (sibling of suspended A): expected Accept, got code={resp.code}"
            assert resp.framed_ip == IP_ICCID_CARD

    def test_16_iccid_reactivate(self, http: httpx.Client, rc: RadiusClient):
        """iccid mode: reactivating IMSI_ICCID_A restores Access-Accept."""
        r = http.patch(
            f"/profiles/{TestRadius3ImsiModes.iccid_sim_id}/imsis/{IMSI_ICCID_A}",
            json={"status": "active"},
        )
        assert r.status_code == 200, f"PATCH iccid imsi reactivate failed: {r.status_code} {r.text}"

        resp = rc.authenticate(IMSI_ICCID_A, APN_SMF1)
        assert resp.is_accept, \
            f"Expected Accept after reactivation of IMSI_ICCID_A, got code={resp.code}"
        assert resp.framed_ip == IP_ICCID_CARD

    def test_17_iccid_fc_slot1_allocates_card_ip(
            self, http: httpx.Client, rc: RadiusClient):
        """iccid mode FC: slot-1 first-connects and allocates one card-level IP.

        first_connection.py sibling loop pre-provisions slots 2 and 3 with the SAME
        card IP in the same transaction (one sim_apn_ips row shared by all slots).
        """
        resp = rc.authenticate(IMSI_FC_ICCID_S1, APN_SMF1,
                               imei="35812300000170", charging_chars="0800")
        assert resp.is_accept, \
            f"iccid FC slot-1: expected Accept, got code={resp.code}"
        assert resp.framed_ip is not None

        TestRadius3ImsiModes.ip_fc_iccid_card = resp.framed_ip

        r_profile = http.get("/profiles", params={"imsi": IMSI_FC_ICCID_S1})
        if r_profile.status_code == 200:
            data = r_profile.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            if profiles:
                TestRadius3ImsiModes.fc_iccid_sim_id = profiles[0]["sim_id"]

    def test_18_iccid_fc_slot2_same_card_ip(self, rc: RadiusClient):
        """iccid mode FC: slot-2 returns the SAME card IP as slot-1 (pre-provisioned).

        In iccid mode the card-level IP is shared by all slots — a single sim_apn_ips row
        (keyed on sim_id, apn=NULL) is written atomically when slot-1 first-connects.
        """
        assert TestRadius3ImsiModes.ip_fc_iccid_card is not None, \
            "test_17 must run first (ip_fc_iccid_card not set)"

        resp = rc.authenticate(IMSI_FC_ICCID_S2, APN_SMF1)
        assert resp.is_accept, \
            f"iccid FC slot-2: expected Accept, got code={resp.code}"
        assert resp.framed_ip == TestRadius3ImsiModes.ip_fc_iccid_card, (
            f"iccid FC: slot-2 must return the same card IP as slot-1. "
            f"card_ip={TestRadius3ImsiModes.ip_fc_iccid_card!r}, s2={resp.framed_ip!r}"
        )

    def test_19_iccid_fc_slot3_same_card_ip(self, rc: RadiusClient):
        """iccid mode FC: slot-3 also returns the same shared card IP."""
        assert TestRadius3ImsiModes.ip_fc_iccid_card is not None, \
            "test_17 must run first"

        resp = rc.authenticate(IMSI_FC_ICCID_S3, APN_SMF1)
        assert resp.is_accept, \
            f"iccid FC slot-3: expected Accept, got code={resp.code}"
        assert resp.framed_ip == TestRadius3ImsiModes.ip_fc_iccid_card, (
            f"iccid FC: slot-3 must return same card IP. "
            f"card_ip={TestRadius3ImsiModes.ip_fc_iccid_card!r}, s3={resp.framed_ip!r}"
        )

    # ════════════════════════════════════════════════════════════════════════════
    # SECTION C — imsi_apn mode (per-IMSI per-APN; 3 IMSIs × smf1 + smf2)
    # ════════════════════════════════════════════════════════════════════════════

    def test_20_iapn_smf1_all_imsis(self, rc: RadiusClient):
        """imsi_apn mode: each IMSI returns its own smf1 IP."""
        for imsi, expected_ip in [
            (IMSI_IAPN_A, IP_IAPN_A_SMF1),
            (IMSI_IAPN_B, IP_IAPN_B_SMF1),
            (IMSI_IAPN_C, IP_IAPN_C_SMF1),
        ]:
            resp = rc.authenticate(imsi, APN_SMF1)
            assert resp.is_accept, \
                f"imsi_apn smf1: expected Accept for {imsi}, got code={resp.code}"
            assert resp.framed_ip == expected_ip, \
                f"{imsi}/smf1: Framed-IP={resp.framed_ip!r}, expected {expected_ip!r}"

    def test_21_iapn_smf2_all_imsis(self, rc: RadiusClient):
        """imsi_apn mode: each IMSI returns its own smf2 IP (different from smf1)."""
        for imsi, expected_ip in [
            (IMSI_IAPN_A, IP_IAPN_A_SMF2),
            (IMSI_IAPN_B, IP_IAPN_B_SMF2),
            (IMSI_IAPN_C, IP_IAPN_C_SMF2),
        ]:
            resp = rc.authenticate(imsi, APN_SMF2)
            assert resp.is_accept, \
                f"imsi_apn smf2: expected Accept for {imsi}, got code={resp.code}"
            assert resp.framed_ip == expected_ip, \
                f"{imsi}/smf2: Framed-IP={resp.framed_ip!r}, expected {expected_ip!r}"

    def test_22_iapn_per_imsi_per_apn_distinct(self, rc: RadiusClient):
        """imsi_apn mode: all 6 IMSI×APN combinations return 6 distinct IPs."""
        results = {}
        for imsi in [IMSI_IAPN_A, IMSI_IAPN_B, IMSI_IAPN_C]:
            for apn in [APN_SMF1, APN_SMF2]:
                resp = rc.authenticate(imsi, apn)
                assert resp.is_accept
                results[(imsi, apn)] = resp.framed_ip

        ips = list(results.values())
        assert len(ips) == len(set(ips)), (
            f"imsi_apn: all 6 IMSI×APN IPs must be unique. Got: {results}"
        )

    def test_23_iapn_unknown_apn_reject(self, rc: RadiusClient):
        """imsi_apn mode: unknown APN → Access-Reject for all 3 IMSIs."""
        for imsi in [IMSI_IAPN_A, IMSI_IAPN_B, IMSI_IAPN_C]:
            resp = rc.authenticate(imsi, APN_GARBAGE)
            assert resp.is_reject, (
                f"imsi_apn mode: {imsi}/garbage APN must → Reject, got code={resp.code}. "
                "lookup returns 404 apn_not_found → aaa-radius-server must emit Reject."
            )

    def test_24_iapn_suspend_per_imsi(self, http: httpx.Client, rc: RadiusClient):
        """imsi_apn mode: suspending IMSI_IAPN_A rejects both smf1 and smf2 for IMSI_A only."""
        r = http.patch(
            f"/profiles/{TestRadius3ImsiModes.iapn_sim_id}/imsis/{IMSI_IAPN_A}",
            json={"status": "suspended"},
        )
        assert r.status_code == 200, f"PATCH iapn imsi suspend failed: {r.status_code} {r.text}"

        for apn in [APN_SMF1, APN_SMF2]:
            resp = rc.authenticate(IMSI_IAPN_A, apn)
            assert resp.is_reject, \
                f"imsi_apn: suspended A/{apn}: expected Reject, got code={resp.code}"

        resp_b = rc.authenticate(IMSI_IAPN_B, APN_SMF1)
        assert resp_b.is_accept, \
            f"imsi_apn: sibling B still active — expected Accept, got code={resp_b.code}"
        assert resp_b.framed_ip == IP_IAPN_B_SMF1

        resp_c = rc.authenticate(IMSI_IAPN_C, APN_SMF2)
        assert resp_c.is_accept, \
            f"imsi_apn: sibling C still active — expected Accept, got code={resp_c.code}"
        assert resp_c.framed_ip == IP_IAPN_C_SMF2

    def test_25_iapn_reactivate(self, http: httpx.Client, rc: RadiusClient):
        """imsi_apn mode: reactivating IMSI_IAPN_A restores both smf1 and smf2."""
        r = http.patch(
            f"/profiles/{TestRadius3ImsiModes.iapn_sim_id}/imsis/{IMSI_IAPN_A}",
            json={"status": "active"},
        )
        assert r.status_code == 200, f"PATCH iapn imsi reactivate failed: {r.status_code} {r.text}"

        for apn, expected_ip in [
            (APN_SMF1, IP_IAPN_A_SMF1),
            (APN_SMF2, IP_IAPN_A_SMF2),
        ]:
            resp = rc.authenticate(IMSI_IAPN_A, apn)
            assert resp.is_accept, \
                f"imsi_apn: after reactivation, A/{apn} expected Accept, got code={resp.code}"
            assert resp.framed_ip == expected_ip

    def test_26_iapn_fc_slot1_smf1(self, http: httpx.Client, rc: RadiusClient):
        """imsi_apn FC: slot-1 IMSI first-connects with smf1; ALL APNs for ALL slots allocated.

        first_connection.py allocates smf1 and smf2 for slot-1, then the sibling loop
        allocates smf1 and smf2 for slots 2 and 3 from their respective pools —
        all 6 IPs provisioned atomically.
        """
        resp = rc.authenticate(IMSI_FC_IAPN_S1, APN_SMF1,
                               imei="35812300000261", charging_chars="0800")
        assert resp.is_accept, \
            f"imsi_apn FC slot-1/smf1: expected Accept, got code={resp.code}"
        assert resp.framed_ip is not None

        TestRadius3ImsiModes.ip_fc_iapn_s1_smf1 = resp.framed_ip

        r_profile = http.get("/profiles", params={"imsi": IMSI_FC_IAPN_S1})
        if r_profile.status_code == 200:
            data = r_profile.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            if profiles:
                TestRadius3ImsiModes.fc_iapn_sim_id = profiles[0]["sim_id"]

    def test_27_iapn_fc_slot1_smf2_pre_allocated(self, rc: RadiusClient):
        """imsi_apn FC: slot-1 smf2 was pre-allocated in the same FC transaction → Accept."""
        assert TestRadius3ImsiModes.ip_fc_iapn_s1_smf1 is not None, \
            "test_26 must run first"

        resp = rc.authenticate(IMSI_FC_IAPN_S1, APN_SMF2)
        assert resp.is_accept, \
            f"imsi_apn FC slot-1/smf2: expected Accept (pre-allocated), got code={resp.code}"
        assert resp.framed_ip is not None
        assert resp.framed_ip != TestRadius3ImsiModes.ip_fc_iapn_s1_smf1, \
            "smf2 IP must differ from smf1 IP (different pools)"

        TestRadius3ImsiModes.ip_fc_iapn_s1_smf2 = resp.framed_ip

    def test_28_iapn_fc_slot2_pre_provisioned(self, rc: RadiusClient):
        """imsi_apn FC: slot-2 was pre-provisioned with its own per-APN IPs."""
        assert TestRadius3ImsiModes.ip_fc_iapn_s1_smf1 is not None, \
            "test_26 must run first"

        resp_smf1 = rc.authenticate(IMSI_FC_IAPN_S2, APN_SMF1)
        assert resp_smf1.is_accept, \
            f"imsi_apn FC slot-2/smf1: expected Accept, got code={resp_smf1.code}"
        assert resp_smf1.framed_ip is not None
        assert resp_smf1.framed_ip != TestRadius3ImsiModes.ip_fc_iapn_s1_smf1, (
            f"slot-2 smf1 IP must differ from slot-1 smf1 IP (each slot has its own pool). "
            f"s1_smf1={TestRadius3ImsiModes.ip_fc_iapn_s1_smf1!r}, s2_smf1={resp_smf1.framed_ip!r}"
        )

        TestRadius3ImsiModes.ip_fc_iapn_s2_smf1 = resp_smf1.framed_ip

    def test_29_iapn_fc_slot3_pre_provisioned(self, rc: RadiusClient):
        """imsi_apn FC: slot-3 was pre-provisioned; all 6 per-slot per-APN IPs are unique."""
        assert TestRadius3ImsiModes.ip_fc_iapn_s1_smf1 is not None, \
            "test_26 must run first"

        resp_smf2 = rc.authenticate(IMSI_FC_IAPN_S3, APN_SMF2)
        assert resp_smf2.is_accept, \
            f"imsi_apn FC slot-3/smf2: expected Accept, got code={resp_smf2.code}"
        assert resp_smf2.framed_ip is not None

        TestRadius3ImsiModes.ip_fc_iapn_s3_smf2 = resp_smf2.framed_ip

        # Collect all known slot IPs and assert they're all distinct
        known_ips = [ip for ip in [
            TestRadius3ImsiModes.ip_fc_iapn_s1_smf1,
            TestRadius3ImsiModes.ip_fc_iapn_s1_smf2,
            TestRadius3ImsiModes.ip_fc_iapn_s2_smf1,
            resp_smf2.framed_ip,
        ] if ip is not None]
        assert len(known_ips) == len(set(known_ips)), \
            f"imsi_apn FC: all collected per-slot per-APN IPs must be unique. Got: {known_ips}"

    def test_30_iapn_fc_idempotent(self, rc: RadiusClient):
        """imsi_apn FC: re-authenticating slot-1/smf1 returns the same IP (idempotent)."""
        assert TestRadius3ImsiModes.ip_fc_iapn_s1_smf1 is not None, \
            "test_26 must run first"

        resp = rc.authenticate(IMSI_FC_IAPN_S1, APN_SMF1)
        assert resp.is_accept
        assert resp.framed_ip == TestRadius3ImsiModes.ip_fc_iapn_s1_smf1, (
            f"imsi_apn FC idempotent: expected same smf1 IP "
            f"{TestRadius3ImsiModes.ip_fc_iapn_s1_smf1!r}, got {resp.framed_ip!r}"
        )

    # ════════════════════════════════════════════════════════════════════════════
    # SECTION D — iccid_apn mode (card-level per-APN; 3 IMSIs × smf1 + smf2)
    # ════════════════════════════════════════════════════════════════════════════

    def test_31_icapn_smf1_all_imsis(self, rc: RadiusClient):
        """iccid_apn mode: all 3 IMSIs return the same card-level smf1 IP."""
        for imsi in [IMSI_ICAPN_A, IMSI_ICAPN_B, IMSI_ICAPN_C]:
            resp = rc.authenticate(imsi, APN_SMF1)
            assert resp.is_accept, \
                f"iccid_apn smf1: expected Accept for {imsi}, got code={resp.code}"
            assert resp.framed_ip == IP_ICAPN_SMF1, \
                f"{imsi}/smf1: Framed-IP={resp.framed_ip!r}, expected card smf1 IP {IP_ICAPN_SMF1!r}"

    def test_32_icapn_smf2_all_imsis(self, rc: RadiusClient):
        """iccid_apn mode: all 3 IMSIs return the same card-level smf2 IP."""
        for imsi in [IMSI_ICAPN_A, IMSI_ICAPN_B, IMSI_ICAPN_C]:
            resp = rc.authenticate(imsi, APN_SMF2)
            assert resp.is_accept, \
                f"iccid_apn smf2: expected Accept for {imsi}, got code={resp.code}"
            assert resp.framed_ip == IP_ICAPN_SMF2, \
                f"{imsi}/smf2: Framed-IP={resp.framed_ip!r}, expected card smf2 IP {IP_ICAPN_SMF2!r}"

    def test_33_icapn_different_apn_different_ip(self, rc: RadiusClient):
        """iccid_apn mode: smf1 and smf2 return different card-level IPs."""
        resp_smf1 = rc.authenticate(IMSI_ICAPN_A, APN_SMF1)
        resp_smf2 = rc.authenticate(IMSI_ICAPN_A, APN_SMF2)
        assert resp_smf1.is_accept and resp_smf2.is_accept
        assert resp_smf1.framed_ip != resp_smf2.framed_ip, \
            f"smf1 and smf2 must return different IPs: smf1={resp_smf1.framed_ip!r}, smf2={resp_smf2.framed_ip!r}"

    def test_34_icapn_unknown_apn_reject(self, rc: RadiusClient):
        """iccid_apn mode: unknown APN → Access-Reject for all 3 IMSIs."""
        for imsi in [IMSI_ICAPN_A, IMSI_ICAPN_B, IMSI_ICAPN_C]:
            resp = rc.authenticate(imsi, APN_GARBAGE)
            assert resp.is_reject, (
                f"iccid_apn mode: {imsi}/garbage APN must → Reject, got code={resp.code}. "
                "lookup returns 404 apn_not_found → aaa-radius-server must emit Reject."
            )

    def test_35_icapn_suspend_sibling_accept(self, http: httpx.Client, rc: RadiusClient):
        """iccid_apn mode: suspending IMSI_ICAPN_A rejects A; siblings B and C stay active."""
        r = http.patch(
            f"/profiles/{TestRadius3ImsiModes.icapn_sim_id}/imsis/{IMSI_ICAPN_A}",
            json={"status": "suspended"},
        )
        assert r.status_code == 200, f"PATCH icapn imsi suspend failed: {r.status_code} {r.text}"

        for apn in [APN_SMF1, APN_SMF2]:
            resp = rc.authenticate(IMSI_ICAPN_A, apn)
            assert resp.is_reject, \
                f"iccid_apn: suspended A/{apn}: expected Reject, got code={resp.code}"

        resp_b = rc.authenticate(IMSI_ICAPN_B, APN_SMF1)
        assert resp_b.is_accept, \
            f"iccid_apn: sibling B/smf1 expected Accept, got code={resp_b.code}"
        assert resp_b.framed_ip == IP_ICAPN_SMF1

        resp_c = rc.authenticate(IMSI_ICAPN_C, APN_SMF2)
        assert resp_c.is_accept, \
            f"iccid_apn: sibling C/smf2 expected Accept, got code={resp_c.code}"
        assert resp_c.framed_ip == IP_ICAPN_SMF2

    def test_36_icapn_reactivate(self, http: httpx.Client, rc: RadiusClient):
        """iccid_apn mode: reactivating IMSI_ICAPN_A restores both smf1 and smf2."""
        r = http.patch(
            f"/profiles/{TestRadius3ImsiModes.icapn_sim_id}/imsis/{IMSI_ICAPN_A}",
            json={"status": "active"},
        )
        assert r.status_code == 200, \
            f"PATCH icapn imsi reactivate failed: {r.status_code} {r.text}"

        for apn, expected_ip in [(APN_SMF1, IP_ICAPN_SMF1), (APN_SMF2, IP_ICAPN_SMF2)]:
            resp = rc.authenticate(IMSI_ICAPN_A, apn)
            assert resp.is_accept, \
                f"iccid_apn: after reactivation, A/{apn} expected Accept, got code={resp.code}"
            assert resp.framed_ip == expected_ip

    def test_37_icapn_fc_slot1_allocates_card_ips(
            self, http: httpx.Client, rc: RadiusClient):
        """iccid_apn FC: slot-1 IMSI first-connects; both smf1 and smf2 card-level IPs allocated.

        first_connection.py allocates smf1 and smf2 IPs for the card in one transaction.
        The sibling loop pre-provisions slots 2 and 3 but they share the SAME card-level
        IPs (one sim_apn_ips row per APN per card, keyed on sim_id+APN, not per-slot).
        """
        resp_smf1 = rc.authenticate(IMSI_FC_ICAPN_S1, APN_SMF1,
                                    imei="35812300000371", charging_chars="0800")
        assert resp_smf1.is_accept, \
            f"iccid_apn FC slot-1/smf1: expected Accept, got code={resp_smf1.code}"
        assert resp_smf1.framed_ip is not None

        TestRadius3ImsiModes.ip_fc_icapn_smf1 = resp_smf1.framed_ip

        resp_smf2 = rc.authenticate(IMSI_FC_ICAPN_S1, APN_SMF2)
        assert resp_smf2.is_accept, \
            f"iccid_apn FC slot-1/smf2: expected Accept, got code={resp_smf2.code}"
        assert resp_smf2.framed_ip is not None
        assert resp_smf2.framed_ip != resp_smf1.framed_ip, \
            "smf1 and smf2 card IPs must be distinct"

        TestRadius3ImsiModes.ip_fc_icapn_smf2 = resp_smf2.framed_ip

        r_profile = http.get("/profiles", params={"imsi": IMSI_FC_ICAPN_S1})
        if r_profile.status_code == 200:
            data = r_profile.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            if profiles:
                TestRadius3ImsiModes.fc_icapn_sim_id = profiles[0]["sim_id"]

    def test_38_icapn_fc_slot2_same_card_ips(self, rc: RadiusClient):
        """iccid_apn FC: slot-2 returns the SAME card-level smf1 and smf2 IPs as slot-1."""
        assert TestRadius3ImsiModes.ip_fc_icapn_smf1 is not None, \
            "test_37 must run first"

        resp_smf1 = rc.authenticate(IMSI_FC_ICAPN_S2, APN_SMF1)
        assert resp_smf1.is_accept, \
            f"iccid_apn FC slot-2/smf1: expected Accept, got code={resp_smf1.code}"
        assert resp_smf1.framed_ip == TestRadius3ImsiModes.ip_fc_icapn_smf1, (
            f"iccid_apn FC: slot-2 smf1 must equal card smf1 IP. "
            f"card={TestRadius3ImsiModes.ip_fc_icapn_smf1!r}, s2={resp_smf1.framed_ip!r}"
        )

        resp_smf2 = rc.authenticate(IMSI_FC_ICAPN_S2, APN_SMF2)
        assert resp_smf2.is_accept, \
            f"iccid_apn FC slot-2/smf2: expected Accept, got code={resp_smf2.code}"
        assert resp_smf2.framed_ip == TestRadius3ImsiModes.ip_fc_icapn_smf2, (
            f"iccid_apn FC: slot-2 smf2 must equal card smf2 IP. "
            f"card={TestRadius3ImsiModes.ip_fc_icapn_smf2!r}, s2={resp_smf2.framed_ip!r}"
        )

    def test_39_icapn_fc_slot3_same_card_ips(self, rc: RadiusClient):
        """iccid_apn FC: slot-3 also returns the same shared card-level APN IPs."""
        assert TestRadius3ImsiModes.ip_fc_icapn_smf1 is not None, \
            "test_37 must run first"

        resp_smf1 = rc.authenticate(IMSI_FC_ICAPN_S3, APN_SMF1)
        assert resp_smf1.is_accept
        assert resp_smf1.framed_ip == TestRadius3ImsiModes.ip_fc_icapn_smf1

        resp_smf2 = rc.authenticate(IMSI_FC_ICAPN_S3, APN_SMF2)
        assert resp_smf2.is_accept
        assert resp_smf2.framed_ip == TestRadius3ImsiModes.ip_fc_icapn_smf2

    # ════════════════════════════════════════════════════════════════════════════
    # SECTION E — RFC 2865 compliance
    # ════════════════════════════════════════════════════════════════════════════

    def test_40_response_authenticator_valid(self):
        """RFC 2865 §3: ResponseAuth = MD5(Code | ID | Length | RequestAuth | Attrs | Secret).

        Sends a raw Access-Request and verifies the response authenticator using
        verify_response_auth() rather than relying on parse_response() to accept it.
        """
        pkt_id = 42
        packet, req_auth = build_access_request(pkt_id, IMSI_IMSI_A, APN_SMF1)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(10.0)
            sock.sendto(packet, (RADIUS_HOST, RADIUS_PORT))
            raw, _ = sock.recvfrom(4096)

        assert verify_response_auth(raw, req_auth, RADIUS_SECRET), (
            "Response authenticator mismatch — aaa-radius-server is using the wrong "
            "shared secret or has a bug in its ResponseAuth computation (RFC 2865 §3)."
        )

    def test_41_reject_has_no_framed_ip(self, rc: RadiusClient):
        """RFC 2865: Access-Reject MUST NOT contain Framed-IP-Address (attr 8).

        An out-of-range IMSI produces a Reject response; Framed-IP-Address must
        be absent from that response.
        """
        resp = rc.authenticate(IMSI_OOB, APN_SMF1)
        assert resp.is_reject, \
            f"Expected Access-Reject for OOB IMSI, got code={resp.code}"
        assert resp.framed_ip is None, (
            f"RFC 2865: Framed-IP-Address MUST NOT appear in Access-Reject. "
            f"Got framed_ip={resp.framed_ip!r}"
        )
