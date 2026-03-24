"""
test_14_export_delete_reprovision.py

For each of the 4 SIM types (iccid, imsi, imsi_apn, iccid_apn):

  1. Provision 4 SIMs of that type.
  2. Export them via GET /profiles/export  (UI export).
  3. Delete each via DELETE /profiles/{sim_id}.
  4. Reprovision using the exported data via POST /profiles/bulk.
  5. Verify profiles are active and lookup returns correct IPs.

Test cases 14.1 – 14.4 × 4 classes = 16 tests total.
"""
from __future__ import annotations

from collections import defaultdict

import httpx

from conftest import (
    PROVISION_BASE,
    JWT_TOKEN,
    USE_CASE_ID,
    make_imsi,
    make_iccid,
    make_ip,
    poll_until,
)
from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import (
    create_profile_iccid,
    create_profile_imsi,
    create_profile_imsi_apn,
    create_profile_iccid_apn,
    delete_profile,
)

# ── Constants ──────────────────────────────────────────────────────────────────

MODULE   = 14
ACCOUNT  = "ExportDeleteReprovision14"
SIM_COUNT = 4

APN_INET = "inet.reprovision14.com"
APN_IMS  = "ims.reprovision14.com"

JOB_TIMEOUT = 300.0


# ── Helper: convert flat export rows → nested bulk JSON ───────────────────────

