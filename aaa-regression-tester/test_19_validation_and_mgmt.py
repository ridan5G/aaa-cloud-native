"""
test_19_validation_and_mgmt.py — ICCID/IMSI Range Config validation + APN-pool management.

Five test groups:

  A — ICCID Range creation validation (invalid ICCID format, inverted range, bad imsi_count,
      invalid ip_resolution)
  B — IMSI Slot validation (invalid IMSI format, inverted range, out-of-bounds slot number,
      cardinality mismatch, duplicate slot)
  C — APN Pool management CRUD (list, add, duplicate rejection, bad pool, delete, 404 cases)
  D — Skip ICCID range (create config without ICCID bounds → IMSI-only SIM group;
      first-connection by IMSI still works)
  E — Size alignment (all IMSI slots and the ICCID range must share the same cardinality;
      PATCH revalidates on range update)

Resources
─────────
  Module 19 → IMSI prefix 27877 19 xxxxxxxx  (no conflict with other modules)
              ICCID prefix 8944501 19 xxxxxxxxxx

  Pools (100.65.220.x/28 — 14 usable IPs each):
    B  — 100.65.220.0/28
    C  — 100.65.220.16/28  (primary / internet APN)
         100.65.220.32/28  (secondary / IMS APN)
    D  — 100.65.220.48/28
    E  — 100.65.220.64/28

  ICCID ranges (all 19-digit):
    B  — 8944501190000000001 … 8944501190000000010  (10 cards)
    C  — 8944501190000000101 … 8944501190000000105  (5 cards)
    D  — (none — skip-ICCID mode)
    E  — 8944501190000001001 … 8944501190000001005  (5 cards)
"""
import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID, make_imsi, make_iccid
from fixtures.pools import create_pool, delete_pool, _force_clear_range_profiles
from fixtures.range_configs import (
    create_iccid_range_config,
    add_imsi_slot,
    delete_iccid_range_config,
)

MODULE = 19

APN_INTERNET = "internet.operator.com"
APN_IMS      = "ims.operator.com"


def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=30.0,
    )


def _fc(http: httpx.Client, imsi: str, apn: str = APN_INTERNET) -> httpx.Response:
    return http.post(
        "/first-connection",
        json={"imsi": imsi, "apn": apn, "use_case_id": USE_CASE_ID},
    )


# ─── A: ICCID Range creation validation ──────────────────────────────────────

