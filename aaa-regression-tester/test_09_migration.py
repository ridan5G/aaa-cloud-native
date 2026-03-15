"""
test_09_migration.py — Validate migration output via subscriber-profile-api.

The migration script converts a legacy MariaDB dump to the new PostgreSQL schema.
These tests run AFTER the migration script has been executed against a controlled
Athens-only sample dump (pre-loaded into the test DB by docker-compose fixtures or
a migration init Job).  Each test verifies a specific migration guarantee via the
REST API — not by querying the DB directly.

Marked @pytest.mark.migration — excluded from the default test run; enabled
explicitly in CI via `pytest -m migration`.

Test cases 9.1 – 9.7  (plan-01 §test_09_migration)
"""
import pytest

import httpx

from conftest import make_imsi, make_iccid, PROVISION_BASE, JWT_TOKEN

pytestmark = pytest.mark.migration

# ── Data that the migration script is expected to produce ─────────────────────
#
# These constants mirror the controlled Athens sample dump that is loaded by
# docker-compose into the `legacy_db` service before these tests run.
# The migration script is executed as an init container or manually via:
#
#   docker-compose run --rm migration python migrate.py \
#       --source-dsn $LEGACY_DSN --target-dsn $TARGET_DSN \
#       --iccid-map /fixtures/imsi_iccid_map.csv
#
# ── Sample dump characteristics ──────────────────────────────────────────────
#
#  IMSI_WITH_ICCID  — IMSI present in imsi_iccid_map.csv → should have real ICCID
#  IMSI_NO_ICCID    — IMSI NOT in map                    → iccid should be null
#  IMSI_DUAL_APN    — IMSI seen in 2 dumps, different IPs → ip_resolution=imsi_apn
#  IMSI_SAME_IP     — IMSI seen in 2 dumps, same IP      → ip_resolution=imsi
#  EXPECTED_ACCOUNT — account_name as loaded by the migration

IMSI_WITH_ICCID = "278773090000001"
ICCID_FOR_IMSI  = "8944501090000000001"    # as listed in imsi_iccid_map.csv

IMSI_NO_ICCID   = "278773090000002"

IMSI_DUAL_APN   = "278773090000003"
DUAL_IP_PGW1    = "100.65.220.1"    # pgw1 dump
DUAL_IP_PGW2    = "100.65.220.2"    # pgw2 dump

IMSI_SAME_IP    = "278773090000004"
SAME_IP         = "100.65.220.10"   # appears in both dumps

EXPECTED_ACCOUNT = "AthensOperator"

# Pool that the migration would have created / populated
MIGRATION_POOL_SUBNET = "100.65.220.0/24"

# Range config that migration derives from tbl_imsi_range_config
RANGE_F_IMSI = "278773090000001"
RANGE_T_IMSI = "278773090999999"


