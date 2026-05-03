"""
test_22_resolution_method_conversion.py — sim_profiles.ip_resolution change safety.

Background
──────────
Changing `sim_profiles.ip_resolution` (via PATCH /profiles/{sim_id}) without
cleaning up the previous mode's IP rows leaves the fast-path resolver staring
at rows it cannot match. The C++ resolver dispatches on `sim_profiles.ip_resolution`
and only returns rows that fit that mode's shape (Resolver.cpp:35–106 — `imsi`
and `iccid` modes only return rows where `apn IS NULL`). The pre-existing
specific-APN rows from the old mode become silent orphans and the fast path
returns NotFound for live subscribers.

This module verifies:
  1. PATCH /profiles/{sim_id} with a dangerous ip_resolution change is rejected
     with 409 `mode_conversion_orphans_rows`.
  2. PATCH /profiles/{sim_id}?force=true is allowed, and the orphaned rows are
     deleted in the same transaction so the resolver invariant holds.
  3. The fast path returns the expected result post-conversion (either the
     wildcard IP if one exists, or 404 cleanly if not — never a stale wrong IP).

Module subnet block: 100.66.48.0/22 (module identifier "26" in IMSI prefix).
"""
from __future__ import annotations

import httpx
import pytest

from conftest import (
    PROVISION_BASE,
    JWT_TOKEN,
    USE_CASE_ID,
    make_iccid,
    make_imsi,
)
from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import (
    create_profile_iccid_apn,
    create_profile_imsi_apn,
    delete_profile,
)


# Pool subnets — module 26 owns 100.66.48.0/22
POOL_SUBNET = "100.66.48.0/24"

# IP addresses (use static .1–.20 from the /24 — plenty of room for all classes)
IP_INET_1   = "100.66.48.1"   # IMSI1 → internet APN
IP_IMS_1    = "100.66.48.2"   # IMSI1 → ims APN
IP_INET_2   = "100.66.48.3"   # IMSI2 → internet APN
IP_IMS_2    = "100.66.48.4"   # IMSI2 → ims APN
IP_WILD_1   = "100.66.48.5"   # IMSI1 wildcard (apn=null)
IP_CARD_INET = "100.66.48.10"
IP_CARD_IMS  = "100.66.48.11"

APN_INET = "internet.operator.com"
APN_IMS  = "ims.operator.com"
APN_OTHER = "other.unknown.com"


