"""
test_13_export_and_ip_search.py

New APIs and behaviour changes covered here:

  • GET /profiles/export    — per-IMSI/APN rows in the bulk-import CSV format,
                              with the same filter params as GET /profiles
  • GET /profiles?ip=<addr> — exact-match IP filter across imsi_apn_ips and
                              sim_apn_ips (card-level IPs)
  • GET /profiles/{sim_id}  — now returns 200 for terminated profiles (not 404)
  • GET /profiles            — no default status filter; includes terminated SIMs

Test cases 13.1 – 13.12
"""
import httpx

from conftest import PROVISION_BASE, JWT_TOKEN, make_imsi, make_iccid, make_ip
from fixtures.pools import create_pool, delete_pool
from fixtures.profiles import (
    create_profile_imsi,
    create_profile_imsi_apn,
    create_profile_iccid,
    delete_profile,
)

# ── Constants ─────────────────────────────────────────────────────────────────

ACCOUNT     = "ExportTest13"          # unique account — keeps filter assertions noise-free
POOL_SUBNET = "100.65.170.0/24"
ICCID       = make_iccid(13, 1)       # 19-digit ICCID for sim_card

IMSI1 = make_imsi(13, 1)  # sim_a, IP_UNIQUE
IMSI2 = make_imsi(13, 2)  # sim_a, IP_SHARED  (also held by sim_b/APN2)
IMSI3 = make_imsi(13, 3)  # sim_b, APN1→IP_APN + APN2→IP_SHARED
IMSI4 = make_imsi(13, 4)  # sim_card, card-level IP_CARD
IMSI5 = make_imsi(13, 5)  # sim_term — terminated during test 13.10

IP_UNIQUE = make_ip(170, 10)   # only sim_a / IMSI1
IP_SHARED = make_ip(170, 20)   # sim_a/IMSI2  +  sim_b/IMSI3/APN2  (2-SIM match)
IP_APN    = make_ip(170, 30)   # only sim_b / IMSI3 / APN1
IP_CARD   = make_ip(170, 40)   # sim_card — card-level (sim_apn_ips table)
IP_TERM   = make_ip(170, 50)   # sim_term — terminated in test 13.10

APN1 = "apn1.export-test.com"
APN2 = "apn2.export-test.com"

# The 9 columns that must appear in every export row (== import template)
EXPORT_COLUMNS = {
    "sim_id", "iccid", "account_name", "status",
    "ip_resolution", "imsi", "apn", "static_ip", "pool_id",
}


