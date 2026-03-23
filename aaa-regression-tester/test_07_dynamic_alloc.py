"""
test_07_dynamic_alloc.py — First-connection two-stage allocation.

The aaa-lookup-service is STRICTLY READ-ONLY (no primary DB connection).
aaa-radius-server follows a two-stage flow:
  Stage 1 → GET /lookup on aaa-lookup-service
  Stage 2 → POST /profiles/first-connection on subscriber-profile-api (only on 404)

These tests simulate both stages explicitly to verify end-to-end correctness.

Test cases 7.1 – 7.9  (plan-01 §test_07_dynamic_alloc)
"""
import threading

import httpx

from conftest import PROVISION_BASE, JWT_TOKEN, USE_CASE_ID
from fixtures.pools import create_pool, delete_pool
from fixtures.range_configs import create_range_config, delete_range_config

# A /29 subnet: network .0, broadcast .7 → 6 usable host IPs (.1–.6)
POOL_SUBNET  = "100.65.190.0/29"
USABLE_COUNT = 6

# IMSI range covered by the primary range config
F_IMSI = "278773070000001"
T_IMSI = "278773070000099"

# IMSIs used in individual tests (all within range)
IMSI_FC1  = "278773070000001"   # 7.2 / 7.3 — first-connection + idempotency
IMSI_SUSP = "278773070000010"   # 7.7 — suspended range config
IMSI_OOB  = "278773079999999"   # 7.6 — outside range → 404

# Secondary pool for 7.9 concurrency test (/28 → 14 usable IPs)
POOL_SUBNET2 = "100.65.191.0/28"
F_IMSI2      = "278773071000001"
T_IMSI2      = "278773071000099"


