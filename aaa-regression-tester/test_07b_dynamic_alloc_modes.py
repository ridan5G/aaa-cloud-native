"""
test_07b_dynamic_alloc_modes.py — First-connection for all 8 auto-allocation scenarios.

Covers scenarios S2–S4 (single-IMSI) and M1–M4 (multi-IMSI) that are not tested
in test_07_dynamic_alloc.py (which tests S1 only).

Scenario matrix:
  S2 — Single-IMSI, imsi_apn  — APN catalog → N IPs per IMSI
  S3 — Single-IMSI, iccid     — card-level IP (apn=NULL) in sim_apn_ips
  S4 — Single-IMSI, iccid_apn — N card-level IPs via APN catalog
  M1 — Multi-IMSI,  imsi      — 1 IP per slot, all pre-provisioned in 1 COMMIT
  M2 — Multi-IMSI,  imsi_apn  — M×N IPs, per-slot APN catalog, 1 COMMIT
  M3 — Multi-IMSI,  iccid     — 1 shared card IP, all slots mapped, 1 COMMIT
  M4 — Multi-IMSI,  iccid_apn — N shared card IPs via APN catalog, 1 COMMIT

Test module = 13 → IMSI prefix 27877 13 (no overlap with other modules).
"""
import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, make_imsi, make_iccid, USE_CASE_ID
from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import cleanup_stale_profiles
from fixtures.range_configs import (
    create_range_config,
    delete_range_config,
    create_iccid_range_config,
    add_imsi_slot,
    add_apn_pool,
    delete_iccid_range_config,
)

MODULE = 13
APN_INTERNET = "internet.operator.com"
APN_IMS      = "ims.operator.com"


def _fc(http: httpx.Client, imsi: str, apn: str = APN_INTERNET) -> httpx.Response:
    """POST /profiles/first-connection — simulates aaa-radius-server Stage 2."""
    return http.post("/profiles/first-connection",
                     json={"imsi": imsi, "apn": apn, "use_case_id": USE_CASE_ID})


def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=30.0,
    )


# ══════════════════════════════════════════════════════════════════════════════
# S2 — Single-IMSI, ip_resolution=imsi_apn
# APN catalog: 2 entries → first-connection provisions 2 IPs in one transaction.
# ══════════════════════════════════════════════════════════════════════════════

