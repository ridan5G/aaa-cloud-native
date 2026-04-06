"""
test_21_imsi_only_first_connect.py — first_connect provisioning for IMSI-only (no ICCID) configs.

Verifies that iccid_range_configs created without f_iccid/t_iccid
(provisioning_mode="first_connect") correctly allocate IPs via POST /first-connection:
  - sim_profile created with iccid=NULL on the first SIM connect
  - Sibling slots are pre-provisioned in the same transaction (thundering-herd prevention)
  - Idempotency: second POST /first-connection returns 200 + same IP
  - All 4 ip_resolution types: imsi, imsi_apn, iccid, iccid_apn

This test file exercises the fix for a latent crash in first_connection.py where the
multi-IMSI path attempted to compute len(f_iccid) on an empty string, crashing with a
ValueError for any IMSI-only first_connect config.

Four test groups (A–D):
  A — ip_resolution="imsi"     : 2 slots, 3 cards — per-IMSI IP allocation
  B — ip_resolution="imsi_apn" : 2 slots, 2 APNs/slot — per-IMSI per-APN IP
  C — ip_resolution="iccid"    : 2 slots — card-level shared IP (iccid=NULL)
  D — ip_resolution="iccid_apn": 2 slots, 2 APNs on slot 1 — card-level per-APN IP

Resources
─────────
  Module 21 → IMSI prefix 27877 21 xxxxxxxx

  Subnets:
    A  — 100.65.240.0/24   (6 IPs needed: 2 slots × 3 cards)
    B  — 100.65.241.0/24   (internet APN pool)
         100.65.242.0/24   (IMS APN pool)
    C  — 100.65.243.0/24   (3 IPs needed: 1 per card)
    D  — 100.65.244.0/24   (internet APN pool)
         100.65.245.0/24   (IMS APN pool)

  IMSI ranges (3-card groups, 2 slots):
    A: S1=278772101000000–278772101000002  S2=278772102000000–278772102000002
    B: S1=278772101010000–278772101010002  S2=278772102010000–278772102010002
    C: S1=278772101020000–278772101020002  S2=278772102020000–278772102020002
    D: S1=278772101030000–278772101030002  S2=278772102030000–278772102030002
"""
import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID, make_imsi
from fixtures.pools import create_pool, delete_pool, get_pool_stats, _force_clear_range_profiles
from fixtures.range_configs import (
    create_iccid_range_config,
    add_imsi_slot,
    add_imsi_slot_apn_pool,
    delete_iccid_range_config,
)

MODULE = 21
CARDS  = 3

APN_INTERNET = "internet.operator.com"
APN_IMS      = "ims.operator.com"

# ── Subnets ───────────────────────────────────────────────────────────────────
SUBNET_A      = "100.65.240.0/24"
SUBNET_B_INET = "100.65.241.0/24"
SUBNET_B_IMS  = "100.65.242.0/24"
SUBNET_C      = "100.65.243.0/24"
SUBNET_D_INET = "100.65.244.0/24"
SUBNET_D_IMS  = "100.65.245.0/24"

# ── IMSI ranges (3-card groups, 2 slots) ─────────────────────────────────────
# Class A — imsi resolution
F_A_S1 = make_imsi(MODULE, 1_000_000);  T_A_S1 = make_imsi(MODULE, 1_000_002)
F_A_S2 = make_imsi(MODULE, 2_000_000);  T_A_S2 = make_imsi(MODULE, 2_000_002)

# Class B — imsi_apn resolution
F_B_S1 = make_imsi(MODULE, 1_010_000);  T_B_S1 = make_imsi(MODULE, 1_010_002)
F_B_S2 = make_imsi(MODULE, 2_010_000);  T_B_S2 = make_imsi(MODULE, 2_010_002)

# Class C — iccid resolution
F_C_S1 = make_imsi(MODULE, 1_020_000);  T_C_S1 = make_imsi(MODULE, 1_020_002)
F_C_S2 = make_imsi(MODULE, 2_020_000);  T_C_S2 = make_imsi(MODULE, 2_020_002)