class TestExportAndIpSearch:
    """
    Fixture layout
    ──────────────
    sim_a    imsi mode      IMSI1 → IP_UNIQUE
                            IMSI2 → IP_SHARED
    sim_b    imsi_apn mode  IMSI3 → APN1: IP_APN
                                    APN2: IP_SHARED   ← same IP as sim_a/IMSI2
    sim_card iccid mode     IMSI4 → card-level IP_CARD (stored in sim_apn_ips)
    sim_term imsi mode      IMSI5 → IP_TERM  (terminated in test 13.10)
    """

    pool_id:     str | None = None
    sim_a_id:    str | None = None
    sim_b_id:    str | None = None
    sim_card_id: str | None = None
    sim_term_id: str | None = None

    @classmethod
    def setup_class(cls):
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            p = create_pool(
                c, subnet=POOL_SUBNET,
                pool_name="pool-export-13", account_name=ACCOUNT,
            )
            cls.pool_id = p["pool_id"]

            # sim_a — imsi mode, 2 IMSIs; IMSI2 shares IP with sim_b
            r = create_profile_imsi(
                c, account_name=ACCOUNT,
                imsis=[
                    {"imsi": IMSI1, "static_ip": IP_UNIQUE, "pool_id": cls.pool_id},
                    {"imsi": IMSI2, "static_ip": IP_SHARED, "pool_id": cls.pool_id},
                ],
            )
            cls.sim_a_id = r["sim_id"]

            # sim_b — imsi_apn mode, 1 IMSI, 2 APNs; APN2 shares IP_SHARED with sim_a
            r = create_profile_imsi_apn(
                c, account_name=ACCOUNT,
                imsis=[{
                    "imsi": IMSI3,
                    "apn_ips": [
                        {"apn": APN1, "static_ip": IP_APN,    "pool_id": cls.pool_id},
                        {"apn": APN2, "static_ip": IP_SHARED, "pool_id": cls.pool_id},
                    ],
                }],
            )
            cls.sim_b_id = r["sim_id"]

            # sim_card — iccid mode; card-level IP stored in sim_apn_ips
            r = create_profile_iccid(
                c, iccid=ICCID, account_name=ACCOUNT,
                imsis=[IMSI4],
                static_ip=IP_CARD, pool_id=cls.pool_id,
            )
            cls.sim_card_id = r["sim_id"]

            # sim_term — imsi mode; terminated during test 13.10
            r = create_profile_imsi(
                c, account_name=ACCOUNT,
                imsis=[{"imsi": IMSI5, "static_ip": IP_TERM, "pool_id": cls.pool_id}],
            )
            cls.sim_term_id = r["sim_id"]

    @classmethod
    def teardown_class(cls):
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            for sid in (cls.sim_a_id, cls.sim_b_id, cls.sim_card_id, cls.sim_term_id):
                if sid:
                    delete_profile(c, sid)   # handles already-terminated (404) gracefully
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # ── 13.1 ─────────────────────────────────────────────────────────────────

    def test_01_export_columns_match_import_format(self, http: httpx.Client):
        """GET /profiles/export — every row has exactly the 9 import-format keys."""
        r = http.get("/profiles/export", params={"account_name": ACCOUNT})
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) > 0, "Expected at least one export row"
        for row in rows:
            assert set(row.keys()) == EXPORT_COLUMNS, (
                f"Row keys mismatch: got {set(row.keys())}"
            )

    # ── 13.2 ─────────────────────────────────────────────────────────────────

    def test_02_export_imsi_mode_one_row_per_imsi(self, http: httpx.Client):
        """GET /profiles/export — imsi-mode profile yields one row per IMSI."""
        r = http.get("/profiles/export", params={"account_name": ACCOUNT})
        rows = r.json()
        sim_a_rows = [row for row in rows if row["sim_id"] == self.__class__.sim_a_id]
        # sim_a has 2 IMSIs → 2 export rows
        assert len(sim_a_rows) == 2, (
            f"Expected 2 rows for sim_a, got {len(sim_a_rows)}"
        )
        ips   = {row["static_ip"] for row in sim_a_rows}
        imsis = {row["imsi"]      for row in sim_a_rows}
        assert IP_UNIQUE in ips and IP_SHARED in ips
        assert IMSI1 in imsis and IMSI2 in imsis

    # ── 13.3 ─────────────────────────────────────────────────────────────────

    def test_03_export_imsi_apn_mode_one_row_per_imsi_apn_pair(self, http: httpx.Client):
        """GET /profiles/export — imsi_apn profile yields one row per IMSI×APN pair."""
        r = http.get("/profiles/export", params={"account_name": ACCOUNT})
        rows = r.json()
        sim_b_rows = [row for row in rows if row["sim_id"] == self.__class__.sim_b_id]
        # sim_b has 1 IMSI × 2 APNs → 2 export rows
        assert len(sim_b_rows) == 2, (
            f"Expected 2 rows for sim_b (1 IMSI × 2 APNs), got {len(sim_b_rows)}"
        )
        apns = {row["apn"] for row in sim_b_rows}
        assert APN1 in apns and APN2 in apns

    # ── 13.4 ─────────────────────────────────────────────────────────────────

    def test_04_export_filtered_by_account(self, http: httpx.Client):
        """GET /profiles/export?account_name= — only rows for that account returned."""
        r = http.get("/profiles/export", params={"account_name": ACCOUNT})
        rows = r.json()
        assert all(row["account_name"] == ACCOUNT for row in rows), (
            "Every exported row should belong to the filtered account"
        )
        # Our 4 test SIMs must all appear
        our_ids = {
            self.__class__.sim_a_id, self.__class__.sim_b_id,
            self.__class__.sim_card_id, self.__class__.sim_term_id,
        }
        assert our_ids <= {row["sim_id"] for row in rows}

    # ── 13.5 ─────────────────────────────────────────────────────────────────

    def test_05_export_ip_filter_unique_ip_single_sim(self, http: httpx.Client):
        """GET /profiles/export?ip=IP_UNIQUE — rows belong only to sim_a."""
        r = http.get("/profiles/export", params={"ip": IP_UNIQUE})
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) > 0, "Expected rows for IP_UNIQUE"
        assert all(row["sim_id"] == self.__class__.sim_a_id for row in rows), (
            f"Expected only sim_a rows, got {[row['sim_id'] for row in rows]}"
        )
        assert any(row["static_ip"] == IP_UNIQUE for row in rows)

    # ── 13.6 ─────────────────────────────────────────────────────────────────

    def test_06_export_ip_filter_shared_ip_two_sims(self, http: httpx.Client):
        """GET /profiles/export?ip=IP_SHARED — rows from both sim_a and sim_b."""
        r = http.get("/profiles/export", params={"ip": IP_SHARED})
        assert r.status_code == 200
        sim_ids = {row["sim_id"] for row in r.json()}
        assert self.__class__.sim_a_id in sim_ids, "sim_a should appear for IP_SHARED"
        assert self.__class__.sim_b_id in sim_ids, "sim_b should appear for IP_SHARED"

    # ── 13.7 ─────────────────────────────────────────────────────────────────

    def test_07_list_ip_filter_exact_match_single_sim(self, http: httpx.Client):
        """GET /profiles?ip=IP_UNIQUE — returns exactly 1 SIM."""
        r = http.get("/profiles", params={"ip": IP_UNIQUE})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["sim_id"] == self.__class__.sim_a_id

    # ── 13.8 ─────────────────────────────────────────────────────────────────

    def test_08_list_ip_filter_shared_ip_returns_multiple(self, http: httpx.Client):
        """GET /profiles?ip=IP_SHARED — returns both SIMs that hold the shared IP."""
        r = http.get("/profiles", params={"ip": IP_SHARED})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 2, (
            f"Expected ≥2 matches for IP_SHARED, got {body['total']}"
        )
        found_ids = {item["sim_id"] for item in body["items"]}
        assert self.__class__.sim_a_id in found_ids
        assert self.__class__.sim_b_id in found_ids

    # ── 13.9 ─────────────────────────────────────────────────────────────────

    def test_09_list_ip_filter_card_level_ip(self, http: httpx.Client):
        """GET /profiles?ip=IP_CARD — matches via sim_apn_ips (card-level table)."""
        r = http.get("/profiles", params={"ip": IP_CARD})
        assert r.status_code == 200
        found_ids = {item["sim_id"] for item in r.json()["items"]}
        assert self.__class__.sim_card_id in found_ids, (
            f"sim_card not found via IP_CARD card-level search: {found_ids}"
        )

    # ── 13.10 ────────────────────────────────────────────────────────────────

    def test_10_list_ip_filter_nonexistent_returns_empty(self, http: httpx.Client):
        """GET /profiles?ip=<nonexistent> — returns 0 matches."""
        r = http.get("/profiles", params={"ip": "1.2.3.4"})
        assert r.status_code == 200
        assert r.json()["total"] == 0

    # ── 13.11 ────────────────────────────────────────────────────────────────

    def test_11_terminated_sim_get_returns_200(self, http: httpx.Client):
        """DELETE /profiles/{sim_term} → 204; GET returns 200 with status=terminated."""
        assert self.__class__.sim_term_id is not None

        # Terminate
        r = http.delete(f"/profiles/{self.__class__.sim_term_id}")
        assert r.status_code == 204

        # GET must now return 200 with the profile in terminated state (not 404)
        r = http.get(f"/profiles/{self.__class__.sim_term_id}")
        assert r.status_code == 200, (
            f"Terminated SIM should return 200, got {r.status_code}: {r.text}"
        )
        body = r.json()
        assert body["status"] == "terminated"
        assert body["sim_id"] == self.__class__.sim_term_id
        # IMSIs are cleaned up on termination
        assert body["imsis"] == []

    # ── 13.12 ────────────────────────────────────────────────────────────────

    def test_12_list_includes_terminated_without_filter(self, http: httpx.Client):
        """GET /profiles (no status filter) — terminated SIM appears in results."""
        r = http.get("/profiles", params={"account_name": ACCOUNT, "limit": 100})
        assert r.status_code == 200
        sim_ids = {item["sim_id"] for item in r.json()["items"]}
        assert self.__class__.sim_term_id in sim_ids, (
            "Terminated SIM should appear when no status filter is applied"
        )

    # ── 13.13 ────────────────────────────────────────────────────────────────

    def test_13_list_status_filter_terminated(self, http: httpx.Client):
        """GET /profiles?status=terminated — returns only terminated profiles."""
        r = http.get(
            "/profiles",
            params={"status": "terminated", "account_name": ACCOUNT, "limit": 100},
        )
        assert r.status_code == 200
        body = r.json()
        items = body["items"]
        assert all(item["status"] == "terminated" for item in items), (
            "All items should be terminated when filtering by status=terminated"
        )
        sim_ids = {item["sim_id"] for item in items}
        assert self.__class__.sim_term_id in sim_ids
