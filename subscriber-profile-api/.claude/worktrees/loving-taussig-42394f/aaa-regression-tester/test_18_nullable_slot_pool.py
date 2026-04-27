"""
test_18_nullable_slot_pool.py — Nullable slot pool_id + APN-pool routing regressions.

Covers the exact production bug where a multi-IMSI ICCID range with imsi_apn mode
and per-slot APN pools (no default pool_id on the slot) caused a 500
NotNullViolationError: null value in column "pool_id" of relation "imsi_range_configs".

Five test scenarios:

  M5  — imsi_apn, both slots have APN pools but NO pool_id (exact bug scenario)
  M5b — imsi_apn, slot1 has APN pools, slot2 has pool_id but NO APN config
          → sibling pre-provisioned via fallback_pairs with full APN set (Bug 3)
  M6  — iccid mode, both slots pool_id=NULL, parent pool provides COALESCE (Bug 4 area)
  M7  — iccid_apn, slot1 APN pools + no pool_id, slot2 no pool/no APNs (Bug 1)
  M8  — immediate mode, imsi_apn, last slot added with NO APN config
          → job ends with completed_with_errors + clear error message (Bug 2)

Running-DB migration required before these tests pass on an existing cluster:
  ALTER TABLE imsi_range_configs ALTER COLUMN pool_id DROP NOT NULL;

Resources
─────────
  Module 18 → IMSI prefix 27877 18 xxxxxxxx  (no conflict with other modules)

  All pools use 100.65.210.x/28 subnets (14 usable IPs each, ample for tiny ranges).

  M5  — 3 cards, 2 slots
    F_ICCID 8944501180000000001 … 8944501180000000003
    Slot 1: IMSI 278771800010001..10003 → pools 100.65.210.0/28 (internet) + .16/28 (IMS)
    Slot 2: IMSI 278771800020001..20003 → pools 100.65.210.32/28 (internet) + .48/28 (IMS)

  M5b — 2 cards, 2 slots
    F_ICCID 8944501180000000101 … 8944501180000000102
    Slot 1: IMSI 278771800030001..30002 → pools 100.65.210.64/28 (internet) + .80/28 (IMS)
    Slot 2: IMSI 278771800040001..40002 → pool  100.65.210.96/28 (no APN config)

  M6  — 2 cards, 2 slots (iccid mode)
    F_ICCID 8944501180000000201 … 8944501180000000202
    Slot 1+2: no pool_id → parent pool 100.65.210.112/28

  M7  — 2 cards, 2 slots (iccid_apn mode)
    F_ICCID 8944501180000000301 … 8944501180000000302
    Slot 1: no pool_id, APN pools: 100.65.210.128/28 (internet) + .144/28 (IMS)
    Slot 2: no pool_id, no APN pools

  M8  — 2 cards, 2 slots (immediate, imsi_apn)
    F_ICCID 8944501180000000401 … 8944501180000000402
    Slot 1: APN pools: 100.65.210.160/28 (internet) + .176/28 (IMS)
    Slot 2: no APN config → last-slot job fires → completed_with_errors
"""
import ipaddress

import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID, make_imsi, make_iccid, poll_until
from fixtures.pools import create_pool, delete_pool, get_pool_stats, _force_clear_range_profiles
from fixtures.range_configs import (
    create_iccid_range_config,
    add_imsi_slot,
    add_apn_pool,
    delete_iccid_range_config,
)

MODULE = 18

APN_INTERNET = "internet.operator.com"
APN_IMS      = "ims.operator.com"


def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=30.0,
    )


def _fc(http: httpx.Client, imsi: str, apn: str = APN_INTERNET) -> httpx.Response:
    """POST /first-connection helper."""
    return http.post(
        "/first-connection",
        json={"imsi": imsi, "apn": apn, "use_case_id": USE_CASE_ID},
    )


def _in_subnet(ip: str, subnet: str) -> bool:
    """Return True when ip falls inside subnet."""
    return ipaddress.ip_address(ip) in ipaddress.ip_network(subnet, strict=False)