# Class D — iccid_apn resolution
F_D_S1 = make_imsi(MODULE, 1_030_000);  T_D_S1 = make_imsi(MODULE, 1_030_002)
F_D_S2 = make_imsi(MODULE, 2_030_000);  T_D_S2 = make_imsi(MODULE, 2_030_002)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=30.0,
    )


def _first_connect(http: httpx.Client, imsi: str, apn: str = APN_INTERNET) -> httpx.Response:
    """POST /first-connection and return the raw response."""
    return http.post(
        "/first-connection",
        json={"imsi": imsi, "apn": apn, "use_case_id": USE_CASE_ID},
    )


def _imsi_at(f_imsi: str, offset: int) -> str:
    """Return the IMSI at the given card offset within a slot range."""
    return str(int(f_imsi) + offset).zfill(15)


# ══════════════════════════════════════════════════════════════════════════════
# Class A — ip_resolution="imsi"
# Per-IMSI IP allocation.  Each slot IMSI on the same card gets its own IP.
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.order(2100)
class TestFirstConnectIMSIOnly_IMSI:
    pool_id: str | None = None
    range_id: int | None = None
    sim_id_card0: str | None = None
    ip_s1_card0: str | None = None

    def test_01_setup(self):
        http = _new_client()
        _force_clear_range_profiles(F_A_S1, T_A_S1)
        _force_clear_range_profiles(F_A_S2, T_A_S2)
        pool = create_pool(http, subnet=SUBNET_A, pool_name="test-21-A",
                           replace_on_conflict=True)
        TestFirstConnectIMSIOnly_IMSI.pool_id = pool["pool_id"]
        rc = create_iccid_range_config(
            http,
            ip_resolution="imsi",
            pool_id=TestFirstConnectIMSIOnly_IMSI.pool_id,
            imsi_count=2,
            provisioning_mode="first_connect",
        )
        TestFirstConnectIMSIOnly_IMSI.range_id = rc["id"]
        add_imsi_slot(http, iccid_range_id=rc["id"],
                      f_imsi=F_A_S1, t_imsi=T_A_S1, imsi_slot=1, ip_resolution="imsi")
        add_imsi_slot(http, iccid_range_id=rc["id"],
                      f_imsi=F_A_S2, t_imsi=T_A_S2, imsi_slot=2, ip_resolution="imsi")

    def test_02_first_connect_slot1_card0(self):
        """Slot-1 IMSI for card 0 connects → 201 Created with IP allocated."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_A_S1)
        assert resp.status_code == 201, (
            f"expected 201 from /first-connection, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("sim_id"), f"missing sim_id in response: {body}"
        assert body.get("static_ip"), f"missing static_ip in response: {body}"
        TestFirstConnectIMSIOnly_IMSI.sim_id_card0 = body["sim_id"]
        TestFirstConnectIMSIOnly_IMSI.ip_s1_card0 = body["static_ip"]

    def test_03_slot2_card0_preprovisioned(self):
        """Slot-2 IMSI for card 0 was pre-provisioned by the sibling loop → 200 Idempotent."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_A_S2)  # slot-2, card offset 0
        assert resp.status_code == 200, (
            f"slot-2 should be pre-provisioned (200), got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["sim_id"] == TestFirstConnectIMSIOnly_IMSI.sim_id_card0, (
            f"sibling has different sim_id: expected {TestFirstConnectIMSIOnly_IMSI.sim_id_card0}, "
            f"got {body['sim_id']}"
        )
        # imsi mode: each IMSI has its own IP — slot-2 IP must differ from slot-1 IP
        assert body.get("static_ip"), f"slot-2 has no IP in response: {body}"
        assert body["static_ip"] != TestFirstConnectIMSIOnly_IMSI.ip_s1_card0, (
            "imsi mode: slot-2 and slot-1 must have different IPs on the same card"
        )

    def test_04_slot1_card0_idempotent(self):
        """Second /first-connection for slot-1 card-0 → 200, same sim_id and IP."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_A_S1)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["sim_id"] == TestFirstConnectIMSIOnly_IMSI.sim_id_card0
        assert body["static_ip"] == TestFirstConnectIMSIOnly_IMSI.ip_s1_card0

    def test_05_second_card_creates_new_profile(self):
        """Card 1 (offset 1) gets a fresh sim_id and new IPs for both slots."""
        http = _new_client()
        resp = _first_connect(http, imsi=_imsi_at(F_A_S1, 1))
        assert resp.status_code == 201, f"expected 201 for new card, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["sim_id"] != TestFirstConnectIMSIOnly_IMSI.sim_id_card0, (
            "card-1 must have a different sim_id from card-0"
        )
        assert body["static_ip"] != TestFirstConnectIMSIOnly_IMSI.ip_s1_card0, (
            "card-1 slot-1 must have a different IP from card-0 slot-1"
        )
        # Verify slot-2 of card-1 was also pre-provisioned
        resp2 = _first_connect(http, imsi=_imsi_at(F_A_S2, 1))
        assert resp2.status_code == 200, (
            f"slot-2 card-1 should be pre-provisioned, got {resp2.status_code}: {resp2.text}"
        )
        assert resp2.json()["sim_id"] == body["sim_id"]

    def test_06_pool_consumed_correctly(self):
        """4 IPs consumed: slot-1 + slot-2 for each of the 2 provisioned cards."""
        http = _new_client()
        stats = get_pool_stats(http, TestFirstConnectIMSIOnly_IMSI.pool_id)
        assert stats["allocated"] == 4, f"expected 4 allocated IPs, got: {stats}"

    def test_07_teardown(self):
        http = _new_client()
        _force_clear_range_profiles(F_A_S1, T_A_S1)
        _force_clear_range_profiles(F_A_S2, T_A_S2)
        delete_iccid_range_config(http, TestFirstConnectIMSIOnly_IMSI.range_id)
        delete_pool(http, TestFirstConnectIMSIOnly_IMSI.pool_id)


# ══════════════════════════════════════════════════════════════════════════════
# Class B — ip_resolution="imsi_apn"
# Per-IMSI per-APN IP.  APN pools must be configured before first connect.
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.order(2110)
class TestFirstConnectIMSIOnly_IMSI_APN:
    pool_inet_id: str | None = None
    pool_ims_id: str | None = None
    range_id: int | None = None
    sim_id_card0: str | None = None
    ip_s1_inet: str | None = None

    def test_01_setup(self):
        http = _new_client()
        _force_clear_range_profiles(F_B_S1, T_B_S1)
        _force_clear_range_profiles(F_B_S2, T_B_S2)
        pool_i = create_pool(http, subnet=SUBNET_B_INET, pool_name="test-21-B-inet",
                             replace_on_conflict=True)
        pool_m = create_pool(http, subnet=SUBNET_B_IMS, pool_name="test-21-B-ims",
                             replace_on_conflict=True)
        TestFirstConnectIMSIOnly_IMSI_APN.pool_inet_id = pool_i["pool_id"]
        TestFirstConnectIMSIOnly_IMSI_APN.pool_ims_id  = pool_m["pool_id"]
        rc = create_iccid_range_config(
            http,
            ip_resolution="imsi_apn",
            pool_id=pool_i["pool_id"],
            imsi_count=2,
            provisioning_mode="first_connect",
        )
        TestFirstConnectIMSIOnly_IMSI_APN.range_id = rc["id"]
        add_imsi_slot(http, iccid_range_id=rc["id"],
                      f_imsi=F_B_S1, t_imsi=T_B_S1, imsi_slot=1, ip_resolution="imsi_apn")
        add_imsi_slot(http, iccid_range_id=rc["id"],
                      f_imsi=F_B_S2, t_imsi=T_B_S2, imsi_slot=2, ip_resolution="imsi_apn")
        # APN pools must be configured BEFORE first-connect
        add_imsi_slot_apn_pool(http, iccid_range_id=rc["id"], slot=1,
                               apn=APN_INTERNET, pool_id=pool_i["pool_id"])
        add_imsi_slot_apn_pool(http, iccid_range_id=rc["id"], slot=1,
                               apn=APN_IMS, pool_id=pool_m["pool_id"])
        add_imsi_slot_apn_pool(http, iccid_range_id=rc["id"], slot=2,
                               apn=APN_INTERNET, pool_id=pool_i["pool_id"])
        add_imsi_slot_apn_pool(http, iccid_range_id=rc["id"], slot=2,
                               apn=APN_IMS, pool_id=pool_m["pool_id"])

    def test_02_first_connect_slot1_internet(self):
        """Slot-1 connects on internet APN → 201; both APNs are provisioned for slot-1."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_B_S1, apn=APN_INTERNET)
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("sim_id") and body.get("static_ip")
        TestFirstConnectIMSIOnly_IMSI_APN.sim_id_card0 = body["sim_id"]
        TestFirstConnectIMSIOnly_IMSI_APN.ip_s1_inet   = body["static_ip"]

    def test_03_slot1_ims_idempotent(self):
        """Slot-1 connects on IMS APN → 200 (IMS was provisioned alongside internet APN)."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_B_S1, apn=APN_IMS)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["sim_id"] == TestFirstConnectIMSIOnly_IMSI_APN.sim_id_card0
        # IMS IP must differ from internet IP
        assert body["static_ip"] != TestFirstConnectIMSIOnly_IMSI_APN.ip_s1_inet

    def test_04_slot2_preprovisioned_internet(self):
        """Slot-2 internet connect → 200 (pre-provisioned by sibling loop)."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_B_S2, apn=APN_INTERNET)
        assert resp.status_code == 200, (
            f"slot-2 should be pre-provisioned (200), got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["sim_id"] == TestFirstConnectIMSIOnly_IMSI_APN.sim_id_card0
        # Slot-2 has its own internet IP
        assert body["static_ip"] != TestFirstConnectIMSIOnly_IMSI_APN.ip_s1_inet, (
            "imsi_apn mode: slot-2 must have a different internet IP from slot-1"
        )

    def test_05_slot2_ims_idempotent(self):
        """Slot-2 IMS connect → 200 (IMS also pre-provisioned for slot-2)."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_B_S2, apn=APN_IMS)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        assert resp.json()["sim_id"] == TestFirstConnectIMSIOnly_IMSI_APN.sim_id_card0

    def test_06_teardown(self):
        http = _new_client()
        _force_clear_range_profiles(F_B_S1, T_B_S1)
        _force_clear_range_profiles(F_B_S2, T_B_S2)
        delete_iccid_range_config(http, TestFirstConnectIMSIOnly_IMSI_APN.range_id)
        delete_pool(http, TestFirstConnectIMSIOnly_IMSI_APN.pool_inet_id)
        delete_pool(http, TestFirstConnectIMSIOnly_IMSI_APN.pool_ims_id)


# ══════════════════════════════════════════════════════════════════════════════
# Class C — ip_resolution="iccid"
# Card-level IP shared across all slots.  sim_profiles.iccid stays NULL.
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.order(2120)
class TestFirstConnectIMSIOnly_ICCID:
    pool_id: str | None = None
    range_id: int | None = None
    sim_id_card0: str | None = None
    ip_card0: str | None = None

    def test_01_setup(self):
        http = _new_client()
        _force_clear_range_profiles(F_C_S1, T_C_S1)
        _force_clear_range_profiles(F_C_S2, T_C_S2)
        pool = create_pool(http, subnet=SUBNET_C, pool_name="test-21-C",
                           replace_on_conflict=True)
        TestFirstConnectIMSIOnly_ICCID.pool_id = pool["pool_id"]
        rc = create_iccid_range_config(
            http,
            ip_resolution="iccid",
            pool_id=pool["pool_id"],
            imsi_count=2,
            provisioning_mode="first_connect",
        )
        TestFirstConnectIMSIOnly_ICCID.range_id = rc["id"]
        add_imsi_slot(http, iccid_range_id=rc["id"],
                      f_imsi=F_C_S1, t_imsi=T_C_S1, imsi_slot=1, ip_resolution="iccid")
        add_imsi_slot(http, iccid_range_id=rc["id"],
                      f_imsi=F_C_S2, t_imsi=T_C_S2, imsi_slot=2, ip_resolution="iccid")

    def test_02_first_connect_slot1_card0(self):
        """Slot-1 IMSI card-0 connects → 201; one card-level IP allocated (iccid=NULL)."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_C_S1)
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("sim_id") and body.get("static_ip")
        TestFirstConnectIMSIOnly_ICCID.sim_id_card0 = body["sim_id"]
        TestFirstConnectIMSIOnly_ICCID.ip_card0     = body["static_ip"]

    def test_03_slot2_shares_card_ip(self):
        """Slot-2 IMSI card-0 → 200; returns the SAME card-level IP as slot-1."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_C_S2)
        assert resp.status_code == 200, (
            f"slot-2 should be pre-provisioned (200), got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["sim_id"] == TestFirstConnectIMSIOnly_ICCID.sim_id_card0, (
            "slot-2 must share the same sim_id (card-level profile)"
        )
        assert body["static_ip"] == TestFirstConnectIMSIOnly_ICCID.ip_card0, (
            "iccid mode: slot-2 must return the same card-level IP as slot-1"
        )

    def test_04_slot1_idempotent(self):
        """Slot-1 connects again → 200, same sim_id and IP."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_C_S1)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["sim_id"]    == TestFirstConnectIMSIOnly_ICCID.sim_id_card0
        assert body["static_ip"] == TestFirstConnectIMSIOnly_ICCID.ip_card0

    def test_05_second_card_new_profile(self):
        """Card 1: fresh sim_profile with a different card-level IP."""
        http = _new_client()
        resp = _first_connect(http, imsi=_imsi_at(F_C_S1, 1))
        assert resp.status_code == 201, f"expected 201 for card-1, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["sim_id"]    != TestFirstConnectIMSIOnly_ICCID.sim_id_card0
        assert body["static_ip"] != TestFirstConnectIMSIOnly_ICCID.ip_card0
        # Slot-2 card-1 pre-provisioned and shares same card-level IP
        resp2 = _first_connect(http, imsi=_imsi_at(F_C_S2, 1))
        assert resp2.status_code == 200
        assert resp2.json()["sim_id"]    == body["sim_id"]
        assert resp2.json()["static_ip"] == body["static_ip"], (
            "iccid mode: slot-2 card-1 must share the same IP as slot-1 card-1"
        )

    def test_06_pool_consumed_correctly(self):
        """2 IPs consumed: one per card (iccid mode is card-level, not per-slot)."""
        http = _new_client()
        stats = get_pool_stats(http, TestFirstConnectIMSIOnly_ICCID.pool_id)
        assert stats["allocated"] == 2, f"expected 2 allocated IPs (card-level), got: {stats}"

    def test_07_teardown(self):
        http = _new_client()
        _force_clear_range_profiles(F_C_S1, T_C_S1)
        _force_clear_range_profiles(F_C_S2, T_C_S2)
        delete_iccid_range_config(http, TestFirstConnectIMSIOnly_ICCID.range_id)
        delete_pool(http, TestFirstConnectIMSIOnly_ICCID.pool_id)


# ══════════════════════════════════════════════════════════════════════════════
# Class D — ip_resolution="iccid_apn"
# Card-level IP per APN.  APN pools configured on the connecting slot (slot-1).
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.order(2130)
class TestFirstConnectIMSIOnly_ICCID_APN:
    pool_inet_id: str | None = None
    pool_ims_id: str | None = None
    range_id: int | None = None
    sim_id_card0: str | None = None
    ip_card0_inet: str | None = None

    def test_01_setup(self):
        http = _new_client()
        _force_clear_range_profiles(F_D_S1, T_D_S1)
        _force_clear_range_profiles(F_D_S2, T_D_S2)
        pool_i = create_pool(http, subnet=SUBNET_D_INET, pool_name="test-21-D-inet",
                             replace_on_conflict=True)
        pool_m = create_pool(http, subnet=SUBNET_D_IMS, pool_name="test-21-D-ims",
                             replace_on_conflict=True)
        TestFirstConnectIMSIOnly_ICCID_APN.pool_inet_id = pool_i["pool_id"]
        TestFirstConnectIMSIOnly_ICCID_APN.pool_ims_id  = pool_m["pool_id"]
        rc = create_iccid_range_config(
            http,
            ip_resolution="iccid_apn",
            pool_id=pool_i["pool_id"],
            imsi_count=2,
            provisioning_mode="first_connect",
        )
        TestFirstConnectIMSIOnly_ICCID_APN.range_id = rc["id"]
        add_imsi_slot(http, iccid_range_id=rc["id"],
                      f_imsi=F_D_S1, t_imsi=T_D_S1, imsi_slot=1, ip_resolution="iccid_apn")
        add_imsi_slot(http, iccid_range_id=rc["id"],
                      f_imsi=F_D_S2, t_imsi=T_D_S2, imsi_slot=2, ip_resolution="iccid_apn")
        # APN pools on slot-1 — card-level IPs are allocated from the first-connecting slot
        add_imsi_slot_apn_pool(http, iccid_range_id=rc["id"], slot=1,
                               apn=APN_INTERNET, pool_id=pool_i["pool_id"])
        add_imsi_slot_apn_pool(http, iccid_range_id=rc["id"], slot=1,
                               apn=APN_IMS, pool_id=pool_m["pool_id"])

    def test_02_first_connect_slot1_internet(self):
        """Slot-1 connects on internet APN → 201; both APNs provisioned at card level."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_D_S1, apn=APN_INTERNET)
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("sim_id") and body.get("static_ip")
        TestFirstConnectIMSIOnly_ICCID_APN.sim_id_card0  = body["sim_id"]
        TestFirstConnectIMSIOnly_ICCID_APN.ip_card0_inet = body["static_ip"]

    def test_03_slot1_ims_idempotent(self):
        """Slot-1 on IMS APN → 200; card-level IMS IP differs from internet IP."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_D_S1, apn=APN_IMS)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["sim_id"] == TestFirstConnectIMSIOnly_ICCID_APN.sim_id_card0
        assert body["static_ip"] != TestFirstConnectIMSIOnly_ICCID_APN.ip_card0_inet, (
            "iccid_apn: IMS card IP must differ from internet card IP"
        )

    def test_04_slot2_internet_same_card_ip(self):
        """Slot-2 on internet APN → 200; same card-level internet IP (iccid_apn is card-level)."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_D_S2, apn=APN_INTERNET)
        assert resp.status_code == 200, (
            f"slot-2 should be pre-provisioned (200), got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["sim_id"] == TestFirstConnectIMSIOnly_ICCID_APN.sim_id_card0
        assert body["static_ip"] == TestFirstConnectIMSIOnly_ICCID_APN.ip_card0_inet, (
            "iccid_apn: all slots on same card share the same per-APN IP"
        )

    def test_05_slot2_ims_same_card_ip(self):
        """Slot-2 on IMS APN → 200; same card-level IMS IP."""
        http = _new_client()
        resp = _first_connect(http, imsi=F_D_S2, apn=APN_IMS)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["sim_id"] == TestFirstConnectIMSIOnly_ICCID_APN.sim_id_card0
        # IMS IP must match what slot-1 got (card-level)
        assert body["static_ip"] != TestFirstConnectIMSIOnly_ICCID_APN.ip_card0_inet, (
            "iccid_apn: IMS IP should differ from internet IP"
        )

    def test_06_pool_consumed_correctly(self):
        """2 IPs consumed for card 0: 1 internet + 1 IMS (card-level, not per-slot)."""
        http = _new_client()
        stats_i = get_pool_stats(http, TestFirstConnectIMSIOnly_ICCID_APN.pool_inet_id)
        stats_m = get_pool_stats(http, TestFirstConnectIMSIOnly_ICCID_APN.pool_ims_id)
        assert stats_i["allocated"] == 1, f"expected 1 internet IP allocated, got: {stats_i}"
        assert stats_m["allocated"] == 1, f"expected 1 IMS IP allocated, got: {stats_m}"

    def test_07_teardown(self):
        http = _new_client()
        _force_clear_range_profiles(F_D_S1, T_D_S1)
        _force_clear_range_profiles(F_D_S2, T_D_S2)
        delete_iccid_range_config(http, TestFirstConnectIMSIOnly_ICCID_APN.range_id)
        delete_pool(http, TestFirstConnectIMSIOnly_ICCID_APN.pool_inet_id)
        delete_pool(http, TestFirstConnectIMSIOnly_ICCID_APN.pool_ims_id)