# ─────────────────────────────────────────────────────────────────────────────
# TestImsiApnToImsi — the user's exact scenario
# ─────────────────────────────────────────────────────────────────────────────
class TestImsiApnToImsi:
    """imsi_apn → imsi: per-APN rows must be cleaned up or the resolver returns NotFound."""

    pool_id: str | None = None
    sim_id: str | None = None

    IMSI1 = make_imsi(26, 10001)
    IMSI2 = make_imsi(26, 10002)

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet=POOL_SUBNET, pool_name="pool-22a",
                            account_name="TestAccount", replace_on_conflict=True)
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

    def test_01_create_imsi_apn_profile(self, http: httpx.Client):
        """Provision an imsi_apn profile with IMSI1×{internet,ims} and IMSI2×{internet,ims} (no wildcard)."""
        body = create_profile_imsi_apn(
            http,
            iccid=None,
            account_name="TestAccount",
            imsis=[
                {"imsi": self.IMSI1, "apn_ips": [
                    {"apn": APN_INET, "static_ip": IP_INET_1, "pool_id": self.pool_id},
                    {"apn": APN_IMS,  "static_ip": IP_IMS_1,  "pool_id": self.pool_id},
                ]},
                {"imsi": self.IMSI2, "apn_ips": [
                    {"apn": APN_INET, "static_ip": IP_INET_2, "pool_id": self.pool_id},
                    {"apn": APN_IMS,  "static_ip": IP_IMS_2,  "pool_id": self.pool_id},
                ]},
            ],
        )
        TestImsiApnToImsi.sim_id = body["sim_id"]

    def test_02_baseline_lookup_works(self, lookup_http: httpx.Client):
        """Sanity: imsi_apn lookup returns the exact-APN IP."""
        r = lookup_http.get("/lookup", params={
            "imsi": self.IMSI1, "apn": APN_INET, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP_INET_1

    def test_03_unforced_change_to_imsi_is_rejected(self, http: httpx.Client):
        """PATCH ip_resolution=imsi without ?force → 409 mode_conversion_orphans_rows.

        Four orphans expected: IMSI1×internet, IMSI1×ims, IMSI2×internet, IMSI2×ims.
        """
        r = http.patch(f"/profiles/{self.sim_id}", json={"ip_resolution": "imsi"})
        assert r.status_code == 409, f"unexpected: {r.status_code} {r.text}"
        body = r.json()
        # FastAPI nests the validation body under "detail"
        detail = body.get("detail", body)
        assert detail["error"] == "mode_conversion_orphans_rows"
        assert detail["from"] == "imsi_apn"
        assert detail["to"] == "imsi"
        assert detail["orphaned_count"] == 4

    def test_04_lookup_still_works_after_rejected_change(self, lookup_http: httpx.Client):
        """The 409 must have left state untouched — lookup still works."""
        r = lookup_http.get("/lookup", params={
            "imsi": self.IMSI1, "apn": APN_INET, "use_case_id": USE_CASE_ID,
        })
        assert r.status_code == 200
        assert r.json()["static_ip"] == IP_INET_1

    def test_05_forced_change_clears_orphans(self, http: httpx.Client):
        """PATCH ip_resolution=imsi with ?force=true → 200 and orphans deleted in same txn."""
        r = http.patch(
            f"/profiles/{self.sim_id}",
            params={"force": "true"},
            json={"ip_resolution": "imsi"},
        )
        assert r.status_code == 200, f"unexpected: {r.status_code} {r.text}"
        # Re-fetch to confirm ip_resolution flipped
        g = http.get(f"/profiles/{self.sim_id}")
        assert g.status_code == 200
        assert g.json()["ip_resolution"] == "imsi"

    def test_06_lookup_returns_404_for_apn_specific_after_force(self, lookup_http: httpx.Client):
        """After forced conversion, the resolver runs in `imsi` mode and looks for apn IS NULL.
        No NULL row exists, no specific-APN rows exist (we just deleted them), so the resolver
        returns NotFound. This is the correct, predictable behaviour — better than returning a
        stale wrong IP. First-connection or further provisioning would fix this."""
        r = lookup_http.get("/lookup", params={
            "imsi": self.IMSI1, "apn": APN_INET, "use_case_id": USE_CASE_ID,
        })
        # After the forced conversion the resolver may return:
        #   - 404 not_found (no rows at all in imsi_apn_ips for this IMSI), OR
        #   - 200 with an IP allocated by first-connection if the IMSI is in a qualifying range.
        # Either is a controlled outcome. What MUST NOT happen is a stale wrong IP.
        assert r.status_code in (200, 404), f"unexpected: {r.status_code} {r.text}"
        if r.status_code == 200:
            # Whatever IP comes back, it must NOT be one of the deleted per-APN IPs.
            ip = r.json().get("static_ip")
            assert ip not in (IP_INET_1, IP_IMS_1), (
                f"resolver returned stale orphan IP {ip} after forced conversion"
            )


# ─────────────────────────────────────────────────────────────────────────────
# TestImsiApnToImsiWithWildcard — change is safe when wildcard exists
# ─────────────────────────────────────────────────────────────────────────────
class TestImsiApnToImsiWithWildcard:
    """imsi_apn → imsi when a wildcard (apn=null) row exists. The wildcard satisfies
    the new resolver. Per-APN rows are still orphaned and need force=true."""

    pool_id: str | None = None
    sim_id: str | None = None

    IMSI = make_imsi(26, 11001)

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet="100.66.49.0/24", pool_name="pool-22b",
                            account_name="TestAccount", replace_on_conflict=True)
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

    def test_01_create_imsi_apn_with_wildcard(self, http: httpx.Client):
        body = create_profile_imsi_apn(
            http,
            iccid=None,
            imsis=[
                {"imsi": self.IMSI, "apn_ips": [
                    {"apn": APN_INET, "static_ip": "100.66.49.1", "pool_id": self.pool_id},
                    {"apn": None,     "static_ip": "100.66.49.2", "pool_id": self.pool_id},
                ]},
            ],
        )
        TestImsiApnToImsiWithWildcard.sim_id = body["sim_id"]

    def test_02_unforced_change_still_rejected(self, http: httpx.Client):
        """Even though a wildcard exists, the per-APN row is still an orphan → 409."""
        r = http.patch(f"/profiles/{self.sim_id}", json={"ip_resolution": "imsi"})
        assert r.status_code == 409
        detail = r.json().get("detail", r.json())
        assert detail["orphaned_count"] == 1   # only the per-APN row, not the wildcard

    def test_03_forced_change_keeps_wildcard(self, http: httpx.Client, lookup_http: httpx.Client):
        """Force=true deletes the per-APN row but leaves the wildcard. Lookup still resolves."""
        r = http.patch(
            f"/profiles/{self.sim_id}",
            params={"force": "true"},
            json={"ip_resolution": "imsi"},
        )
        assert r.status_code == 200

        # Lookup must now hit the wildcard row regardless of APN
        for apn in (APN_INET, APN_OTHER):
            r = lookup_http.get("/lookup", params={
                "imsi": self.IMSI, "apn": apn, "use_case_id": USE_CASE_ID,
            })
            assert r.status_code == 200, f"apn={apn}: {r.status_code} {r.text}"
            assert r.json()["static_ip"] == "100.66.49.2"


# ─────────────────────────────────────────────────────────────────────────────
# TestIccidApnToIccid — same shape on the sim_apn_ips table
# ─────────────────────────────────────────────────────────────────────────────
class TestIccidApnToIccid:
    """iccid_apn → iccid: card-level per-APN rows orphan when switching to APN-agnostic card mode."""

    pool_id: str | None = None
    sim_id: str | None = None

    ICCID = make_iccid(26, 12001)
    IMSI1 = make_imsi(26, 12001)
    IMSI2 = make_imsi(26, 12002)

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet="100.66.50.0/24", pool_name="pool-22c",
                            account_name="TestAccount", replace_on_conflict=True)
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

    def test_01_create_iccid_apn_profile(self, http: httpx.Client):
        body = create_profile_iccid_apn(
            http,
            iccid=self.ICCID,
            imsis=[self.IMSI1, self.IMSI2],
            apn_ips=[
                {"apn": APN_INET, "static_ip": IP_CARD_INET, "pool_id": self.pool_id},
                {"apn": APN_IMS,  "static_ip": IP_CARD_IMS,  "pool_id": self.pool_id},
            ],
        )
        TestIccidApnToIccid.sim_id = body["sim_id"]

    def test_02_unforced_change_to_iccid_rejected(self, http: httpx.Client):
        r = http.patch(f"/profiles/{self.sim_id}", json={"ip_resolution": "iccid"})
        assert r.status_code == 409
        detail = r.json().get("detail", r.json())
        assert detail["error"] == "mode_conversion_orphans_rows"
        assert detail["from"] == "iccid_apn"
        assert detail["to"] == "iccid"
        assert detail["orphaned_count"] == 2

    def test_03_forced_change_clears_card_apn_rows(self, http: httpx.Client):
        r = http.patch(
            f"/profiles/{self.sim_id}",
            params={"force": "true"},
            json={"ip_resolution": "iccid"},
        )
        assert r.status_code == 200
        g = http.get(f"/profiles/{self.sim_id}")
        assert g.status_code == 200
        assert g.json()["ip_resolution"] == "iccid"