def _wait_for_job(http: httpx.Client, job_id: str, timeout: float = 300.0) -> dict:
    return poll_until(
        fn=lambda: http.get(f"/jobs/{job_id}").json(),
        condition=lambda r: r.get("status") in ("completed", "completed_with_errors", "failed"),
        timeout=timeout,
        interval=3.0,
        label=f"job {job_id} completion",
    )


# ══════════════════════════════════════════════════════════════════════════════
# M5 — imsi_apn, NO pool_id on slots, each slot has its own APN→pool catalog
#       (the exact production bug: NotNullViolationError on imsi_range_configs.pool_id)
# ══════════════════════════════════════════════════════════════════════════════

class TestM5_ImsiApn_NullSlotPool:
    """M5: 2-slot imsi_apn SIM, slots created with pool_id=None — Bug 1 regression."""

    pool_s1_internet_id: str = ""
    pool_s1_ims_id:      str = ""
    pool_s2_internet_id: str = ""
    pool_s2_ims_id:      str = ""
    iccid_range_id:      int = 0
    slot1_rc_id:         int = 0
    slot2_rc_id:         int = 0

    F_ICCID = make_iccid(MODULE, 1)     # "8944501180000000001"
    T_ICCID = make_iccid(MODULE, 3)     # "8944501180000000003"
    F_IMSI_S1 = make_imsi(MODULE, 10001)
    T_IMSI_S1 = make_imsi(MODULE, 10003)
    F_IMSI_S2 = make_imsi(MODULE, 20001)
    T_IMSI_S2 = make_imsi(MODULE, 20003)

    @classmethod
    def setup_class(cls):
        _force_clear_range_profiles(cls.F_IMSI_S1, cls.T_IMSI_S2)
        with _new_client() as c:
            cls.pool_s1_internet_id = create_pool(
                c, subnet="100.65.210.0/28",
                pool_name="m5-s1-internet", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_s1_ims_id = create_pool(
                c, subnet="100.65.210.16/28",
                pool_name="m5-s1-ims", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_s2_internet_id = create_pool(
                c, subnet="100.65.210.32/28",
                pool_name="m5-s2-internet", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_s2_ims_id = create_pool(
                c, subnet="100.65.210.48/28",
                pool_name="m5-s2-ims", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]

            # Parent range: no pool_id (purely APN-driven routing)
            iccid_rc = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID, t_iccid=cls.T_ICCID,
                ip_resolution="imsi_apn",
                imsi_count=2,
            )
            cls.iccid_range_id = iccid_rc["id"]

            # Slot 1: NO pool_id — this used to 500 before the DB fix
            slot1 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI_S1, t_imsi=cls.T_IMSI_S1,
                imsi_slot=1, ip_resolution="imsi_apn",
            )
            cls.slot1_rc_id = slot1["range_config_id"]
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_INTERNET, pool_id=cls.pool_s1_internet_id)
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_IMS, pool_id=cls.pool_s1_ims_id)

            # Slot 2: NO pool_id
            slot2 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI_S2, t_imsi=cls.T_IMSI_S2,
                imsi_slot=2, ip_resolution="imsi_apn",
            )
            cls.slot2_rc_id = slot2["range_config_id"]
            add_apn_pool(c, range_config_id=cls.slot2_rc_id,
                         apn=APN_INTERNET, pool_id=cls.pool_s2_internet_id)
            add_apn_pool(c, range_config_id=cls.slot2_rc_id,
                         apn=APN_IMS, pool_id=cls.pool_s2_ims_id)

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.iccid_range_id:
                delete_iccid_range_config(c, cls.iccid_range_id)
            for pid in [
                cls.pool_s1_internet_id, cls.pool_s1_ims_id,
                cls.pool_s2_internet_id, cls.pool_s2_ims_id,
            ]:
                if pid:
                    delete_pool(c, pid)

    # 18.M5.1 ─────────────────────────────────────────────────────────────────
    def test_01_slot_add_without_pool_id_returns_201(self):
        """Both slots were added without pool_id → setup_class succeeded (Bug 1 guard)."""
        assert self.slot1_rc_id, "slot1 range_config_id must be set by setup"
        assert self.slot2_rc_id, "slot2 range_config_id must be set by setup"

    # 18.M5.2 ─────────────────────────────────────────────────────────────────
    def test_02_first_connection_slot1_returns_201(self, http: httpx.Client):
        """first-connection on slot-1 IMSI → 201, non-null IP in slot1-internet subnet."""
        r = _fc(http, self.F_IMSI_S1, APN_INTERNET)
        assert r.status_code == 201, f"Expected 201: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("static_ip"), f"Expected non-null IP: {body}"
        assert _in_subnet(body["static_ip"], "100.65.210.0/28"), \
            f"IP {body['static_ip']} not in slot1-internet subnet"

    # 18.M5.3 ─────────────────────────────────────────────────────────────────
    def test_03_slot2_pre_provisioned_with_both_apns(self, http: httpx.Client):
        """Slot-2 was pre-provisioned atomically with both APNs from its own APN catalog."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI_S2})
        assert r.status_code == 200, f"Profile lookup failed: {r.text}"
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles, "Slot-2 should be pre-provisioned"
        imsis_on_profile = profiles[0].get("imsis", [])
        slot2_entry = next((i for i in imsis_on_profile if i["imsi"] == self.F_IMSI_S2), None)
        assert slot2_entry, "Slot-2 IMSI must appear on the profile"
        apns = {e["apn"] for e in slot2_entry.get("apn_ips", [])}
        assert APN_INTERNET in apns, f"Slot-2 must have internet APN pre-provisioned, got: {apns}"
        assert APN_IMS in apns, f"Slot-2 must have IMS APN pre-provisioned, got: {apns}"

    # 18.M5.4 ─────────────────────────────────────────────────────────────────
    def test_04_slot2_ips_in_correct_pools(self, http: httpx.Client):
        """Slot-2 IPs come from slot-2 pools, not slot-1 pools."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI_S2})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        imsis_on_profile = profiles[0].get("imsis", [])
        slot2_entry = next((i for i in imsis_on_profile if i["imsi"] == self.F_IMSI_S2), None)
        assert slot2_entry
        for entry in slot2_entry.get("apn_ips", []):
            ip = entry["static_ip"]
            if entry["apn"] == APN_INTERNET:
                assert _in_subnet(ip, "100.65.210.32/28"), \
                    f"Slot-2 internet IP {ip} not in pool_s2_internet subnet"
            elif entry["apn"] == APN_IMS:
                assert _in_subnet(ip, "100.65.210.48/28"), \
                    f"Slot-2 IMS IP {ip} not in pool_s2_ims subnet"

    # 18.M5.5 ─────────────────────────────────────────────────────────────────
    def test_05_second_connect_slot2_is_idempotent(self, http: httpx.Client):
        """first-connection on already-provisioned slot-2 IMSI → 200 (idempotent)."""
        r = _fc(http, self.F_IMSI_S2, APN_IMS)
        assert r.status_code == 200, f"Expected 200 (idempotent): {r.status_code} {r.text}"
        body = r.json()
        assert body.get("static_ip"), f"Must return the pre-provisioned IP: {body}"

    # 18.M5.6 ─────────────────────────────────────────────────────────────────
    def test_06_release_ips_returns_four(self, http: httpx.Client):
        """Release IPs for the first card → released_count == 4 (2 APNs × 2 slots)."""
        # Get sim_id from the profile
        r = http.get("/profiles", params={"imsi": self.F_IMSI_S1})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles
        sim_id = profiles[0]["sim_id"]

        rel = http.post(f"/profiles/{sim_id}/release-ips")
        assert rel.status_code == 200, f"Release failed: {rel.status_code} {rel.text}"
        assert rel.json().get("released_count") == 4, \
            f"Expected 4 released IPs, got: {rel.json()}"

    # 18.M5.7 ─────────────────────────────────────────────────────────────────
    def test_07_reconnect_after_release_returns_ip(self, http: httpx.Client):
        """After release, re-connecting slot-1 → non-null IP in slot1-internet pool."""
        r = _fc(http, self.F_IMSI_S1, APN_INTERNET)
        assert r.status_code in (200, 201), \
            f"Expected 200 or 201 after re-connect: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("static_ip"), f"Expected non-null IP: {body}"
        assert _in_subnet(body["static_ip"], "100.65.210.0/28"), \
            f"IP {body['static_ip']} not in slot1-internet subnet after re-connect"