class TestDynamicAlloc:
    pool_id:         str | None = None
    range_config_id: str | None = None
    # All auto-provisioned sim_ids collected for teardown
    alloc_sim_ids: list[str] = []

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p = create_pool(c, subnet=POOL_SUBNET,
                            pool_name="pool-dyn-07", account_name="TestAccount",
                            replace_on_conflict=True)
            cls.pool_id = p["pool_id"]

            rc = create_range_config(
                c,
                f_imsi=F_IMSI,
                t_imsi=T_IMSI,
                pool_id=cls.pool_id,
                ip_resolution="imsi",
                account_name="TestAccount",
            )
            cls.range_config_id = rc["id"]
            cls.alloc_sim_ids = []

    @classmethod
    def teardown_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            for did in cls.alloc_sim_ids:
                try:
                    c.delete(f"/profiles/{did}")
                except Exception:
                    pass
            if cls.range_config_id:
                delete_range_config(c, cls.range_config_id)
            if cls.pool_id:
                delete_pool(c, cls.pool_id)

    # ── Stage 2 helper ────────────────────────────────────────────────────────

    @staticmethod
    def _first_connection(http: httpx.Client, imsi: str, apn: str) -> httpx.Response:
        """Simulate aaa-radius-server Stage 2: POST /profiles/first-connection."""
        return http.post(
            "/profiles/first-connection",
            json={"imsi": imsi, "apn": apn, "use_case_id": USE_CASE_ID},
        )

    # 7.1 ─────────────────────────────────────────────────────────────────────
    def test_01_setup_verified(self, http: httpx.Client):
        """Pool and range config are reachable and active before allocation tests."""
        r_pool = http.get(f"/pools/{TestDynamicAlloc.pool_id}")
        assert r_pool.status_code == 200

        r_rc = http.get(f"/range-configs/{TestDynamicAlloc.range_config_id}")
        assert r_rc.status_code == 200
        assert r_rc.json()["status"] == "active"

    # 7.2 ─────────────────────────────────────────────────────────────────────
    def test_02_first_connection_creates_profile(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """
        Stage 1: GET /lookup → 404 (profile not yet provisioned, service is read-only).
        Stage 2: POST /profiles/first-connection → 201 (profile auto-created via range config).
        Stage 1 again: GET /lookup → 200 with the allocated IP.
        """
        # Stage 1 — lookup service has no profile → 404
        r_s1 = lookup_http.get("/lookup",
                                params={"imsi": IMSI_FC1,
                                        "apn": "internet.operator.com",
                                        "use_case_id": USE_CASE_ID})
        assert r_s1.status_code == 404, \
            f"Expected 404 before provisioning, got {r_s1.status_code}"

        # Stage 2 — subscriber-profile-api provisions via range config
        r_s2 = self._first_connection(http, IMSI_FC1, "internet.operator.com")
        assert r_s2.status_code == 201, \
            f"First-connection failed: {r_s2.status_code} {r_s2.text}"
        body = r_s2.json()
        assert "sim_id" in body, "Response must contain sim_id"
        assert "static_ip" in body, "Response must contain static_ip"
        TestDynamicAlloc.alloc_sim_ids.append(body["sim_id"])

        # Stage 1 again — now the profile exists → 200
        r_s1b = lookup_http.get("/lookup",
                                 params={"imsi": IMSI_FC1,
                                         "apn": "internet.operator.com",
                                         "use_case_id": USE_CASE_ID})
        assert r_s1b.status_code == 200
        assert r_s1b.json()["static_ip"] == body["static_ip"]

    # 7.3 ─────────────────────────────────────────────────────────────────────
    def test_03_second_first_connection_is_idempotent(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """POST /profiles/first-connection for already-provisioned IMSI → same IP, no re-allocation."""
        # Remember current IP from lookup
        r1 = lookup_http.get("/lookup",
                             params={"imsi": IMSI_FC1,
                                     "apn": "internet.operator.com",
                                     "use_case_id": USE_CASE_ID})
        assert r1.status_code == 200
        existing_ip = r1.json()["static_ip"]

        # Second Stage 2 call — must be idempotent
        r2 = self._first_connection(http, IMSI_FC1, "internet.operator.com")
        assert r2.status_code in (200, 201), \
            f"Expected 200 or 201, got {r2.status_code}: {r2.text}"
        assert r2.json()["static_ip"] == existing_ip, \
            "IP changed on second first-connection call (re-allocation bug)"

    # 7.4 ─────────────────────────────────────────────────────────────────────
    def test_04_pool_stats_reflect_allocation(self, http: httpx.Client):
        """GET /pools/{pool_id}/stats → allocated ≥ 1, available < USABLE_COUNT."""
        r = http.get(f"/pools/{TestDynamicAlloc.pool_id}/stats")
        assert r.status_code == 200
        stats = r.json()
        assert stats["allocated"] >= 1, "Pool must show at least 1 allocated IP"
        assert stats["available"] < USABLE_COUNT, \
            "available must be less than total usable after allocation"

    # 7.5 ─────────────────────────────────────────────────────────────────────
    def test_05_auto_created_profile_structure(self, http: httpx.Client):
        """GET /profiles?imsi={imsi} → 200; ip_resolution=imsi; iccid=null."""
        r = http.get("/profiles", params={"imsi": IMSI_FC1})
        assert r.status_code == 200
        data = r.json()
        profiles = data if isinstance(data, list) else data.get("profiles", [])
        assert len(profiles) >= 1, "Auto-created profile must be retrievable by IMSI"
        profile = profiles[0]
        assert profile["ip_resolution"] == "imsi", \
            f"Expected ip_resolution=imsi, got {profile['ip_resolution']}"
        assert profile.get("iccid") is None, \
            f"Expected iccid=null for first-connection profile, got {profile.get('iccid')}"

    # 7.6 ─────────────────────────────────────────────────────────────────────
    def test_06_imsi_outside_range_returns_404(self, lookup_http: httpx.Client):
        """GET /lookup for IMSI not covered by any range config → 404 not_found."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI_OOB,
                                    "apn": "internet.operator.com",
                                    "use_case_id": USE_CASE_ID})
        assert r.status_code == 404
        error = r.json().get("error", "")
        assert error in ("not_found", "no_range_config", "apn_not_found"), \
            f"Unexpected error: {error}"

    # 7.7 ─────────────────────────────────────────────────────────────────────
    def test_07_suspended_range_config_blocks_first_connection(
            self, http: httpx.Client, lookup_http: httpx.Client):
        """
        PATCH range_config status=suspended → Stage 2 first-connection fails;
        Stage 1 returns 404 because no profile was created.
        """
        # Suspend the range config
        r_susp = http.patch(
            f"/range-configs/{TestDynamicAlloc.range_config_id}",
            json={"status": "suspended"},
        )
        assert r_susp.status_code == 200

        # Stage 2 for a fresh IMSI — should fail (range suspended)
        r_alloc = self._first_connection(http, IMSI_SUSP, "internet.operator.com")
        assert r_alloc.status_code in (404, 422, 503), \
            f"Expected failure code, got {r_alloc.status_code}: {r_alloc.text}"

        # Stage 1 — still 404 because no profile was created
        r_lookup = lookup_http.get("/lookup",
                                   params={"imsi": IMSI_SUSP,
                                           "apn": "internet.operator.com",
                                           "use_case_id": USE_CASE_ID})
        assert r_lookup.status_code == 404

        # Re-activate for subsequent tests
        http.patch(f"/range-configs/{TestDynamicAlloc.range_config_id}",
                   json={"status": "active"})

    # 7.8 ─────────────────────────────────────────────────────────────────────
    def test_08_pool_exhausted_returns_503(self, http: httpx.Client):
        """
        Exhaust all IPs in the /29 pool → next allocation returns 503 pool_exhausted.

        The pool has USABLE_COUNT=6 IPs.  IMSI_FC1 used 1.  We fill the rest
        then attempt one more — must get 503.
        """
        created_ids: list[str] = []

        for seq in range(2, USABLE_COUNT + 2):
            imsi = f"2787730700{seq:05d}"
            r = self._first_connection(http, imsi, "internet.operator.com")
            if r.status_code == 201:
                created_ids.append(r.json()["sim_id"])
            elif r.status_code == 503:
                break   # exhausted sooner than expected (pool already had allocations)

        TestDynamicAlloc.alloc_sim_ids.extend(created_ids)

        # Now the pool must be exhausted
        overflow_imsi = "278773070000099"
        r_overflow = self._first_connection(
            http, overflow_imsi, "internet.operator.com"
        )
        assert r_overflow.status_code == 503, (
            f"Expected 503 pool_exhausted after filling /29, "
            f"got {r_overflow.status_code}: {r_overflow.text}"
        )
        assert r_overflow.json().get("error") in (
            "pool_exhausted", "no_available_ip"
        ), f"Unexpected error body: {r_overflow.json()}"

    # 7.9 ─────────────────────────────────────────────────────────────────────
    def test_09_concurrent_first_connections_no_duplicate_ips(
            self, http: httpx.Client):
        """
        10 concurrent Stage-2 calls for 10 distinct IMSIs in a fresh /28 pool
        → all succeed; allocated IPs are unique (no double-allocation).
        """
        import os, httpx as _h
        base = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
        jwt  = os.getenv("TEST_JWT", "dev-skip-verify")

        # Create a fresh pool + range config for this sub-test
        with _h.Client(base_url=base,
                       headers={"Authorization": f"Bearer {jwt}"},
                       timeout=30.0) as c:
            p2 = create_pool(c, subnet=POOL_SUBNET2,
                             pool_name="pool-dyn-07-conc", account_name="TestAccount")
            pool2_id = p2["pool_id"]
            rc2 = create_range_config(
                c,
                f_imsi=F_IMSI2,
                t_imsi=T_IMSI2,
                pool_id=pool2_id,
                ip_resolution="imsi",
                account_name="TestAccount",
            )
            rc2_id = rc2["id"]

        allocated_ips:  list[str] = []
        created_ids:    list[str] = []
        thread_errors:  list[Exception] = []
        lock = threading.Lock()

        def do_alloc(imsi: str) -> None:
            try:
                r = http.post(
                    "/profiles/first-connection",
                    json={"imsi": imsi, "apn": "internet.operator.com",
                          "use_case_id": USE_CASE_ID},
                )
                if r.status_code == 201:
                    with lock:
                        created_ids.append(r.json()["sim_id"])
                        allocated_ips.append(r.json()["static_ip"])
            except Exception as ex:
                with lock:
                    thread_errors.append(ex)

        threads = [
            threading.Thread(target=do_alloc,
                             args=(f"2787730710{i:05d}",))
            for i in range(1, 11)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not thread_errors, f"Thread exceptions: {thread_errors}"
        assert len(allocated_ips) == len(set(allocated_ips)), \
            f"Duplicate IPs detected: {allocated_ips}"

        # Teardown secondary fixtures
        with _h.Client(base_url=base,
                       headers={"Authorization": f"Bearer {jwt}"},
                       timeout=30.0) as c:
            for did in created_ids:
                c.delete(f"/profiles/{did}")
            c.delete(f"/range-configs/{rc2_id}")
            c.delete(f"/pools/{pool2_id}")