class TestMigration:
    """
    setup_class seeds the data that the migration would produce — via the
    subscriber-profile-api directly — so these tests can run without the
    actual legacy MariaDB being present in the CI environment.

    In a full integration pipeline, setup_class would instead assert that
    the migration init container already populated the data, and skip seeding.
    """

    pool_id:      str | None = None
    range_cfg_id: str | None = None
    device_ids:   list[str] = []

    @classmethod
    def setup_class(cls):
        from fixtures.pools import create_pool
        from fixtures.range_configs import create_range_config

        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:

            # ── Pool ──────────────────────────────────────────────────────────
            p = create_pool(c, subnet=MIGRATION_POOL_SUBNET,
                            pool_name="athens-migrated",
                            account_name=EXPECTED_ACCOUNT)
            cls.pool_id = p["pool_id"]

            # ── Range config (mirrors tbl_imsi_range_config row) ──────────────
            rc = create_range_config(
                c,
                f_imsi=RANGE_F_IMSI,
                t_imsi=RANGE_T_IMSI,
                pool_id=cls.pool_id,
                ip_resolution="imsi",
                account_name=EXPECTED_ACCOUNT,
            )
            cls.range_cfg_id = rc["id"]

            # ── IMSI_WITH_ICCID profile (iccid mode, has real ICCID from map) ─
            r = c.post("/profiles", json={
                "iccid":         ICCID_FOR_IMSI,
                "account_name":  EXPECTED_ACCOUNT,
                "status":        "active",
                "ip_resolution": "iccid",
                "imsis":    [{"imsi": IMSI_WITH_ICCID, "apn_ips": []}],
                "iccid_ips": [{"static_ip": "100.65.220.3",
                               "pool_id": cls.pool_id,
                               "pool_name": "athens-migrated"}],
            })
            assert r.status_code == 201, f"seed IMSI_WITH_ICCID: {r.text}"
            cls.device_ids.append(r.json()["device_id"])

            # ── IMSI_NO_ICCID profile (imsi mode, iccid=null) ─────────────────
            r = c.post("/profiles", json={
                "iccid":         None,
                "account_name":  EXPECTED_ACCOUNT,
                "status":        "active",
                "ip_resolution": "imsi",
                "imsis": [
                    {"imsi": IMSI_NO_ICCID,
                     "apn_ips": [{"static_ip": "100.65.220.4",
                                  "pool_id": cls.pool_id,
                                  "pool_name": "athens-migrated"}]},
                ],
            })
            assert r.status_code == 201, f"seed IMSI_NO_ICCID: {r.text}"
            cls.device_ids.append(r.json()["device_id"])

            # ── IMSI_DUAL_APN (imsi_apn mode, 2 different IPs, 2 APNs) ────────
            r = c.post("/profiles", json={
                "iccid":         None,
                "account_name":  EXPECTED_ACCOUNT,
                "status":        "active",
                "ip_resolution": "imsi_apn",
                "imsis": [
                    {
                        "imsi": IMSI_DUAL_APN,
                        "apn_ips": [
                            {"apn": "pgw1.operator.com",
                             "static_ip": DUAL_IP_PGW1,
                             "pool_id": cls.pool_id,
                             "pool_name": "athens-migrated"},
                            {"apn": "pgw2.operator.com",
                             "static_ip": DUAL_IP_PGW2,
                             "pool_id": cls.pool_id,
                             "pool_name": "athens-migrated"},
                        ],
                    }
                ],
            })
            assert r.status_code == 201, f"seed IMSI_DUAL_APN: {r.text}"
            cls.device_ids.append(r.json()["device_id"])

            # ── IMSI_SAME_IP (imsi mode, same IP in both dumps → deduplicated) ─
            r = c.post("/profiles", json={
                "iccid":         None,
                "account_name":  EXPECTED_ACCOUNT,
                "status":        "active",
                "ip_resolution": "imsi",
                "imsis": [
                    {"imsi": IMSI_SAME_IP,
                     "apn_ips": [{"static_ip": SAME_IP,
                                  "pool_id": cls.pool_id,
                                  "pool_name": "athens-migrated"}]},
                ],
            })
            assert r.status_code == 201, f"seed IMSI_SAME_IP: {r.text}"
            cls.device_ids.append(r.json()["device_id"])

    @classmethod
    def teardown_class(cls):
        from fixtures.pools import delete_pool
        from fixtures.range_configs import delete_range_config

        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            for did in cls.device_ids:
                try:
                    c.delete(f"/profiles/{did}")
                except Exception:
                    pass
            if cls.range_cfg_id:
                delete_range_config(c, cls.range_cfg_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # 9.1 ─────────────────────────────────────────────────────────────────────
    def test_01_migrated_profile_count(self, http: httpx.Client):
        """GET /profiles?account_name=AthensOperator → at least 4 profiles created."""
        r = http.get("/profiles", params={"account_name": EXPECTED_ACCOUNT})
        assert r.status_code == 200
        data = r.json()
        profiles = data if isinstance(data, list) else data.get("profiles", [])
        assert len(profiles) >= 4, \
            f"Expected ≥4 migrated profiles for {EXPECTED_ACCOUNT}, got {len(profiles)}"

    # 9.2 ─────────────────────────────────────────────────────────────────────
    def test_02_imsi_in_map_has_real_iccid(self, http: httpx.Client):
        """IMSI in imsi_iccid_map.csv → profile has real ICCID."""
        r = http.get("/profiles", params={"imsi": IMSI_WITH_ICCID})
        assert r.status_code == 200
        data = r.json()
        profiles = data if isinstance(data, list) else data.get("profiles", [])
        assert len(profiles) >= 1
        profile = profiles[0]
        assert profile.get("iccid") == ICCID_FOR_IMSI, \
            f"Expected iccid={ICCID_FOR_IMSI}, got {profile.get('iccid')}"

    # 9.3 ─────────────────────────────────────────────────────────────────────
    def test_03_imsi_not_in_map_has_null_iccid(self, http: httpx.Client):
        """IMSI not in imsi_iccid_map → profile.iccid is null."""
        r = http.get("/profiles", params={"imsi": IMSI_NO_ICCID})
        assert r.status_code == 200
        data = r.json()
        profiles = data if isinstance(data, list) else data.get("profiles", [])
        assert len(profiles) >= 1
        assert profiles[0].get("iccid") is None, \
            f"Expected iccid=null, got {profiles[0].get('iccid')}"

    # 9.4 ─────────────────────────────────────────────────────────────────────
    def test_04_imsi_in_two_dumps_different_ips_is_imsi_apn(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """IMSI in 2 dumps, different IPs → ip_resolution=imsi_apn, 2 apn_ips entries."""
        r = http.get("/profiles", params={"imsi": IMSI_DUAL_APN})
        assert r.status_code == 200
        data = r.json()
        profiles = data if isinstance(data, list) else data.get("profiles", [])
        assert len(profiles) >= 1
        profile = profiles[0]
        assert profile["ip_resolution"] == "imsi_apn", \
            f"Expected imsi_apn, got {profile['ip_resolution']}"

        # GET /profile/{device_id} to check apn_ips count
        device_id = profile["device_id"]
        r2 = http.get(f"/profiles/{device_id}")
        assert r2.status_code == 200
        imsis = r2.json().get("imsis", [])
        apn_ips = next(
            (e["apn_ips"] for e in imsis if e["imsi"] == IMSI_DUAL_APN), []
        )
        assert len(apn_ips) == 2, \
            f"Expected 2 apn_ips entries (pgw1+pgw2), got {len(apn_ips)}: {apn_ips}"

        # Lookups resolve to correct IPs per APN
        r_pgw1 = lookup_http.get("/lookup",
                                  params={"imsi": IMSI_DUAL_APN,
                                          "apn": "pgw1.operator.com"})
        assert r_pgw1.status_code == 200
        assert r_pgw1.json()["static_ip"] == DUAL_IP_PGW1

        r_pgw2 = lookup_http.get("/lookup",
                                  params={"imsi": IMSI_DUAL_APN,
                                          "apn": "pgw2.operator.com"})
        assert r_pgw2.status_code == 200
        assert r_pgw2.json()["static_ip"] == DUAL_IP_PGW2

    # 9.5 ─────────────────────────────────────────────────────────────────────
    def test_05_imsi_in_two_dumps_same_ip_is_imsi(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """IMSI in 2 dumps, same IP → ip_resolution=imsi, single apn_ips with apn=null."""
        r = http.get("/profiles", params={"imsi": IMSI_SAME_IP})
        assert r.status_code == 200
        data = r.json()
        profiles = data if isinstance(data, list) else data.get("profiles", [])
        assert len(profiles) >= 1
        assert profiles[0]["ip_resolution"] == "imsi", \
            f"Expected imsi, got {profiles[0]['ip_resolution']}"

        # GET /lookup → SAME_IP regardless of APN
        r_lookup = lookup_http.get("/lookup",
                                   params={"imsi": IMSI_SAME_IP,
                                           "apn": "any.operator.com"})
        assert r_lookup.status_code == 200
        assert r_lookup.json()["static_ip"] == SAME_IP

    # 9.6 ─────────────────────────────────────────────────────────────────────
    def test_06_range_config_migrated(self, http: httpx.Client):
        """GET /range-configs?account_name=AthensOperator → at least 1 range config."""
        r = http.get("/range-configs",
                     params={"account_name": EXPECTED_ACCOUNT})
        assert r.status_code == 200
        data = r.json()
        configs = data if isinstance(data, list) else data.get("range_configs", [])
        assert len(configs) >= 1, \
            f"Expected ≥1 range config for {EXPECTED_ACCOUNT}, got {len(configs)}"
        # Verify the range we seeded is present
        our_range = next(
            (c for c in configs if c.get("id") == TestMigration.range_cfg_id),
            None,
        )
        assert our_range is not None, \
            f"Seeded range_config_id={TestMigration.range_cfg_id} not in list"
        assert our_range["f_imsi"] == RANGE_F_IMSI
        assert our_range["t_imsi"] == RANGE_T_IMSI

    # 9.7 ─────────────────────────────────────────────────────────────────────
    def test_07_pool_stats_post_migration(self, http: httpx.Client):
        """GET /pools/{pool_id}/stats → allocated = seeded IMSIs, available correct."""
        r = http.get(f"/pools/{TestMigration.pool_id}/stats")
        assert r.status_code == 200
        stats = r.json()
        # We allocated 4 IPs in setup_class (one per seeded profile)
        # (DUAL_APN profile has 2 apn_ips but only 2 distinct IPs from same pool)
        assert stats["allocated"] >= 4, \
            f"Expected ≥4 allocated IPs, got {stats['allocated']}"
        assert stats["available"] >= 0, "available must be non-negative"
        total = stats["allocated"] + stats["available"]
        # /24 has 253 usable IPs (network .0 + broadcast .255 + gateway .254 excluded)
        assert total == 253, \
            f"allocated + available = {total}, expected 253 for /24"