# ══════════════════════════════════════════════════════════════════════════════
# M5b — imsi_apn, slot1 has APN pools, slot2 has pool_id but NO APN config
#        → first-connect on slot1 must fail 422 (mandatory APN config — Bug 3)
#        → after adding APN pools to slot2, retry succeeds
# ══════════════════════════════════════════════════════════════════════════════

class TestM5b_SiblingNoApnConfig:
    """M5b: sibling slot missing APN config in imsi_apn mode → 422 missing_apn_config."""

    pool_s1_internet_id: str = ""
    pool_s1_ims_id:      str = ""
    pool_s2_id:          str = ""
    iccid_range_id:      int = 0
    slot1_rc_id:         int = 0
    slot2_rc_id:         int = 0

    F_ICCID = make_iccid(MODULE, 101)   # "8944501180000000101"
    T_ICCID = make_iccid(MODULE, 102)   # "8944501180000000102"
    F_IMSI_S1 = make_imsi(MODULE, 30001)
    T_IMSI_S1 = make_imsi(MODULE, 30002)
    F_IMSI_S2 = make_imsi(MODULE, 40001)
    T_IMSI_S2 = make_imsi(MODULE, 40002)

    @classmethod
    def setup_class(cls):
        _force_clear_range_profiles(cls.F_IMSI_S1, cls.T_IMSI_S2)
        with _new_client() as c:
            cls.pool_s1_internet_id = create_pool(
                c, subnet="100.65.210.64/28",
                pool_name="m5b-s1-internet", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_s1_ims_id = create_pool(
                c, subnet="100.65.210.80/28",
                pool_name="m5b-s1-ims", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_s2_id = create_pool(
                c, subnet="100.65.210.96/28",
                pool_name="m5b-s2", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]

            iccid_rc = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID, t_iccid=cls.T_ICCID,
                ip_resolution="imsi_apn",
                imsi_count=2,
            )
            cls.iccid_range_id = iccid_rc["id"]

            # Slot 1: APN pools configured
            slot1 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI_S1, t_imsi=cls.T_IMSI_S1,
                imsi_slot=1, ip_resolution="imsi_apn",
            )
            cls.slot1_rc_id = slot1["range_config_id"]
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_INTERNET, pool_id=cls.pool_s1_internet_id)
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_IMS, pool_id=cls.pool_s1_ims_id)

            # Slot 2: has pool_id but deliberately NO APN catalog entries
            slot2 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI_S2, t_imsi=cls.T_IMSI_S2,
                imsi_slot=2, ip_resolution="imsi_apn",
                pool_id=cls.pool_s2_id,
            )
            cls.slot2_rc_id = slot2["range_config_id"]

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.iccid_range_id:
                delete_iccid_range_config(c, cls.iccid_range_id)
            for pid in [cls.pool_s1_internet_id, cls.pool_s1_ims_id, cls.pool_s2_id]:
                if pid:
                    delete_pool(c, pid)

    # 18.M5b.1 ────────────────────────────────────────────────────────────────
    def test_01_first_connect_fails_422_when_sibling_has_no_apn_config(self, http: httpx.Client):
        """first-connect on slot-1 IMSI → 422 missing_apn_config (sibling slot-2 has no APN entries)."""
        r = _fc(http, self.F_IMSI_S1, APN_INTERNET)
        assert r.status_code == 422, (
            f"Expected 422 missing_apn_config because sibling slot-2 has no APN pools, "
            f"got {r.status_code}: {r.text}"
        )
        body = r.json()
        # The app's exception handler returns the detail dict at the top level.
        assert body.get("error") == "missing_apn_config", \
            f"Expected error='missing_apn_config' at top level, got: {body}"

    # 18.M5b.2 ────────────────────────────────────────────────────────────────
    def test_02_no_profile_created_on_422(self, http: httpx.Client):
        """Transaction rolled back on 422 — no sim_profile created for slot-1 IMSI."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI_S1})
        # 404 means no profile exists; 200 with empty list also means no profile.
        if r.status_code == 404:
            return  # no profile — correct
        assert r.status_code == 200, f"Unexpected status: {r.status_code} {r.text}"
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert not profiles, \
            f"Profile must not exist after rolled-back first-connect, got: {profiles}"

    # 18.M5b.3 ────────────────────────────────────────────────────────────────
    def test_03_after_adding_apn_pools_to_slot2_connect_succeeds(self, http: httpx.Client):
        """After configuring APN pools on slot-2, first-connect on slot-1 → 201."""
        with _new_client() as c:
            add_apn_pool(c, range_config_id=self.slot2_rc_id,
                         apn=APN_INTERNET, pool_id=self.pool_s2_id)
            add_apn_pool(c, range_config_id=self.slot2_rc_id,
                         apn=APN_IMS, pool_id=self.pool_s2_id)

        r = _fc(http, self.F_IMSI_S1, APN_INTERNET)
        assert r.status_code == 201, \
            f"Expected 201 after slot-2 APN pools configured: {r.status_code} {r.text}"
        assert r.json().get("static_ip"), f"Expected non-null IP: {r.json()}"

    # 18.M5b.4 ────────────────────────────────────────────────────────────────
    def test_04_slot2_pre_provisioned_after_fix(self, http: httpx.Client):
        """After fix, slot-2 is pre-provisioned with both APNs from its own pool."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI_S2})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles, "Slot-2 must be pre-provisioned after slot-1 first-connect"
        imsis = profiles[0].get("imsis", [])
        slot2_entry = next((i for i in imsis if i["imsi"] == self.F_IMSI_S2), None)
        assert slot2_entry, "Slot-2 IMSI must appear on profile"
        apns = {e["apn"] for e in slot2_entry.get("apn_ips", [])}
        assert APN_INTERNET in apns and APN_IMS in apns, \
            f"Slot-2 must have both APNs provisioned, got: {apns}"
        for entry in slot2_entry.get("apn_ips", []):
            assert _in_subnet(entry["static_ip"], "100.65.210.96/28"), \
                f"Slot-2 IP {entry['static_ip']} must come from pool_s2 subnet"