def _rows_to_bulk_json(rows: list[dict]) -> list[dict]:
    """Convert GET /profiles/export rows (flat) back to POST /profiles/bulk payload."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["sim_id"]].append(r)

    profiles: list[dict] = []
    for sim_rows in groups.values():
        r0 = sim_rows[0]
        ip_res = r0["ip_resolution"]
        profile: dict = {
            "iccid":         r0["iccid"],
            "account_name":  r0["account_name"],
            "status":        "active",
            "ip_resolution": ip_res,
        }

        if ip_res == "imsi":
            profile["imsis"] = [
                {
                    "imsi":    r["imsi"],
                    "apn_ips": [{"static_ip": r["static_ip"], "pool_id": r["pool_id"]}],
                }
                for r in sim_rows
            ]

        elif ip_res == "imsi_apn":
            imsi_map: dict[str, list[dict]] = defaultdict(list)
            for r in sim_rows:
                imsi_map[r["imsi"]].append(r)
            profile["imsis"] = [
                {
                    "imsi": imsi,
                    "apn_ips": [
                        {"apn": r["apn"], "static_ip": r["static_ip"], "pool_id": r["pool_id"]}
                        for r in apn_rows
                    ],
                }
                for imsi, apn_rows in imsi_map.items()
            ]

        elif ip_res == "iccid":
            # Deduplicate card-level IP (same IP appears once per IMSI row)
            seen: set[tuple] = set()
            iccid_ips: list[dict] = []
            for r in sim_rows:
                key = (r["static_ip"], r.get("apn"))
                if key not in seen:
                    iccid_ips.append({"apn": r.get("apn"), "static_ip": r["static_ip"], "pool_id": r["pool_id"]})
                    seen.add(key)
            profile["imsis"]    = [{"imsi": r["imsi"], "apn_ips": []} for r in sim_rows]
            profile["iccid_ips"] = iccid_ips

        elif ip_res == "iccid_apn":
            # Deduplicate IMSIs and card-level APN IPs separately
            seen_imsis: set[str] = set()
            imsi_list: list[dict] = []
            for r in sim_rows:
                if r["imsi"] not in seen_imsis:
                    imsi_list.append({"imsi": r["imsi"], "apn_ips": []})
                    seen_imsis.add(r["imsi"])

            seen_ips: set[tuple] = set()
            iccid_ips = []
            for r in sim_rows:
                key = (r["static_ip"], r.get("apn"))
                if key not in seen_ips:
                    iccid_ips.append({"apn": r["apn"], "static_ip": r["static_ip"], "pool_id": r["pool_id"]})
                    seen_ips.add(key)

            profile["imsis"]    = imsi_list
            profile["iccid_ips"] = iccid_ips

        profiles.append(profile)
    return profiles


# ── Shared client factory ──────────────────────────────────────────────────────

def _client() -> httpx.Client:
    return httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=30.0,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Class A — ip_resolution = iccid
#  Each SIM: 1 ICCID, 2 IMSIs, 1 card-level IP (stored in sim_apn_ips)
# ══════════════════════════════════════════════════════════════════════════════

class TestExportDeleteReprovisionIccid:
    """iccid type: card-level IP shared by all IMSIs."""

    SUBNET    = "100.65.184.0/24"
    IP_BLOCK  = 184
    IMSI_BASE = 0       # IMSIs 1-8
    ICCID_BASE = 0      # ICCIDs 1-4

    pool_id:       str | None  = None
    sim_ids:       list[str]   = []
    exported_rows: list[dict]  = []
    job_id:        str | None  = None
    # (imsi, apn, expected_ip)
    verify_lookups: list[tuple[str, str | None, str]] = []

    @classmethod
    def setup_class(cls):
        cls.sim_ids       = []
        cls.exported_rows = []
        cls.verify_lookups = []

        with _client() as c:
            p = create_pool(c, subnet=cls.SUBNET,
                            pool_name=f"pool-14-iccid", account_name=ACCOUNT,
                            replace_on_conflict=True)
            cls.pool_id = p["pool_id"]

            for i in range(1, SIM_COUNT + 1):
                iccid    = make_iccid(MODULE, cls.ICCID_BASE + i)
                imsi_a   = make_imsi(MODULE, cls.IMSI_BASE + i * 2 - 1)
                imsi_b   = make_imsi(MODULE, cls.IMSI_BASE + i * 2)
                card_ip  = make_ip(cls.IP_BLOCK, i)

                r = create_profile_iccid(
                    c, iccid=iccid, account_name=ACCOUNT,
                    imsis=[imsi_a, imsi_b],
                    static_ip=card_ip, pool_id=cls.pool_id,
                )
                cls.sim_ids.append(r["sim_id"])
                # iccid type ignores APN but the lookup endpoint still requires it;
                # pass a placeholder so the lookup call is valid.
                cls.verify_lookups.append((imsi_a, "any", card_ip))

    @classmethod
    def teardown_class(cls):
        with _client() as c:
            for sid in cls.sim_ids:
                delete_profile(c, sid)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # ── 14.1 ──────────────────────────────────────────────────────────────────

    def test_01_export_contains_all_sims(self, http: httpx.Client):
        """GET /profiles/export — all 4 iccid SIMs appear; static_ip is non-null."""
        r = http.get("/profiles/export", params={"account_name": ACCOUNT, "ip_resolution": "iccid"})
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) > 0, "Export returned no rows"

        our_rows = [row for row in rows if row["sim_id"] in self.__class__.sim_ids]
        found_ids = {row["sim_id"] for row in our_rows}
        assert found_ids == set(self.__class__.sim_ids), (
            f"Missing sim_ids in export: {set(self.__class__.sim_ids) - found_ids}"
        )
        # Card-level IPs must be present (validates the export fix)
        for row in our_rows:
            assert row["static_ip"] is not None, (
                f"static_ip is NULL for iccid SIM {row['sim_id']} — export fix required"
            )

        self.__class__.exported_rows = our_rows

    # ── 14.2 ──────────────────────────────────────────────────────────────────

    def test_02_delete_all_sims(self, http: httpx.Client):
        """DELETE /profiles/{sim_id} × 4 → 204; GET returns status=terminated."""
        for sid in self.__class__.sim_ids:
            r = http.delete(f"/profiles/{sid}")
            assert r.status_code == 204, f"Expected 204 deleting {sid}, got {r.status_code}"

        for sid in self.__class__.sim_ids:
            r = http.get(f"/profiles/{sid}")
            assert r.status_code == 200
            assert r.json()["status"] == "terminated", f"SIM {sid} not terminated"

    # ── 14.3 ──────────────────────────────────────────────────────────────────

    def test_03_reprovision_via_bulk(self, http: httpx.Client):
        """Convert exported rows → bulk JSON, POST /profiles/bulk → job completes."""
        assert self.__class__.exported_rows, "No exported rows — test 14.1 must pass first"

        payload = _rows_to_bulk_json(self.__class__.exported_rows)
        assert len(payload) == SIM_COUNT, f"Expected {SIM_COUNT} profiles in payload, got {len(payload)}"

        r = http.post("/profiles/bulk", json=payload, timeout=60.0)
        assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
        self.__class__.job_id = r.json()["job_id"]

        result = poll_until(
            lambda: http.get(f"/jobs/{self.__class__.job_id}").json(),
            condition=lambda j: j.get("status") in ("completed", "failed"),
            timeout=JOB_TIMEOUT,
            interval=5.0,
            label=f"reprovision-iccid job {self.__class__.job_id}",
        )
        assert result["status"] == "completed", f"Job failed: {result}"
        assert result.get("failed", 0) == 0, f"Unexpected failures: {result}"
        assert result.get("processed", 0) == SIM_COUNT, (
            f"Expected processed={SIM_COUNT}, got {result.get('processed')}"
        )

    # ── 14.4 ──────────────────────────────────────────────────────────────────

    def test_04_verify_reprovisioned_profiles(self, http: httpx.Client, lookup_http: httpx.Client):
        """After reprovision, GET /profiles?imsi=… → active; GET /lookup → correct IP."""
        for imsi, apn, expected_ip in self.__class__.verify_lookups:
            r = http.get("/profiles", params={"imsi": imsi})
            assert r.status_code == 200
            data = r.json()
            items = data if isinstance(data, list) else data.get("items", data.get("profiles", []))
            active = [p for p in items if p.get("status") == "active"]
            assert len(active) >= 1, f"No active profile for IMSI {imsi} after reprovision"

            lookup_params = {"imsi": imsi, "use_case_id": USE_CASE_ID}
            if apn:
                lookup_params["apn"] = apn
            r2 = lookup_http.get("/lookup", params=lookup_params)
            assert r2.status_code == 200, f"Lookup for {imsi} returned {r2.status_code}: {r2.text}"
            assert r2.json()["static_ip"] == expected_ip, (
                f"IP mismatch for {imsi}: expected {expected_ip}, got {r2.json()['static_ip']}"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  Class B — ip_resolution = imsi
#  Each SIM: 2 IMSIs each with their own APN-agnostic IP
# ══════════════════════════════════════════════════════════════════════════════

class TestExportDeleteReprovisionImsi:
    """imsi type: per-IMSI APN-agnostic IP."""

    SUBNET    = "100.65.185.0/24"
    IP_BLOCK  = 185
    IMSI_BASE = 100

    pool_id:       str | None  = None
    sim_ids:       list[str]   = []
    exported_rows: list[dict]  = []
    job_id:        str | None  = None
    verify_lookups: list[tuple[str, str | None, str]] = []

    @classmethod
    def setup_class(cls):
        cls.sim_ids       = []
        cls.exported_rows = []
        cls.verify_lookups = []

        with _client() as c:
            p = create_pool(c, subnet=cls.SUBNET,
                            pool_name="pool-14-imsi", account_name=ACCOUNT,
                            replace_on_conflict=True)
            cls.pool_id = p["pool_id"]

            for i in range(1, SIM_COUNT + 1):
                imsi_a = make_imsi(MODULE, cls.IMSI_BASE + i * 2 - 1)
                imsi_b = make_imsi(MODULE, cls.IMSI_BASE + i * 2)
                ip_a   = make_ip(cls.IP_BLOCK, i * 2 - 1)
                ip_b   = make_ip(cls.IP_BLOCK, i * 2)

                r = create_profile_imsi(
                    c, account_name=ACCOUNT,
                    imsis=[
                        {"imsi": imsi_a, "static_ip": ip_a, "pool_id": cls.pool_id},
                        {"imsi": imsi_b, "static_ip": ip_b, "pool_id": cls.pool_id},
                    ],
                )
                cls.sim_ids.append(r["sim_id"])
                # imsi type ignores APN but the lookup endpoint still requires it;
                # pass a placeholder so the lookup call is valid.
                cls.verify_lookups.append((imsi_a, "any", ip_a))

    @classmethod
    def teardown_class(cls):
        with _client() as c:
            for sid in cls.sim_ids:
                delete_profile(c, sid)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # ── 14.1 ──────────────────────────────────────────────────────────────────

    def test_01_export_contains_all_sims(self, http: httpx.Client):
        """GET /profiles/export — all 4 imsi SIMs appear, one row per IMSI."""
        r = http.get("/profiles/export", params={"account_name": ACCOUNT, "ip_resolution": "imsi"})
        assert r.status_code == 200
        rows = r.json()

        our_rows = [row for row in rows if row["sim_id"] in self.__class__.sim_ids]
        found_ids = {row["sim_id"] for row in our_rows}
        assert found_ids == set(self.__class__.sim_ids), (
            f"Missing sim_ids in export: {set(self.__class__.sim_ids) - found_ids}"
        )
        # 4 SIMs × 2 IMSIs each = 8 rows
        assert len(our_rows) == SIM_COUNT * 2, (
            f"Expected {SIM_COUNT * 2} rows, got {len(our_rows)}"
        )
        for row in our_rows:
            assert row["static_ip"] is not None, f"static_ip is NULL for row {row}"

        self.__class__.exported_rows = our_rows

    # ── 14.2 ──────────────────────────────────────────────────────────────────

    def test_02_delete_all_sims(self, http: httpx.Client):
        """DELETE /profiles/{sim_id} × 4 → 204; GET returns status=terminated."""
        for sid in self.__class__.sim_ids:
            r = http.delete(f"/profiles/{sid}")
            assert r.status_code == 204, f"Expected 204 deleting {sid}, got {r.status_code}"

        for sid in self.__class__.sim_ids:
            r = http.get(f"/profiles/{sid}")
            assert r.status_code == 200
            assert r.json()["status"] == "terminated"

    # ── 14.3 ──────────────────────────────────────────────────────────────────

    def test_03_reprovision_via_bulk(self, http: httpx.Client):
        """Convert exported rows → bulk JSON, POST /profiles/bulk → job completes."""
        assert self.__class__.exported_rows, "No exported rows — test 14.1 must pass first"

        payload = _rows_to_bulk_json(self.__class__.exported_rows)
        assert len(payload) == SIM_COUNT

        r = http.post("/profiles/bulk", json=payload, timeout=60.0)
        assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
        self.__class__.job_id = r.json()["job_id"]

        result = poll_until(
            lambda: http.get(f"/jobs/{self.__class__.job_id}").json(),
            condition=lambda j: j.get("status") in ("completed", "failed"),
            timeout=JOB_TIMEOUT,
            interval=5.0,
            label=f"reprovision-imsi job {self.__class__.job_id}",
        )
        assert result["status"] == "completed", f"Job failed: {result}"
        assert result.get("failed", 0) == 0
        assert result.get("processed", 0) == SIM_COUNT

    # ── 14.4 ──────────────────────────────────────────────────────────────────

    def test_04_verify_reprovisioned_profiles(self, http: httpx.Client, lookup_http: httpx.Client):
        """After reprovision, lookup returns correct per-IMSI IP."""
        for imsi, apn, expected_ip in self.__class__.verify_lookups:
            r = http.get("/profiles", params={"imsi": imsi})
            assert r.status_code == 200
            data = r.json()
            items = data if isinstance(data, list) else data.get("items", data.get("profiles", []))
            active = [p for p in items if p.get("status") == "active"]
            assert len(active) >= 1, f"No active profile for IMSI {imsi} after reprovision"

            lookup_params = {"imsi": imsi, "use_case_id": USE_CASE_ID}
            if apn:
                lookup_params["apn"] = apn
            r2 = lookup_http.get("/lookup", params=lookup_params)
            assert r2.status_code == 200, f"Lookup for {imsi} returned {r2.status_code}: {r2.text}"
            assert r2.json()["static_ip"] == expected_ip


# ══════════════════════════════════════════════════════════════════════════════
#  Class C — ip_resolution = imsi_apn
#  Each SIM: 2 IMSIs × 2 APNs = 4 IP entries per SIM
# ══════════════════════════════════════════════════════════════════════════════

class TestExportDeleteReprovisionImsiApn:
    """imsi_apn type: per-IMSI per-APN static IP."""

    SUBNET    = "100.65.186.0/24"
    IP_BLOCK  = 186
    IMSI_BASE = 200

    pool_id:       str | None  = None
    sim_ids:       list[str]   = []
    exported_rows: list[dict]  = []
    job_id:        str | None  = None
    verify_lookups: list[tuple[str, str | None, str]] = []

    @classmethod
    def setup_class(cls):
        cls.sim_ids       = []
        cls.exported_rows = []
        cls.verify_lookups = []

        with _client() as c:
            p = create_pool(c, subnet=cls.SUBNET,
                            pool_name="pool-14-imsi-apn", account_name=ACCOUNT,
                            replace_on_conflict=True)
            cls.pool_id = p["pool_id"]

            ip_seq = 1
            for i in range(1, SIM_COUNT + 1):
                imsi_a = make_imsi(MODULE, cls.IMSI_BASE + i * 2 - 1)
                imsi_b = make_imsi(MODULE, cls.IMSI_BASE + i * 2)

                ip_a_inet = make_ip(cls.IP_BLOCK, ip_seq);     ip_seq += 1
                ip_a_ims  = make_ip(cls.IP_BLOCK, ip_seq);     ip_seq += 1
                ip_b_inet = make_ip(cls.IP_BLOCK, ip_seq);     ip_seq += 1
                ip_b_ims  = make_ip(cls.IP_BLOCK, ip_seq);     ip_seq += 1

                r = create_profile_imsi_apn(
                    c, account_name=ACCOUNT,
                    imsis=[
                        {
                            "imsi": imsi_a,
                            "apn_ips": [
                                {"apn": APN_INET, "static_ip": ip_a_inet, "pool_id": cls.pool_id},
                                {"apn": APN_IMS,  "static_ip": ip_a_ims,  "pool_id": cls.pool_id},
                            ],
                        },
                        {
                            "imsi": imsi_b,
                            "apn_ips": [
                                {"apn": APN_INET, "static_ip": ip_b_inet, "pool_id": cls.pool_id},
                                {"apn": APN_IMS,  "static_ip": ip_b_ims,  "pool_id": cls.pool_id},
                            ],
                        },
                    ],
                )
                cls.sim_ids.append(r["sim_id"])
                cls.verify_lookups.append((imsi_a, APN_INET, ip_a_inet))
                cls.verify_lookups.append((imsi_a, APN_IMS,  ip_a_ims))

    @classmethod
    def teardown_class(cls):
        with _client() as c:
            for sid in cls.sim_ids:
                delete_profile(c, sid)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # ── 14.1 ──────────────────────────────────────────────────────────────────

    def test_01_export_contains_all_sims(self, http: httpx.Client):
        """GET /profiles/export — all 4 imsi_apn SIMs appear, one row per IMSI×APN."""
        r = http.get("/profiles/export", params={"account_name": ACCOUNT, "ip_resolution": "imsi_apn"})
        assert r.status_code == 200
        rows = r.json()

        our_rows = [row for row in rows if row["sim_id"] in self.__class__.sim_ids]
        found_ids = {row["sim_id"] for row in our_rows}
        assert found_ids == set(self.__class__.sim_ids)
        # 4 SIMs × 2 IMSIs × 2 APNs = 16 rows
        assert len(our_rows) == SIM_COUNT * 2 * 2, (
            f"Expected {SIM_COUNT * 2 * 2} rows (1 per IMSI×APN), got {len(our_rows)}"
        )
        for row in our_rows:
            assert row["static_ip"] is not None

        self.__class__.exported_rows = our_rows

    # ── 14.2 ──────────────────────────────────────────────────────────────────

    def test_02_delete_all_sims(self, http: httpx.Client):
        """DELETE /profiles/{sim_id} × 4 → 204; GET returns status=terminated."""
        for sid in self.__class__.sim_ids:
            r = http.delete(f"/profiles/{sid}")
            assert r.status_code == 204

        for sid in self.__class__.sim_ids:
            r = http.get(f"/profiles/{sid}")
            assert r.status_code == 200
            assert r.json()["status"] == "terminated"

    # ── 14.3 ──────────────────────────────────────────────────────────────────

    def test_03_reprovision_via_bulk(self, http: httpx.Client):
        """Convert exported rows → bulk JSON, POST /profiles/bulk → job completes."""
        assert self.__class__.exported_rows

        payload = _rows_to_bulk_json(self.__class__.exported_rows)
        assert len(payload) == SIM_COUNT

        r = http.post("/profiles/bulk", json=payload, timeout=60.0)
        assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
        self.__class__.job_id = r.json()["job_id"]

        result = poll_until(
            lambda: http.get(f"/jobs/{self.__class__.job_id}").json(),
            condition=lambda j: j.get("status") in ("completed", "failed"),
            timeout=JOB_TIMEOUT,
            interval=5.0,
            label=f"reprovision-imsi_apn job {self.__class__.job_id}",
        )
        assert result["status"] == "completed", f"Job failed: {result}"
        assert result.get("failed", 0) == 0
        assert result.get("processed", 0) == SIM_COUNT

    # ── 14.4 ──────────────────────────────────────────────────────────────────

    def test_04_verify_reprovisioned_profiles(self, http: httpx.Client, lookup_http: httpx.Client):
        """After reprovision, lookup with APN returns correct per-IMSI/APN IP."""
        for imsi, apn, expected_ip in self.__class__.verify_lookups:
            r = http.get("/profiles", params={"imsi": imsi})
            assert r.status_code == 200
            data = r.json()
            items = data if isinstance(data, list) else data.get("items", data.get("profiles", []))
            active = [p for p in items if p.get("status") == "active"]
            assert len(active) >= 1, f"No active profile for IMSI {imsi}"

            r2 = lookup_http.get("/lookup", params={"imsi": imsi, "apn": apn, "use_case_id": USE_CASE_ID})
            assert r2.status_code == 200, f"Lookup {imsi}@{apn}: {r2.status_code} {r2.text}"
            assert r2.json()["static_ip"] == expected_ip, (
                f"IP mismatch for {imsi}@{apn}: expected {expected_ip}, got {r2.json()['static_ip']}"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  Class D — ip_resolution = iccid_apn
#  Each SIM: 1 ICCID, 2 IMSIs, 2 card-level APN IPs (stored in sim_apn_ips)
# ══════════════════════════════════════════════════════════════════════════════

class TestExportDeleteReprovisionIccidApn:
    """iccid_apn type: card-level per-APN IP."""

    SUBNET    = "100.65.187.0/24"
    IP_BLOCK  = 187
    IMSI_BASE = 300
    ICCID_BASE = 100

    pool_id:       str | None  = None
    sim_ids:       list[str]   = []
    exported_rows: list[dict]  = []
    job_id:        str | None  = None
    verify_lookups: list[tuple[str, str | None, str]] = []

    @classmethod
    def setup_class(cls):
        cls.sim_ids       = []
        cls.exported_rows = []
        cls.verify_lookups = []

        with _client() as c:
            p = create_pool(c, subnet=cls.SUBNET,
                            pool_name="pool-14-iccid-apn", account_name=ACCOUNT,
                            replace_on_conflict=True)
            cls.pool_id = p["pool_id"]

            for i in range(1, SIM_COUNT + 1):
                iccid    = make_iccid(MODULE, cls.ICCID_BASE + i)
                imsi_a   = make_imsi(MODULE, cls.IMSI_BASE + i * 2 - 1)
                imsi_b   = make_imsi(MODULE, cls.IMSI_BASE + i * 2)
                ip_inet  = make_ip(cls.IP_BLOCK, i * 2 - 1)
                ip_ims   = make_ip(cls.IP_BLOCK, i * 2)

                r = create_profile_iccid_apn(
                    c, iccid=iccid, account_name=ACCOUNT,
                    imsis=[imsi_a, imsi_b],
                    apn_ips=[
                        {"apn": APN_INET, "static_ip": ip_inet, "pool_id": cls.pool_id},
                        {"apn": APN_IMS,  "static_ip": ip_ims,  "pool_id": cls.pool_id},
                    ],
                )
                cls.sim_ids.append(r["sim_id"])
                cls.verify_lookups.append((imsi_a, APN_INET, ip_inet))
                cls.verify_lookups.append((imsi_a, APN_IMS,  ip_ims))

    @classmethod
    def teardown_class(cls):
        with _client() as c:
            for sid in cls.sim_ids:
                delete_profile(c, sid)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # ── 14.1 ──────────────────────────────────────────────────────────────────

    def test_01_export_contains_all_sims(self, http: httpx.Client):
        """GET /profiles/export — all 4 iccid_apn SIMs appear; static_ip is non-null."""
        r = http.get("/profiles/export", params={"account_name": ACCOUNT, "ip_resolution": "iccid_apn"})
        assert r.status_code == 200
        rows = r.json()

        our_rows = [row for row in rows if row["sim_id"] in self.__class__.sim_ids]
        found_ids = {row["sim_id"] for row in our_rows}
        assert found_ids == set(self.__class__.sim_ids), (
            f"Missing sim_ids in export: {set(self.__class__.sim_ids) - found_ids}"
        )
        # 4 SIMs × 2 IMSIs × 2 APNs = 16 rows
        assert len(our_rows) == SIM_COUNT * 2 * 2, (
            f"Expected {SIM_COUNT * 2 * 2} rows (1 per IMSI×APN), got {len(our_rows)}"
        )
        for row in our_rows:
            assert row["static_ip"] is not None, (
                f"static_ip is NULL for iccid_apn SIM {row['sim_id']} — export fix required"
            )

        self.__class__.exported_rows = our_rows

    # ── 14.2 ──────────────────────────────────────────────────────────────────

    def test_02_delete_all_sims(self, http: httpx.Client):
        """DELETE /profiles/{sim_id} × 4 → 204; GET returns status=terminated."""
        for sid in self.__class__.sim_ids:
            r = http.delete(f"/profiles/{sid}")
            assert r.status_code == 204

        for sid in self.__class__.sim_ids:
            r = http.get(f"/profiles/{sid}")
            assert r.status_code == 200
            assert r.json()["status"] == "terminated"

    # ── 14.3 ──────────────────────────────────────────────────────────────────

    def test_03_reprovision_via_bulk(self, http: httpx.Client):
        """Convert exported rows → bulk JSON, POST /profiles/bulk → job completes."""
        assert self.__class__.exported_rows

        payload = _rows_to_bulk_json(self.__class__.exported_rows)
        assert len(payload) == SIM_COUNT

        r = http.post("/profiles/bulk", json=payload, timeout=60.0)
        assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
        self.__class__.job_id = r.json()["job_id"]

        result = poll_until(
            lambda: http.get(f"/jobs/{self.__class__.job_id}").json(),
            condition=lambda j: j.get("status") in ("completed", "failed"),
            timeout=JOB_TIMEOUT,
            interval=5.0,
            label=f"reprovision-iccid_apn job {self.__class__.job_id}",
        )
        assert result["status"] == "completed", f"Job failed: {result}"
        assert result.get("failed", 0) == 0
        assert result.get("processed", 0) == SIM_COUNT

    # ── 14.4 ──────────────────────────────────────────────────────────────────

    def test_04_verify_reprovisioned_profiles(self, http: httpx.Client, lookup_http: httpx.Client):
        """After reprovision, lookup with APN returns correct card-level IP."""
        for imsi, apn, expected_ip in self.__class__.verify_lookups:
            r = http.get("/profiles", params={"imsi": imsi})
            assert r.status_code == 200
            data = r.json()
            items = data if isinstance(data, list) else data.get("items", data.get("profiles", []))
            active = [p for p in items if p.get("status") == "active"]
            assert len(active) >= 1, f"No active profile for IMSI {imsi}"

            r2 = lookup_http.get("/lookup", params={"imsi": imsi, "apn": apn, "use_case_id": USE_CASE_ID})
            assert r2.status_code == 200, f"Lookup {imsi}@{apn}: {r2.status_code} {r2.text}"
            assert r2.json()["static_ip"] == expected_ip, (
                f"IP mismatch for {imsi}@{apn}: expected {expected_ip}, got {r2.json()['static_ip']}"
            )