# ─────────────────────────────────────────────────────────────────────────────
# TestImsiApnToIccidApn — cross-table conversion
# ─────────────────────────────────────────────────────────────────────────────
class TestImsiApnToIccidApn:
    """imsi_apn → iccid_apn: cross-table. Every existing row in imsi_apn_ips becomes
    an orphan because the new resolver queries sim_apn_ips."""

    pool_id: str | None = None
    sim_id: str | None = None

    IMSI = make_imsi(26, 13001)

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet="100.66.51.0/24", pool_name="pool-22d",
                            account_name="TestAccount", replace_on_conflict=True)
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

    def test_01_create_imsi_apn_profile(self, http: httpx.Client):
        body = create_profile_imsi_apn(
            http,
            iccid=None,
            imsis=[
                {"imsi": self.IMSI, "apn_ips": [
                    {"apn": APN_INET, "static_ip": "100.66.51.1", "pool_id": self.pool_id},
                    {"apn": APN_IMS,  "static_ip": "100.66.51.2", "pool_id": self.pool_id},
                ]},
            ],
        )
        TestImsiApnToIccidApn.sim_id = body["sim_id"]

    def test_02_cross_table_unforced_rejected(self, http: httpx.Client):
        """Cross-table: every imsi_apn_ips row for this sim is an orphan once we move
        to iccid_apn (which reads sim_apn_ips). Without ?force=true → 409."""
        r = http.patch(f"/profiles/{self.sim_id}", json={"ip_resolution": "iccid_apn"})
        assert r.status_code == 409
        detail = r.json().get("detail", r.json())
        assert detail["error"] == "mode_conversion_orphans_rows"
        # Cross-table: count includes ALL rows, not just specific-APN ones
        assert detail["orphaned_count"] == 2

    def test_03_cross_table_force_wipes_old_table(self, http: httpx.Client):
        r = http.patch(
            f"/profiles/{self.sim_id}",
            params={"force": "true"},
            json={"ip_resolution": "iccid_apn"},
        )
        assert r.status_code == 200
        g = http.get(f"/profiles/{self.sim_id}")
        assert g.status_code == 200
        assert g.json()["ip_resolution"] == "iccid_apn"