class TestIccidRangeValidation:
    """
    All tests POST /iccid-range-configs with invalid fields and expect 400
    validation_failed.  No pool or cleanup needed — every request is rejected
    before any DB write.
    """

    F = make_iccid(MODULE, 1)   # 8944501190000000001
    T = make_iccid(MODULE, 10)  # 8944501190000000010

    # A.1 ─────────────────────────────────────────────────────────────────────
    def test_01_inverted_iccid_range(self, http: httpx.Client):
        """f_iccid > t_iccid → 400 validation_failed."""
        resp = http.post("/iccid-range-configs", json={
            "f_iccid": self.T,
            "t_iccid": self.F,   # inverted
            "ip_resolution": "iccid",
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # A.2 ─────────────────────────────────────────────────────────────────────
    def test_02_f_iccid_too_short(self, http: httpx.Client):
        """18-digit f_iccid → 400 validation_failed."""
        resp = http.post("/iccid-range-configs", json={
            "f_iccid": "894450119000000001",   # 18 digits
            "t_iccid": self.T,
            "ip_resolution": "iccid",
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # A.3 ─────────────────────────────────────────────────────────────────────
    def test_03_t_iccid_too_long(self, http: httpx.Client):
        """21-digit t_iccid → 400 validation_failed."""
        resp = http.post("/iccid-range-configs", json={
            "f_iccid": self.F,
            "t_iccid": "894450119000000001000",  # 21 digits
            "ip_resolution": "iccid",
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # A.4 ─────────────────────────────────────────────────────────────────────
    def test_04_f_iccid_non_numeric(self, http: httpx.Client):
        """Non-numeric f_iccid → 400 validation_failed."""
        resp = http.post("/iccid-range-configs", json={
            "f_iccid": "ABCDE01190000000001",
            "t_iccid": self.T,
            "ip_resolution": "iccid",
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # A.5 ─────────────────────────────────────────────────────────────────────
    def test_05_only_one_iccid_provided(self, http: httpx.Client):
        """Providing f_iccid but not t_iccid → 400 validation_failed."""
        resp = http.post("/iccid-range-configs", json={
            "f_iccid": self.F,
            "ip_resolution": "iccid",
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # A.6 ─────────────────────────────────────────────────────────────────────
    def test_06_imsi_count_zero(self, http: httpx.Client):
        """imsi_count=0 → 400 validation_failed."""
        resp = http.post("/iccid-range-configs", json={
            "f_iccid": self.F,
            "t_iccid": self.T,
            "ip_resolution": "iccid",
            "imsi_count": 0,
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # A.7 ─────────────────────────────────────────────────────────────────────
    def test_07_imsi_count_too_large(self, http: httpx.Client):
        """imsi_count=11 → 400 validation_failed."""
        resp = http.post("/iccid-range-configs", json={
            "f_iccid": self.F,
            "t_iccid": self.T,
            "ip_resolution": "iccid",
            "imsi_count": 11,
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"

    # A.8 ─────────────────────────────────────────────────────────────────────
    def test_08_invalid_ip_resolution(self, http: httpx.Client):
        """Unknown ip_resolution value → 400 validation_failed."""
        resp = http.post("/iccid-range-configs", json={
            "f_iccid": self.F,
            "t_iccid": self.T,
            "ip_resolution": "foobar",
        })
        assert resp.status_code == 400
        assert resp.json().get("error") == "validation_failed"


# ─── B: IMSI Slot validation ──────────────────────────────────────────────────

class TestImsiSlotValidation:
    """
    Tests POST /iccid-range-configs/{id}/imsi-slots with invalid inputs.
    Uses a 10-card ICCID range (diff=9); valid slots must match this cardinality.
    """

    pool_id:    str | None = None
    range_id:   int | None = None

    F_ICCID = make_iccid(MODULE, 1)    # 8944501190000000001
    T_ICCID = make_iccid(MODULE, 10)   # 8944501190000000010  (10 cards, diff=9)

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            p = create_pool(c, subnet="100.65.220.0/28",
                            pool_name="t19b-pool", replace_on_conflict=True)
            cls.pool_id = p["pool_id"]
            r = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID,
                t_iccid=cls.T_ICCID,
                ip_resolution="imsi",
                imsi_count=1,
                pool_id=cls.pool_id,
            )
            cls.range_id = r["id"]

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_iccid_range_config(c, cls.range_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    def _post_slot(self, http, f_imsi, t_imsi, slot=1, **extra):
        return http.post(
            f"/iccid-range-configs/{self.range_id}/imsi-slots",
            json={"f_imsi": f_imsi, "t_imsi": t_imsi, "imsi_slot": slot, **extra},
        )

    # B.1 ─────────────────────────────────────────────────────────────────────
    def test_01_inverted_imsi_range(self, http: httpx.Client):
        """f_imsi > t_imsi → 400 validation_failed."""
        f = make_imsi(MODULE, 10)
        t = make_imsi(MODULE, 1)
        resp = self._post_slot(http, f, t)
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_failed"

    # B.2 ─────────────────────────────────────────────────────────────────────
    def test_02_f_imsi_too_short(self, http: httpx.Client):
        """14-digit f_imsi → 400 validation_failed."""
        resp = self._post_slot(http, "27877190000001", make_imsi(MODULE, 10))
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_failed"

    # B.3 ─────────────────────────────────────────────────────────────────────
    def test_03_t_imsi_too_long(self, http: httpx.Client):
        """16-digit t_imsi → 400 validation_failed."""
        resp = self._post_slot(http, make_imsi(MODULE, 1), "2787719000000100")
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_failed"

    # B.4 ─────────────────────────────────────────────────────────────────────
    def test_04_imsi_slot_zero(self, http: httpx.Client):
        """imsi_slot=0 → 400 validation_failed."""
        resp = self._post_slot(http, make_imsi(MODULE, 1), make_imsi(MODULE, 10), slot=0)
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_failed"

    # B.5 ─────────────────────────────────────────────────────────────────────
    def test_05_imsi_slot_too_large(self, http: httpx.Client):
        """imsi_slot=11 → 400 validation_failed."""
        resp = self._post_slot(http, make_imsi(MODULE, 1), make_imsi(MODULE, 10), slot=11)
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_failed"

    # B.6 ─────────────────────────────────────────────────────────────────────
    def test_06_cardinality_too_many(self, http: httpx.Client):
        """11 IMSIs for a 10-card ICCID range → 400 cardinality mismatch."""
        resp = self._post_slot(http, make_imsi(MODULE, 1), make_imsi(MODULE, 11))  # diff=10, iccid diff=9
        assert resp.status_code == 400
        detail = resp.json()
        assert detail["error"] == "validation_failed"
        assert "cardinality" in detail["details"][0]["message"]

    # B.7 ─────────────────────────────────────────────────────────────────────
    def test_07_cardinality_too_few(self, http: httpx.Client):
        """9 IMSIs for a 10-card ICCID range → 400 cardinality mismatch."""
        resp = self._post_slot(http, make_imsi(MODULE, 1), make_imsi(MODULE, 9))   # diff=8, iccid diff=9
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_failed"

    # B.8 ─────────────────────────────────────────────────────────────────────
    def test_08_valid_slot_accepted(self, http: httpx.Client):
        """Exactly 10 IMSIs for a 10-card ICCID range → 201."""
        resp = self._post_slot(http, make_imsi(MODULE, 1), make_imsi(MODULE, 10))  # diff=9 ✓
        assert resp.status_code == 201
        assert "range_config_id" in resp.json()
        TestImsiSlotValidation._slot_range_config_id = resp.json()["range_config_id"]

    # B.9 ─────────────────────────────────────────────────────────────────────
    def test_09_duplicate_slot_rejected(self, http: httpx.Client):
        """Re-posting slot 1 with same IMSI range → 400 slot already exists."""
        resp = self._post_slot(http, make_imsi(MODULE, 1), make_imsi(MODULE, 10))
        assert resp.status_code == 400
        detail = resp.json()
        assert detail["error"] == "validation_failed"
        assert "already exists" in detail["details"][0]["message"]


# ─── C: APN Pool management ───────────────────────────────────────────────────

class TestApnPoolManagement:
    """
    CRUD operations on /iccid-range-configs/{id}/imsi-slots/{slot}/apn-pools.
    Uses a 5-card range with a single imsi_apn slot and two pools (internet, IMS).
    """

    pool_internet_id: str | None = None
    pool_ims_id:      str | None = None
    range_id:         int | None = None

    F_ICCID = make_iccid(MODULE, 101)   # 8944501190000000101
    T_ICCID = make_iccid(MODULE, 105)   # 8944501190000000105  (5 cards, diff=4)
    SLOT = 1

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            pi = create_pool(c, subnet="100.65.220.16/28",
                             pool_name="t19c-internet", replace_on_conflict=True)
            cls.pool_internet_id = pi["pool_id"]
            pims = create_pool(c, subnet="100.65.220.32/28",
                               pool_name="t19c-ims", replace_on_conflict=True)
            cls.pool_ims_id = pims["pool_id"]

            r = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID,
                t_iccid=cls.T_ICCID,
                ip_resolution="imsi_apn",
                imsi_count=1,
            )
            cls.range_id = r["id"]
            # Add the slot (diff=4 for 5-card range)
            add_imsi_slot(
                c,
                iccid_range_id=cls.range_id,
                f_imsi=make_imsi(MODULE, 101),
                t_imsi=make_imsi(MODULE, 105),
                imsi_slot=cls.SLOT,
                ip_resolution="imsi_apn",
            )

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_iccid_range_config(c, cls.range_id)
            if cls.pool_internet_id:
                delete_pool(c, cls.pool_internet_id)
            if cls.pool_ims_id:
                delete_pool(c, cls.pool_ims_id)

    def _apn_url(self, apn: str | None = None) -> str:
        base = f"/iccid-range-configs/{self.range_id}/imsi-slots/{self.SLOT}/apn-pools"
        return f"{base}/{apn}" if apn else base

    # C.1 ─────────────────────────────────────────────────────────────────────
    def test_01_get_apn_pools_initially_empty(self, http: httpx.Client):
        """GET apn-pools on a fresh slot → 200, items=[]."""
        resp = http.get(self._apn_url())
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    # C.2 ─────────────────────────────────────────────────────────────────────
    def test_02_add_internet_apn_pool(self, http: httpx.Client):
        """POST internet APN → 201, returns id/apn/pool_id."""
        resp = http.post(self._apn_url(), json={
            "apn": APN_INTERNET,
            "pool_id": self.pool_internet_id,
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["apn"] == APN_INTERNET
        assert body["pool_id"] == self.pool_internet_id
        assert "id" in body

    # C.3 ─────────────────────────────────────────────────────────────────────
    def test_03_list_includes_internet(self, http: httpx.Client):
        """GET after adding internet APN → 200, items has one entry."""
        resp = http.get(self._apn_url())
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["apn"] == APN_INTERNET

    # C.4 ─────────────────────────────────────────────────────────────────────
    def test_04_add_ims_apn_pool(self, http: httpx.Client):
        """POST IMS APN → 201."""
        resp = http.post(self._apn_url(), json={
            "apn": APN_IMS,
            "pool_id": self.pool_ims_id,
        })
        assert resp.status_code == 201
        assert resp.json()["apn"] == APN_IMS

    # C.5 ─────────────────────────────────────────────────────────────────────
    def test_05_list_has_two_entries(self, http: httpx.Client):
        """GET after adding IMS APN → 200, items has two entries."""
        resp = http.get(self._apn_url())
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        apns = {i["apn"] for i in items}
        assert apns == {APN_INTERNET, APN_IMS}

    # C.6 ─────────────────────────────────────────────────────────────────────
    def test_06_duplicate_apn_rejected(self, http: httpx.Client):
        """POST internet APN again → 400 'already has a pool override'."""
        resp = http.post(self._apn_url(), json={
            "apn": APN_INTERNET,
            "pool_id": self.pool_internet_id,
        })
        assert resp.status_code == 400
        detail = resp.json()
        assert detail["error"] == "validation_failed"
        assert "already" in detail["details"][0]["message"]

    # C.7 ─────────────────────────────────────────────────────────────────────
    def test_07_nonexistent_pool_id_rejected(self, http: httpx.Client):
        """POST with a made-up pool_id UUID → 400 'pool not found'."""
        resp = http.post(self._apn_url(), json={
            "apn": "other.apn",
            "pool_id": "00000000-0000-0000-0000-000000000000",
        })
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_failed"

    # C.8 ─────────────────────────────────────────────────────────────────────
    def test_08_delete_internet_apn(self, http: httpx.Client):
        """DELETE internet APN → 204."""
        resp = http.delete(self._apn_url(APN_INTERNET))
        assert resp.status_code == 204

    # C.9 ─────────────────────────────────────────────────────────────────────
    def test_09_list_after_delete_has_one(self, http: httpx.Client):
        """GET after deleting internet → 200, only IMS remains."""
        resp = http.get(self._apn_url())
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["apn"] == APN_IMS

    # C.10 ────────────────────────────────────────────────────────────────────
    def test_10_delete_nonexistent_apn(self, http: httpx.Client):
        """DELETE already-removed APN → 404."""
        resp = http.delete(self._apn_url(APN_INTERNET))
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"

    # C.11 ────────────────────────────────────────────────────────────────────
    def test_11_get_on_missing_slot_returns_404(self, http: httpx.Client):
        """GET apn-pools for a non-existent slot number → 404."""
        resp = http.get(
            f"/iccid-range-configs/{self.range_id}/imsi-slots/99/apn-pools"
        )
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"


# ─── D: Skip ICCID range ──────────────────────────────────────────────────────

class TestSkipIccidRange:
    """
    Create a SIM Range Config without specifying f_iccid/t_iccid.
    The config acts as an IMSI-only SIM group — no ICCID bounds, no cardinality
    constraint on slot IMSI ranges, first-connection still works by IMSI.
    """

    pool_id:  str | None = None
    range_id: int | None = None

    # IMSI slot range used by this class (any cardinality is valid for skip-ICCID configs)
    _F_SLOT_IMSI = make_imsi(MODULE, 500)
    _T_SLOT_IMSI = make_imsi(MODULE, 507)

    @classmethod
    def setup_class(cls):
        # Remove stale profiles from any prior interrupted run before provisioning.
        _force_clear_range_profiles(cls._F_SLOT_IMSI, cls._T_SLOT_IMSI)
        with _new_client() as c:
            p = create_pool(c, subnet="100.65.220.48/28",
                            pool_name="t19d-pool", replace_on_conflict=True)
            cls.pool_id = p["pool_id"]

    @classmethod
    def teardown_class(cls):
        # Delete auto-created sim_profiles so re-runs get 201 instead of 200.
        _force_clear_range_profiles(cls._F_SLOT_IMSI, cls._T_SLOT_IMSI)
        with _new_client() as c:
            if cls.range_id:
                delete_iccid_range_config(c, cls.range_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # D.1 ─────────────────────────────────────────────────────────────────────
    def test_01_create_without_iccid_range(self, http: httpx.Client):
        """POST /iccid-range-configs with no f_iccid/t_iccid → 201."""
        resp = http.post("/iccid-range-configs", json={
            "account_name":  "TestAccount",
            "ip_resolution": "imsi",
            "imsi_count":    1,
            "pool_id":       TestSkipIccidRange.pool_id,
        })
        assert resp.status_code == 201, resp.text
        TestSkipIccidRange.range_id = resp.json()["id"]

    # D.2 ─────────────────────────────────────────────────────────────────────
    def test_03_add_slot_any_cardinality(self, http: httpx.Client):
        """Slot on a skip-ICCID config accepts any IMSI range size (no cardinality check)."""
        resp = http.post(
            f"/iccid-range-configs/{TestSkipIccidRange.range_id}/imsi-slots",
            json={
                "f_imsi":    make_imsi(MODULE, 500),
                "t_imsi":    make_imsi(MODULE, 507),   # 8 IMSIs — no cardinality constraint
                "imsi_slot": 1,
                "pool_id":   TestSkipIccidRange.pool_id,
            },
        )
        assert resp.status_code == 201, resp.text

    # D.4 ─────────────────────────────────────────────────────────────────────
    def test_04_first_connection_by_imsi_works(self, http: httpx.Client):
        """POST /first-connection with an IMSI in the skip-ICCID slot → 201, IP allocated."""
        resp = _fc(http, make_imsi(MODULE, 500))
        assert resp.status_code == 201, resp.text
        assert resp.json().get("static_ip") is not None


# ─── E: Size alignment ────────────────────────────────────────────────────────

class TestSizeAlignment:
    """
    All IMSI slots added to an ICCID range config must have the same cardinality
    as the ICCID range.  PATCH on a slot also revalidates cardinality.

    Uses a 5-card range (diff=4):
      Slot 1: make_imsi(19, 1001) … make_imsi(19, 1005)  (diff=4 ✓)
      Slot 2 bad: diff=3 or diff=5 → 400
      Slot 2 good: diff=4 ✓
    """

    pool_id:  str | None = None
    range_id: int | None = None

    F_ICCID = make_iccid(MODULE, 1001)   # 8944501190000001001
    T_ICCID = make_iccid(MODULE, 1005)   # 8944501190000001005  (5 cards, diff=4)

    @classmethod
    def setup_class(cls):
        with _new_client() as c:
            p = create_pool(c, subnet="100.65.220.64/28",
                            pool_name="t19e-pool", replace_on_conflict=True)
            cls.pool_id = p["pool_id"]
            r = create_iccid_range_config(
                c,
                f_iccid=cls.F_ICCID,
                t_iccid=cls.T_ICCID,
                ip_resolution="imsi",
                imsi_count=2,
                pool_id=cls.pool_id,
            )
            cls.range_id = r["id"]
            # Add slot 1 with correct cardinality (diff=4)
            add_imsi_slot(
                c,
                iccid_range_id=cls.range_id,
                f_imsi=make_imsi(MODULE, 1001),
                t_imsi=make_imsi(MODULE, 1005),
                imsi_slot=1,
                ip_resolution="imsi",
                pool_id=cls.pool_id,
            )

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_iccid_range_config(c, cls.range_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # E.1 ─────────────────────────────────────────────────────────────────────
    def test_01_slot2_too_few_imsis(self, http: httpx.Client):
        """Slot 2 with 4 IMSIs (diff=3) for a 5-card ICCID range → 400 cardinality mismatch."""
        resp = http.post(
            f"/iccid-range-configs/{self.range_id}/imsi-slots",
            json={
                "f_imsi":    make_imsi(MODULE, 2001),
                "t_imsi":    make_imsi(MODULE, 2004),   # diff=3, need diff=4
                "imsi_slot": 2,
            },
        )
        assert resp.status_code == 400
        detail = resp.json()
        assert detail["error"] == "validation_failed"
        msg = detail["details"][0]["message"]
        assert "cardinality" in msg
        assert "4" in msg   # cardinality 4 does not match iccid range cardinality 5

    # E.2 ─────────────────────────────────────────────────────────────────────
    def test_02_slot2_too_many_imsis(self, http: httpx.Client):
        """Slot 2 with 6 IMSIs (diff=5) for a 5-card ICCID range → 400 cardinality mismatch."""
        resp = http.post(
            f"/iccid-range-configs/{self.range_id}/imsi-slots",
            json={
                "f_imsi":    make_imsi(MODULE, 3001),
                "t_imsi":    make_imsi(MODULE, 3006),   # diff=5, need diff=4
                "imsi_slot": 2,
            },
        )
        assert resp.status_code == 400
        detail = resp.json()
        assert detail["error"] == "validation_failed"
        assert "cardinality" in detail["details"][0]["message"]

    # E.3 ─────────────────────────────────────────────────────────────────────
    def test_03_slot2_correct_cardinality(self, http: httpx.Client):
        """Slot 2 with exactly 5 IMSIs (diff=4) → 201."""
        resp = http.post(
            f"/iccid-range-configs/{self.range_id}/imsi-slots",
            json={
                "f_imsi":    make_imsi(MODULE, 4001),
                "t_imsi":    make_imsi(MODULE, 4005),   # diff=4 ✓
                "imsi_slot": 2,
                "pool_id":   self.pool_id,
            },
        )
        assert resp.status_code == 201, resp.text

    # E.4 ─────────────────────────────────────────────────────────────────────
    def test_04_patch_slot1_wrong_cardinality(self, http: httpx.Client):
        """PATCH slot 1 with a 4-IMSI range (diff=3) → 400 cardinality mismatch."""
        resp = http.patch(
            f"/iccid-range-configs/{self.range_id}/imsi-slots/1",
            json={
                "f_imsi": make_imsi(MODULE, 5001),
                "t_imsi": make_imsi(MODULE, 5004),   # diff=3, need diff=4
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_failed"

    # E.5 ─────────────────────────────────────────────────────────────────────
    def test_05_patch_slot1_correct_cardinality(self, http: httpx.Client):
        """PATCH slot 1 with a 5-IMSI range (diff=4) → 200."""
        resp = http.patch(
            f"/iccid-range-configs/{self.range_id}/imsi-slots/1",
            json={
                "f_imsi": make_imsi(MODULE, 6001),
                "t_imsi": make_imsi(MODULE, 6005),   # diff=4 ✓
            },
        )
        assert resp.status_code == 200, resp.text

    # E.6 ─────────────────────────────────────────────────────────────────────
    def test_06_all_slots_align_with_iccid_range(self, http: httpx.Client):
        """GET imsi-slots → both slots have the same cardinality as the ICCID range."""
        resp = http.get(f"/iccid-range-configs/{self.range_id}/imsi-slots")
        assert resp.status_code == 200
        slots = resp.json()["items"]
        assert len(slots) == 2
        iccid_diff = int(self.T_ICCID) - int(self.F_ICCID)
        for slot in slots:
            slot_diff = int(slot["t_imsi"]) - int(slot["f_imsi"])
            assert slot_diff == iccid_diff, (
                f"Slot {slot['imsi_slot']} has cardinality {slot_diff + 1} "
                f"but ICCID range has {iccid_diff + 1}"
            )