# ══════════════════════════════════════════════════════════════════════════════
# M6 — iccid mode, both slot pool_ids are NULL, parent pool provides COALESCE
# ══════════════════════════════════════════════════════════════════════════════

class TestM6_Iccid_NullSlotPool:
    """M6: iccid mode, slots created with pool_id=None, parent range supplies the pool."""

    pool_id:         str = ""
    iccid_range_id:  int = 0

    F_ICCID = make_iccid(MODULE, 201)   # "8944501180000000201"
    T_ICCID = make_iccid(MODULE, 202)   # "8944501180000000202"
    F_IMSI_S1 = make_imsi(MODULE, 50001)
    T_IMSI_S1 = make_imsi(MODULE, 50002)
    F_IMSI_S2 = make_imsi(MODULE, 60001)
    T_IMSI_S2 = make_imsi(MODULE, 60002)

    @classmethod
    def setup_class(cls):
        _force_clear_range_profiles(cls.F_IMSI_S1, cls.T_IMSI_S2)
        with _new_client() as c:
            cls.pool_id = create_pool(
                c, subnet="100.65.210.112/28",
                pool_name="m6-parent", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]

            # Parent has pool_id; slots do NOT
            iccid_rc = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID, t_iccid=cls.T_ICCID,
                ip_resolution="iccid",
                pool_id=cls.pool_id,
                imsi_count=2,
            )
            cls.iccid_range_id = iccid_rc["id"]

            # Both slots: NO pool_id → COALESCE with parent pool at query time
            add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI_S1, t_imsi=cls.T_IMSI_S1,
                imsi_slot=1, ip_resolution="iccid",
            )
            add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI_S2, t_imsi=cls.T_IMSI_S2,
                imsi_slot=2, ip_resolution="iccid",
            )

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.iccid_range_id:
                delete_iccid_range_config(c, cls.iccid_range_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # 18.M6.1 ─────────────────────────────────────────────────────────────────
    def test_01_first_connection_returns_201(self, http: httpx.Client):
        """first-connection on slot-1 IMSI (iccid mode, null slot pool) → 201."""
        r = _fc(http, self.F_IMSI_S1, APN_INTERNET)
        assert r.status_code == 201, f"Expected 201: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("static_ip"), f"Expected non-null IP: {body}"
        assert _in_subnet(body["static_ip"], "100.65.210.112/28"), \
            f"IP {body['static_ip']} not in parent pool subnet"

    # 18.M6.2 ─────────────────────────────────────────────────────────────────
    def test_02_both_slots_share_same_sim_id(self, http: httpx.Client):
        """Both slot IMSIs are on the same sim_profile (shared card-level IP)."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI_S1})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles
        profile = profiles[0]
        imsi_list = [i["imsi"] for i in profile.get("imsis", [])]
        assert self.F_IMSI_S1 in imsi_list, "Slot-1 IMSI must be on profile"
        assert self.F_IMSI_S2 in imsi_list, "Slot-2 IMSI must be on same profile"

    # 18.M6.3 ─────────────────────────────────────────────────────────────────
    def test_03_slot2_connect_is_idempotent(self, http: httpx.Client):
        """first-connection on slot-2 IMSI (pre-provisioned) → 200."""
        r = _fc(http, self.F_IMSI_S2, APN_INTERNET)
        assert r.status_code == 200, f"Expected 200 (idempotent): {r.status_code} {r.text}"
        assert r.json().get("static_ip"), "Must return the shared IP"


# ══════════════════════════════════════════════════════════════════════════════
# M7 — iccid_apn mode, slot1 has APN pools + no pool_id, slot2 has no pool/APNs
# ══════════════════════════════════════════════════════════════════════════════

class TestM7_IccidApn_NullSlotPool:
    """M7: iccid_apn, slot1 drives card-level IPs via APN catalog, slot2 is empty."""

    pool_internet_id: str = ""
    pool_ims_id:      str = ""
    iccid_range_id:   int = 0
    slot1_rc_id:      int = 0

    F_ICCID = make_iccid(MODULE, 301)   # "8944501180000000301"
    T_ICCID = make_iccid(MODULE, 302)   # "8944501180000000302"
    F_IMSI_S1 = make_imsi(MODULE, 70001)
    T_IMSI_S1 = make_imsi(MODULE, 70002)
    F_IMSI_S2 = make_imsi(MODULE, 80001)
    T_IMSI_S2 = make_imsi(MODULE, 80002)

    @classmethod
    def setup_class(cls):
        _force_clear_range_profiles(cls.F_IMSI_S1, cls.T_IMSI_S2)
        with _new_client() as c:
            cls.pool_internet_id = create_pool(
                c, subnet="100.65.210.128/28",
                pool_name="m7-internet", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_ims_id = create_pool(
                c, subnet="100.65.210.144/28",
                pool_name="m7-ims", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]

            # Parent: no pool_id; fully APN-driven
            iccid_rc = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID, t_iccid=cls.T_ICCID,
                ip_resolution="iccid_apn",
                imsi_count=2,
            )
            cls.iccid_range_id = iccid_rc["id"]

            # Slot 1: NO pool_id, APN catalog drives card-level IPs
            slot1 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI_S1, t_imsi=cls.T_IMSI_S1,
                imsi_slot=1, ip_resolution="iccid_apn",
            )
            cls.slot1_rc_id = slot1["range_config_id"]
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_INTERNET, pool_id=cls.pool_internet_id)
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_IMS, pool_id=cls.pool_ims_id)

            # Slot 2: NO pool_id, NO APN catalog (in iccid_apn mode, slot2 only gets imsi2sim)
            add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI_S2, t_imsi=cls.T_IMSI_S2,
                imsi_slot=2, ip_resolution="iccid_apn",
            )

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.iccid_range_id:
                delete_iccid_range_config(c, cls.iccid_range_id)
            for pid in [cls.pool_internet_id, cls.pool_ims_id]:
                if pid:
                    delete_pool(c, pid)

    # 18.M7.1 ─────────────────────────────────────────────────────────────────
    def test_01_first_connection_returns_201(self, http: httpx.Client):
        """first-connection on slot-1 IMSI (iccid_apn, no slot pool_id) → 201."""
        r = _fc(http, self.F_IMSI_S1, APN_INTERNET)
        assert r.status_code == 201, f"Expected 201: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("static_ip"), f"Expected non-null IP: {body}"
        assert _in_subnet(body["static_ip"], "100.65.210.128/28"), \
            f"IP {body['static_ip']} not in internet pool subnet"

    # 18.M7.2 ─────────────────────────────────────────────────────────────────
    def test_02_card_has_two_apn_ips(self, http: httpx.Client):
        """Card (sim_profile) has 2 APN-level IPs: internet + IMS."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI_S1})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles
        profile = profiles[0]
        iccid_ips = profile.get("iccid_ips", [])
        apns = {e["apn"] for e in iccid_ips}
        assert len(apns) == 2, f"Expected 2 card-level APN IPs, got {len(apns)}: {apns}"
        assert APN_INTERNET in apns
        assert APN_IMS in apns

    # 18.M7.3 ─────────────────────────────────────────────────────────────────
    def test_03_slot2_imsi_linked_to_same_profile(self, http: httpx.Client):
        """Slot-2 IMSI is linked to the same sim_profile via imsi2sim."""
        r = http.get("/profiles", params={"imsi": self.F_IMSI_S2})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        assert profiles, "Slot-2 IMSI must be linked to a profile"
        imsi_list = [i["imsi"] for i in profiles[0].get("imsis", [])]
        assert self.F_IMSI_S1 in imsi_list
        assert self.F_IMSI_S2 in imsi_list

    # 18.M7.4 ─────────────────────────────────────────────────────────────────
    def test_04_ims_apn_is_idempotent(self, http: httpx.Client):
        """first-connection on IMS APN (already provisioned) → 200."""
        r = _fc(http, self.F_IMSI_S1, APN_IMS)
        assert r.status_code == 200, f"Expected 200 (idempotent): {r.status_code} {r.text}"
        body = r.json()
        assert body.get("static_ip")
        assert _in_subnet(body["static_ip"], "100.65.210.144/28"), \
            f"IMS IP {body['static_ip']} not in IMS pool subnet"


# ══════════════════════════════════════════════════════════════════════════════
# M8 — immediate mode, imsi_apn, last slot has NO APN config
#       → job must end with completed_with_errors + clear "missing_apn_config" message
#       (Bug 2: previously inserted apn=NULL rows silently)
# ══════════════════════════════════════════════════════════════════════════════

class TestM8_Immediate_MissingApnConfig:
    """M8: immediate mode, last slot without APN config → completed_with_errors (Bug 2)."""

    pool_s1_internet_id: str = ""
    pool_s1_ims_id:      str = ""
    iccid_range_id:      int = 0
    slot1_rc_id:         int = 0
    job_id:              str = ""

    F_ICCID = make_iccid(MODULE, 401)   # "8944501180000000401"
    T_ICCID = make_iccid(MODULE, 402)   # "8944501180000000402"
    F_IMSI_S1 = make_imsi(MODULE, 90001)
    T_IMSI_S1 = make_imsi(MODULE, 90002)
    F_IMSI_S2 = make_imsi(MODULE, 91001)
    T_IMSI_S2 = make_imsi(MODULE, 91002)

    @classmethod
    def setup_class(cls):
        _force_clear_range_profiles(cls.F_IMSI_S1, cls.T_IMSI_S2)
        with _new_client() as c:
            cls.pool_s1_internet_id = create_pool(
                c, subnet="100.65.210.160/28",
                pool_name="m8-s1-internet", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]
            cls.pool_s1_ims_id = create_pool(
                c, subnet="100.65.210.176/28",
                pool_name="m8-s1-ims", account_name="TestAccount",
                replace_on_conflict=True,
            )["pool_id"]

            iccid_rc = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID, t_iccid=cls.T_ICCID,
                ip_resolution="imsi_apn",
                imsi_count=2,
                provisioning_mode="immediate",
            )
            cls.iccid_range_id = iccid_rc["id"]

            # Slot 1: not the last slot — no job fires yet
            slot1 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI_S1, t_imsi=cls.T_IMSI_S1,
                imsi_slot=1, ip_resolution="imsi_apn",
            )
            cls.slot1_rc_id = slot1["range_config_id"]
            # Configure APN pools for slot 1
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_INTERNET, pool_id=cls.pool_s1_internet_id)
            add_apn_pool(c, range_config_id=cls.slot1_rc_id,
                         apn=APN_IMS, pool_id=cls.pool_s1_ims_id)

            # Slot 2: LAST slot, NO APN pools configured → immediate job fires
            slot2 = add_imsi_slot(
                c, iccid_range_id=cls.iccid_range_id,
                f_imsi=cls.F_IMSI_S2, t_imsi=cls.T_IMSI_S2,
                imsi_slot=2, ip_resolution="imsi_apn",
            )
            cls.job_id = slot2.get("job_id", "")

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.iccid_range_id:
                delete_iccid_range_config(c, cls.iccid_range_id)
            for pid in [cls.pool_s1_internet_id, cls.pool_s1_ims_id]:
                if pid:
                    delete_pool(c, pid)

    # 18.M8.1 ─────────────────────────────────────────────────────────────────
    def test_01_last_slot_add_returns_job_id(self):
        """Adding last slot in immediate mode must return a job_id."""
        assert self.job_id, \
            "Last-slot add must include job_id in response for immediate provisioning_mode"

    # 18.M8.2 ─────────────────────────────────────────────────────────────────
    def test_02_job_ends_with_completed_with_errors(self, http: httpx.Client):
        """Immediate job ends with completed_with_errors (not silent success) — Bug 2 guard."""
        job = _wait_for_job(http, self.job_id)
        assert job["status"] == "completed_with_errors", (
            f"Expected completed_with_errors because slot-2 has no APN config, "
            f"got status={job['status']}: {job.get('errors')}"
        )
        assert job.get("failed", 0) > 0, \
            f"Expected failed > 0 in job, got: {job}"

    # 18.M8.3 ─────────────────────────────────────────────────────────────────
    def test_03_error_message_names_missing_apn_config(self, http: httpx.Client):
        """Job error messages must contain 'missing_apn_config' for slot-2 cards."""
        job = _wait_for_job(http, self.job_id)
        errors = job.get("errors", [])
        assert errors, "Job must have at least one error entry"
        all_messages = " ".join(str(e.get("message", "")) for e in errors)
        assert "missing_apn_config" in all_messages, (
            f"Expected 'missing_apn_config' in error messages, got: {all_messages}"
        )

    # 18.M8.4 ─────────────────────────────────────────────────────────────────
    def test_04_no_apn_null_rows_for_slot2(self, http: httpx.Client):
        """No apn=NULL rows inserted for slot-2 IMSIs (the old silent-corruption path)."""
        # Slot-2 IMSIs must not appear in any profile (no silent partial provisioning)
        r = http.get("/profiles", params={"imsi": self.F_IMSI_S2})
        assert r.status_code == 200
        profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
        if profiles:
            # If a profile exists (slot-1 provisioned it), ensure slot-2 IMSI
            # has no apn_ips entries with apn=None
            for profile in profiles:
                for imsi_entry in profile.get("imsis", []):
                    if imsi_entry["imsi"] == self.F_IMSI_S2:
                        null_apns = [
                            e for e in imsi_entry.get("apn_ips", [])
                            if e.get("apn") is None
                        ]
                        assert not null_apns, \
                            f"Slot-2 must not have apn=NULL rows: {null_apns}"