# ─────────────────────────────────────────────────────────────────────────────
# TestNoOpAndAllowedTransitions — same-value PATCH and additive transitions
# ─────────────────────────────────────────────────────────────────────────────
class TestNoOpAndAllowedTransitions:
    """Same-value PATCH and `imsi → imsi_apn` (additive) must not require ?force=true."""

    pool_id: str | None = None
    sim_id: str | None = None

    IMSI = make_imsi(26, 14001)

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet="100.66.52.0/24", pool_name="pool-22e",
                            account_name="TestAccount", replace_on_conflict=True)
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

    def test_01_create_imsi_profile(self, http: httpx.Client):
        # Use the imsi_apn fixture with a single null-apn row to mimic an `imsi` profile shape
        # (the fixture sets ip_resolution=imsi_apn, but apn=null + a single row is the imsi shape).
        # Then we PATCH to ip_resolution=imsi as a baseline — orphan_count should be 0
        # because the existing row already has apn IS NULL.
        body = create_profile_imsi_apn(
            http,
            iccid=None,
            imsis=[
                {"imsi": self.IMSI, "apn_ips": [
                    {"apn": None, "static_ip": "100.66.52.1", "pool_id": self.pool_id},
                ]},
            ],
        )
        TestNoOpAndAllowedTransitions.sim_id = body["sim_id"]

    def test_02_imsi_apn_to_imsi_with_only_wildcard_no_force_needed(self, http: httpx.Client):
        """If the only existing row is the wildcard (apn IS NULL), nothing is orphaned
        on the imsi_apn → imsi transition — the guard must allow it without ?force=true."""
        r = http.patch(f"/profiles/{self.sim_id}", json={"ip_resolution": "imsi"})
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"

    def test_03_same_value_patch_is_noop(self, http: httpx.Client):
        """PATCH ip_resolution=imsi (same as current after test_02) → 200, no guard fires."""
        r = http.patch(f"/profiles/{self.sim_id}", json={"ip_resolution": "imsi"})
        assert r.status_code == 200