class TestS2SingleImsiApn:
    """S2: single-IMSI SIM, imsi_apn mode with 2-entry APN catalog."""

    pool_internet_id: str | None = None
    pool_ims_id:      str | None = None
    range_config_id:  int | None = None

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            cleanup_stale_profiles(c, "27877130000000")
            cls.pool_internet_id = create_pool(
                c, subnet="100.65.230.0/29",
                pool_name="s2-internet", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_ims_id = create_pool(
                c, subnet="100.65.230.8/29",
                pool_name="s2-ims", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            rc = create_range_config(
                c,
                f_imsi=make_imsi(MODULE, 0),
                t_imsi=make_imsi(MODULE, 9),
                pool_id=cls.pool_internet_id,
                ip_resolution="imsi_apn",
                account_name="TestAccount",
            )
            cls.range_config_id = rc["id"]
            # APN catalog: internet → pool_internet, ims → pool_ims
            add_apn_pool(c, range_config_id=cls.range_config_id,
                         apn=APN_INTERNET, pool_id=cls.pool_internet_id)
            add_apn_pool(c, range_config_id=cls.range_config_id,
                         apn=APN_IMS, pool_id=cls.pool_ims_id)

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_config_id:
                delete_range_config(c, cls.range_config_id)
            if cls.pool_internet_id:
                delete_pool(c, cls.pool_internet_id)
            if cls.pool_ims_id:
                delete_pool(c, cls.pool_ims_id)

    def test_01_first_connection_allocates_request_apn_ip(self, http: httpx.Client):
        """201: returns static_ip for the request APN (internet); sim_id present."""
        imsi = make_imsi(MODULE, 0)
        r = _fc(http, imsi, APN_INTERNET)
        assert r.status_code == 201, f"Expected 201: {r.status_code} {r.text}"
        body = r.json()
        assert "sim_id" in body
        assert "static_ip" in body
        assert body["static_ip"].startswith("100.65.230.")

    def test_02_both_apns_provisioned(self, http: httpx.Client):
        """After first-connection, both APN IPs exist on the profile."""
        imsi = make_imsi(MODULE, 0)
        r = http.get("/profiles", params={"imsi": imsi})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles, "Profile must exist after first-connection"
        profile = profiles[0]
        assert profile["ip_resolution"] == "imsi_apn"
        # The IMSI should have 2 apn_ips entries (internet + ims)
        imsis = profile.get("imsis", [])
        assert imsis, "Profile must have at least one IMSI entry"
        apn_ips = imsis[0].get("apn_ips", [])
        apns_provisioned = {entry["apn"] for entry in apn_ips}
        assert APN_INTERNET in apns_provisioned, "internet APN must be provisioned"
        assert APN_IMS in apns_provisioned, "ims APN must be provisioned"

    def test_03_idempotency_returns_same_ip(self, http: httpx.Client):
        """Second first-connection call for same IMSI+APN returns 200 with same IP."""
        imsi = make_imsi(MODULE, 0)
        r1 = _fc(http, imsi, APN_INTERNET)
        assert r1.status_code in (200, 201)
        ip1 = r1.json()["static_ip"]
        r2 = _fc(http, imsi, APN_INTERNET)
        assert r2.status_code == 200, f"Second call must be 200 (reused): {r2.text}"
        assert r2.json()["static_ip"] == ip1, "IP must not change on idempotent call"

    def test_04_second_apn_also_idempotent(self, http: httpx.Client):
        """First-connection for the ims APN (already catalog-provisioned) returns 200."""
        imsi = make_imsi(MODULE, 0)
        r = _fc(http, imsi, APN_IMS)
        assert r.status_code == 200, f"Expected 200 for pre-provisioned ims APN: {r.text}"
        assert r.json()["static_ip"].startswith("100.65.230.")


# ══════════════════════════════════════════════════════════════════════════════
# S3 — Single-IMSI, ip_resolution=iccid
# IP stored at card level (sim_apn_ips, apn=NULL); IMSI has no per-IMSI IP.
# ══════════════════════════════════════════════════════════════════════════════

class TestS3SingleIccid:
    """S3: single-IMSI SIM, iccid mode — card-level IP."""

    pool_id:          str | None = None
    range_config_id:  int | None = None

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            cleanup_stale_profiles(c, "27877130000020")
            cls.pool_id = create_pool(
                c, subnet="100.65.230.16/29",
                pool_name="s3-pool", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            rc = create_range_config(
                c,
                f_imsi=make_imsi(MODULE, 200),
                t_imsi=make_imsi(MODULE, 209),
                pool_id=cls.pool_id,
                ip_resolution="iccid",
                account_name="TestAccount",
            )
            cls.range_config_id = rc["id"]

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_config_id:
                delete_range_config(c, cls.range_config_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    def test_01_first_connection_allocates_card_level_ip(self, http: httpx.Client):
        """201: card-level IP allocated; sim_id and static_ip in response."""
        imsi = make_imsi(MODULE, 200)
        r = _fc(http, imsi, APN_INTERNET)
        assert r.status_code == 201, f"Expected 201: {r.status_code} {r.text}"
        body = r.json()
        assert "sim_id" in body
        assert "static_ip" in body

    def test_02_profile_has_iccid_resolution(self, http: httpx.Client):
        """GET /profiles?imsi= → ip_resolution=iccid; iccid_ips present."""
        imsi = make_imsi(MODULE, 200)
        r = http.get("/profiles", params={"imsi": imsi})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles
        profile = profiles[0]
        assert profile["ip_resolution"] == "iccid"
        iccid_ips = profile.get("iccid_ips", [])
        assert len(iccid_ips) == 1, f"Expected exactly 1 card-level IP, got {len(iccid_ips)}"
        assert iccid_ips[0].get("apn") is None, "iccid mode stores apn=NULL"

    def test_03_different_apn_returns_same_ip(self, http: httpx.Client):
        """iccid mode is APN-agnostic: any APN returns the same card IP."""
        imsi = make_imsi(MODULE, 200)
        r1 = _fc(http, imsi, APN_INTERNET)
        assert r1.status_code == 200
        ip1 = r1.json()["static_ip"]
        r2 = _fc(http, imsi, APN_IMS)
        assert r2.status_code == 200
        assert r2.json()["static_ip"] == ip1, "iccid mode: same IP regardless of APN"


# ══════════════════════════════════════════════════════════════════════════════
# S4 — Single-IMSI, ip_resolution=iccid_apn
# APN catalog → N card-level IPs in sim_apn_ips.
# ══════════════════════════════════════════════════════════════════════════════

class TestS4SingleIccidApn:
    """S4: single-IMSI SIM, iccid_apn mode with 2-entry APN catalog."""

    pool_internet_id: str | None = None
    pool_ims_id:      str | None = None
    range_config_id:  int | None = None

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            cleanup_stale_profiles(c, "27877130000040")
            cls.pool_internet_id = create_pool(
                c, subnet="100.65.230.24/29",
                pool_name="s4-internet", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_ims_id = create_pool(
                c, subnet="100.65.230.32/29",
                pool_name="s4-ims", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            rc = create_range_config(
                c,
                f_imsi=make_imsi(MODULE, 400),
                t_imsi=make_imsi(MODULE, 409),
                pool_id=cls.pool_internet_id,
                ip_resolution="iccid_apn",
                account_name="TestAccount",
            )
            cls.range_config_id = rc["id"]
            add_apn_pool(c, range_config_id=cls.range_config_id,
                         apn=APN_INTERNET, pool_id=cls.pool_internet_id)
            add_apn_pool(c, range_config_id=cls.range_config_id,
                         apn=APN_IMS, pool_id=cls.pool_ims_id)

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_config_id:
                delete_range_config(c, cls.range_config_id)
            if cls.pool_internet_id:
                delete_pool(c, cls.pool_internet_id)
            if cls.pool_ims_id:
                delete_pool(c, cls.pool_ims_id)

    def test_01_first_connection_returns_request_apn_ip(self, http: httpx.Client):
        """201: static_ip matches the internet APN pool; sim_id present."""
        imsi = make_imsi(MODULE, 400)
        r = _fc(http, imsi, APN_INTERNET)
        assert r.status_code == 201, f"Expected 201: {r.status_code} {r.text}"
        body = r.json()
        assert "sim_id" in body
        assert "static_ip" in body

    def test_02_both_apns_provisioned_at_card_level(self, http: httpx.Client):
        """Profile has 2 card-level IPs (one per APN), no per-IMSI IPs."""
        imsi = make_imsi(MODULE, 400)
        r = http.get("/profiles", params={"imsi": imsi})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles
        profile = profiles[0]
        assert profile["ip_resolution"] == "iccid_apn"
        iccid_ips = profile.get("iccid_ips", [])
        assert len(iccid_ips) == 2, f"Expected 2 card-level IPs, got {len(iccid_ips)}"
        apns = {e["apn"] for e in iccid_ips}
        assert APN_INTERNET in apns
        assert APN_IMS in apns

    def test_03_ims_apn_idempotent(self, http: httpx.Client):
        """First-connection for ims APN (pre-provisioned by catalog) returns 200."""
        imsi = make_imsi(MODULE, 400)
        r = _fc(http, imsi, APN_IMS)
        assert r.status_code == 200, f"Expected 200 for pre-provisioned ims APN: {r.text}"
        assert r.json()["static_ip"].startswith("100.65.230.")


# ══════════════════════════════════════════════════════════════════════════════
# M1 — Multi-IMSI, ip_resolution=imsi
# First slot connection pre-provisions the sibling slot in the same transaction.
# ══════════════════════════════════════════════════════════════════════════════

class TestM1MultiImsi:
    """M1: 2-slot multi-IMSI SIM, imsi mode — 1 IP per slot, atomic pre-provisioning."""

    pool_slot1_id:     str | None = None
    pool_slot2_id:     str | None = None
    iccid_range_id:    int | None = None
    slot1_rc_id:       int | None = None
    slot2_rc_id:       int | None = None

    F_ICCID = make_iccid(MODULE, 0)
    T_ICCID = make_iccid(MODULE, 9)
    F_IMSI1 = make_imsi(MODULE, 600)   # slot 1
    T_IMSI1 = make_imsi(MODULE, 609)
    F_IMSI2 = make_imsi(MODULE, 700)   # slot 2
    T_IMSI2 = make_imsi(MODULE, 709)

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            # Slot-1 prefix is sufficient — profiles contain both IMSI slots
            cleanup_stale_profiles(c, "27877130000060")
            cls.pool_slot1_id = create_pool(
                c, subnet="100.65.230.40/29",
                pool_name="m1-slot1", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_slot2_id = create_pool(
                c, subnet="100.65.230.48/29",
                pool_name="m1-slot2", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            iccid_rc = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID, t_iccid=cls.T_ICCID,
                ip_resolution="imsi",
                pool_id=cls.pool_slot1_id,
                imsi_count=2,
            )
            cls.iccid_range_id = iccid_rc["id"]
            slot1 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI1, t_imsi=cls.T_IMSI1,
                imsi_slot=1, ip_resolution="imsi",
                pool_id=cls.pool_slot1_id,
            )
            cls.slot1_rc_id = slot1["range_config_id"]
            slot2 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI2, t_imsi=cls.T_IMSI2,
                imsi_slot=2, ip_resolution="imsi",
                pool_id=cls.pool_slot2_id,
            )
            cls.slot2_rc_id = slot2["range_config_id"]

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.iccid_range_id:
                delete_iccid_range_config(c, cls.iccid_range_id)
            if cls.pool_slot1_id:
                delete_pool(c, cls.pool_slot1_id)
            if cls.pool_slot2_id:
                delete_pool(c, cls.pool_slot2_id)

    def test_01_first_slot_connection_returns_201(self, http: httpx.Client):
        """First-connection for slot-1 IMSI → 201 with sim_id and static_ip."""
        r = _fc(http, self.F_IMSI1)
        assert r.status_code == 201, f"Expected 201: {r.status_code} {r.text}"
        body = r.json()
        assert "sim_id" in body
        assert "static_ip" in body

    def test_02_sibling_slot2_pre_provisioned(self, http: httpx.Client):
        """Slot-2 IMSI was pre-provisioned atomically; GET /profiles returns it."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI2})
        assert r.status_code == 200, f"Slot-2 IMSI must be provisioned: {r.text}"
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles, "Slot-2 IMSI should have been pre-provisioned"
        profile = profiles[0]
        assert profile["ip_resolution"] == "imsi"
        imsis_on_profile = [i["imsi"] for i in profile.get("imsis", [])]
        assert self.F_IMSI1 in imsis_on_profile, "Slot-1 IMSI must be on same profile"
        assert self.F_IMSI2 in imsis_on_profile, "Slot-2 IMSI must be on same profile"

    def test_03_slot2_connection_is_idempotent(self, http: httpx.Client):
        """Second connection on slot-2 IMSI returns 200 (pre-provisioned path)."""
        r = _fc(http, self.F_IMSI2)
        assert r.status_code == 200, f"Expected 200 for pre-provisioned slot-2: {r.text}"
        body = r.json()
        assert "static_ip" in body

    def test_04_each_slot_has_distinct_ip(self, http: httpx.Client):
        """Slot-1 and slot-2 IMSIs have different IPs drawn from their own pools."""
        r1 = _fc(http, self.F_IMSI1)
        r2 = _fc(http, self.F_IMSI2)
        assert r1.status_code in (200, 201)
        assert r2.status_code in (200, 201)
        ip1 = r1.json()["static_ip"]
        ip2 = r2.json()["static_ip"]
        assert ip1 != ip2, f"Slot IPs must differ: both got {ip1}"
        assert ip1.startswith("100.65.230.4"), "Slot-1 IP from pool_slot1 (/29 at .40)"
        assert ip2.startswith("100.65.230.4") or ip2.startswith("100.65.230.5"), \
            "Slot-2 IP from pool_slot2 (/29 at .48)"


# ══════════════════════════════════════════════════════════════════════════════
# M2 — Multi-IMSI, ip_resolution=imsi_apn + APN catalog
# 2 slots × 2 APNs = 4 IPs provisioned in one COMMIT.
# ══════════════════════════════════════════════════════════════════════════════

class TestM2MultiImsiApn:
    """M2: 2-slot multi-IMSI SIM, imsi_apn + 2-entry APN catalog → 4 IPs."""

    pool_internet_id:  str | None = None
    pool_ims_id:       str | None = None
    iccid_range_id:    int | None = None
    slot1_rc_id:       int | None = None
    slot2_rc_id:       int | None = None

    F_ICCID = make_iccid(MODULE, 100)
    T_ICCID = make_iccid(MODULE, 109)
    F_IMSI1 = make_imsi(MODULE, 800)
    T_IMSI1 = make_imsi(MODULE, 809)
    F_IMSI2 = make_imsi(MODULE, 900)
    T_IMSI2 = make_imsi(MODULE, 909)

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            cleanup_stale_profiles(c, "27877130000080")
            cls.pool_internet_id = create_pool(
                c, subnet="100.65.230.56/29",
                pool_name="m2-internet", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_ims_id = create_pool(
                c, subnet="100.65.230.64/29",
                pool_name="m2-ims", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            iccid_rc = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID, t_iccid=cls.T_ICCID,
                ip_resolution="imsi_apn",
                pool_id=cls.pool_internet_id,
                imsi_count=2,
            )
            cls.iccid_range_id = iccid_rc["id"]
            slot1 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI1, t_imsi=cls.T_IMSI1,
                imsi_slot=1, ip_resolution="imsi_apn",
                pool_id=cls.pool_internet_id,
            )
            cls.slot1_rc_id = slot1["range_config_id"]
            # APN catalog for slot 1
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_INTERNET, pool_id=cls.pool_internet_id)
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_IMS, pool_id=cls.pool_ims_id)

            slot2 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI2, t_imsi=cls.T_IMSI2,
                imsi_slot=2, ip_resolution="imsi_apn",
                pool_id=cls.pool_internet_id,
            )
            cls.slot2_rc_id = slot2["range_config_id"]
            # APN catalog for slot 2 (same pools)
            add_apn_pool(c, range_config_id=cls.slot2_rc_id,
                         apn=APN_INTERNET, pool_id=cls.pool_internet_id)
            add_apn_pool(c, range_config_id=cls.slot2_rc_id,
                         apn=APN_IMS, pool_id=cls.pool_ims_id)

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.iccid_range_id:
                delete_iccid_range_config(c, cls.iccid_range_id)
            if cls.pool_internet_id:
                delete_pool(c, cls.pool_internet_id)
            if cls.pool_ims_id:
                delete_pool(c, cls.pool_ims_id)

    def test_01_first_connection_slot1_returns_201(self, http: httpx.Client):
        """201: slot-1 first-connection returns internet APN IP."""
        r = _fc(http, self.F_IMSI1, APN_INTERNET)
        assert r.status_code == 201, f"Expected 201: {r.status_code} {r.text}"
        body = r.json()
        assert "sim_id" in body and "static_ip" in body

    def test_02_slot1_has_both_apns_provisioned(self, http: httpx.Client):
        """Slot-1 IMSI has 2 apn_ips entries after first-connection."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI1})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles
        imsis = profiles[0].get("imsis", [])
        slot1_entry = next((i for i in imsis if i["imsi"] == self.F_IMSI1), None)
        assert slot1_entry, "Slot-1 IMSI must be on profile"
        apns = {e["apn"] for e in slot1_entry.get("apn_ips", [])}
        assert APN_INTERNET in apns and APN_IMS in apns, \
            f"Both APNs must be provisioned for slot-1, got: {apns}"

    def test_03_slot2_pre_provisioned_with_both_apns(self, http: httpx.Client):
        """Slot-2 IMSI was pre-provisioned with both APNs in the same transaction."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI2})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles, "Slot-2 IMSI should be pre-provisioned"
        imsis = profiles[0].get("imsis", [])
        slot2_entry = next((i for i in imsis if i["imsi"] == self.F_IMSI2), None)
        assert slot2_entry, "Slot-2 IMSI must be on profile"
        apns = {e["apn"] for e in slot2_entry.get("apn_ips", [])}
        assert APN_INTERNET in apns and APN_IMS in apns, \
            f"Both APNs must be pre-provisioned for slot-2, got: {apns}"

    def test_04_total_ips_allocated_is_four(self, http: httpx.Client):
        """2 slots × 2 APNs = 4 IPs drawn from the two pools."""
        # Verify 4 unique IPs (internet pool has 2, ims pool has 2)
        r = http.get("/pools/" + self.pool_internet_id + "/stats")
        assert r.status_code == 200
        internet_alloc = r.json()["allocated"]
        r2 = http.get("/pools/" + self.pool_ims_id + "/stats")
        assert r2.status_code == 200
        ims_alloc = r2.json()["allocated"]
        assert internet_alloc >= 2, f"internet pool must have ≥2 allocated, got {internet_alloc}"
        assert ims_alloc >= 2, f"ims pool must have ≥2 allocated, got {ims_alloc}"


# ══════════════════════════════════════════════════════════════════════════════
# M3 — Multi-IMSI, ip_resolution=iccid
# One shared card-level IP; all sibling slots mapped to same device in 1 COMMIT.
# ══════════════════════════════════════════════════════════════════════════════

class TestM3MultiIccid:
    """M3: 2-slot multi-IMSI SIM, iccid mode — 1 shared card IP."""

    pool_id:           str | None = None
    iccid_range_id:    int | None = None

    F_ICCID = make_iccid(MODULE, 200)
    T_ICCID = make_iccid(MODULE, 209)
    F_IMSI1 = make_imsi(MODULE, 1000)
    T_IMSI1 = make_imsi(MODULE, 1009)
    F_IMSI2 = make_imsi(MODULE, 1100)
    T_IMSI2 = make_imsi(MODULE, 1109)

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            cleanup_stale_profiles(c, "27877130000100")
            cls.pool_id = create_pool(
                c, subnet="100.65.230.72/29",
                pool_name="m3-pool", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            iccid_rc = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID, t_iccid=cls.T_ICCID,
                ip_resolution="iccid",
                pool_id=cls.pool_id,
                imsi_count=2,
            )
            cls.iccid_range_id = iccid_rc["id"]
            add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI1, t_imsi=cls.T_IMSI1,
                imsi_slot=1, ip_resolution="iccid",
            )
            add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI2, t_imsi=cls.T_IMSI2,
                imsi_slot=2, ip_resolution="iccid",
            )

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.iccid_range_id:
                delete_iccid_range_config(c, cls.iccid_range_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    def test_01_first_connection_creates_card_profile(self, http: httpx.Client):
        """201: single card-level IP allocated; sim_id in response."""
        r = _fc(http, self.F_IMSI1)
        assert r.status_code == 201, f"Expected 201: {r.status_code} {r.text}"
        body = r.json()
        assert "sim_id" in body and "static_ip" in body

    def test_02_slot2_shares_same_device_and_ip(self, http: httpx.Client):
        """Slot-2 IMSI returns 200 with the SAME IP (shared card IP, iccid mode)."""
        r1 = _fc(http, self.F_IMSI1)
        r2 = _fc(http, self.F_IMSI2)
        assert r1.status_code in (200, 201)
        assert r2.status_code == 200, f"Slot-2 must be pre-provisioned (200): {r2.text}"
        assert r1.json()["static_ip"] == r2.json()["static_ip"], \
            "iccid mode: all slots share one card IP"
        assert r1.json()["sim_id"] == r2.json()["sim_id"], \
            "iccid mode: all slots share one sim_id"

    def test_03_pool_allocates_exactly_one_ip(self, http: httpx.Client):
        """iccid mode: only 1 IP consumed from pool regardless of slot count."""
        r = http.get(f"/pools/{self.pool_id}/stats")
        assert r.status_code == 200
        assert r.json()["allocated"] == 1, \
            f"iccid mode must consume exactly 1 IP; got {r.json()['allocated']}"


# ══════════════════════════════════════════════════════════════════════════════
# M4 — Multi-IMSI, ip_resolution=iccid_apn + APN catalog
# N shared card-level IPs; all sibling slots share the same sim_apn_ips rows.
# ══════════════════════════════════════════════════════════════════════════════

class TestM4MultiIccidApn:
    """M4: 2-slot multi-IMSI SIM, iccid_apn + 2-entry APN catalog → 2 shared IPs."""

    pool_internet_id:  str | None = None
    pool_ims_id:       str | None = None
    iccid_range_id:    int | None = None
    slot1_rc_id:       int | None = None

    F_ICCID = make_iccid(MODULE, 300)
    T_ICCID = make_iccid(MODULE, 309)
    F_IMSI1 = make_imsi(MODULE, 1200)
    T_IMSI1 = make_imsi(MODULE, 1209)
    F_IMSI2 = make_imsi(MODULE, 1300)
    T_IMSI2 = make_imsi(MODULE, 1309)

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            cleanup_stale_profiles(c, "27877130000120")
            cls.pool_internet_id = create_pool(
                c, subnet="100.65.230.80/29",
                pool_name="m4-internet", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_ims_id = create_pool(
                c, subnet="100.65.230.88/29",
                pool_name="m4-ims", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            iccid_rc = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID, t_iccid=cls.T_ICCID,
                ip_resolution="iccid_apn",
                pool_id=cls.pool_internet_id,
                imsi_count=2,
            )
            cls.iccid_range_id = iccid_rc["id"]
            slot1 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI1, t_imsi=cls.T_IMSI1,
                imsi_slot=1, ip_resolution="iccid_apn",
                pool_id=cls.pool_internet_id,
            )
            cls.slot1_rc_id = slot1["range_config_id"]
            # APN catalog on slot-1 (iccid_apn: catalog on slot range config)
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_INTERNET, pool_id=cls.pool_internet_id)
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_IMS, pool_id=cls.pool_ims_id)
            add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI2, t_imsi=cls.T_IMSI2,
                imsi_slot=2, ip_resolution="iccid_apn",
                pool_id=cls.pool_internet_id,
            )

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.iccid_range_id:
                delete_iccid_range_config(c, cls.iccid_range_id)
            if cls.pool_internet_id:
                delete_pool(c, cls.pool_internet_id)
            if cls.pool_ims_id:
                delete_pool(c, cls.pool_ims_id)

    def test_01_first_connection_slot1_returns_internet_ip(self, http: httpx.Client):
        """201: internet APN IP returned; sim_id present."""
        r = _fc(http, self.F_IMSI1, APN_INTERNET)
        assert r.status_code == 201, f"Expected 201: {r.status_code} {r.text}"
        body = r.json()
        assert "sim_id" in body and "static_ip" in body

    def test_02_both_apns_at_card_level(self, http: httpx.Client):
        """Profile has 2 card-level IPs (internet + ims) shared across both slots."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI1})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles
        profile = profiles[0]
        assert profile["ip_resolution"] == "iccid_apn"
        iccid_ips = profile.get("iccid_ips", [])
        assert len(iccid_ips) == 2, f"Expected 2 card-level IPs, got {len(iccid_ips)}"
        apns = {e["apn"] for e in iccid_ips}
        assert APN_INTERNET in apns and APN_IMS in apns

    def test_03_slot2_shares_card_ips(self, http: httpx.Client):
        """Slot-2 IMSI returns same IPs (card-level, iccid_apn mode)."""
        r1 = _fc(http, self.F_IMSI1, APN_INTERNET)
        r2 = _fc(http, self.F_IMSI2, APN_INTERNET)
        assert r1.status_code in (200, 201)
        assert r2.status_code == 200
        assert r1.json()["static_ip"] == r2.json()["static_ip"], \
            "iccid_apn: both slots share the same card-level internet IP"

    def test_04_ims_apn_also_shared(self, http: httpx.Client):
        """Slot-2 ims APN returns same card-level ims IP as slot-1."""
        r1 = _fc(http, self.F_IMSI1, APN_IMS)
        r2 = _fc(http, self.F_IMSI2, APN_IMS)
        assert r1.status_code in (200, 201)
        assert r2.status_code == 200
        assert r1.json()["static_ip"] == r2.json()["static_ip"], \
            "iccid_apn: ims APN IP shared across slots"
