"""
test_11_performance.py — Latency assertions under concurrent load.

Prerequisites:
  - A pre-seeded dataset of ≥300 000 profiles must be present in the test DB.
  - The seed fixture runs once (skipped if already loaded) and takes ~3 min.

All timing measurements are end-to-end from test client to API response.
p99 is computed from raw latency samples using linear interpolation.

Marked @pytest.mark.slow — excluded from the default CI run; enable with:
    pytest -m slow

Test cases 11.1 – 11.7  (plan-01 §test_11_performance)
"""
import asyncio
import time

import httpx
import pytest

from conftest import (
    make_imsi,
    make_ip,
    percentile,
    TimingRecorder,
    PROVISION_BASE,
    JWT_TOKEN,
    LOOKUP_BASE,
    USE_CASE_ID,
)
from fixtures.pools import create_pool, delete_pool

pytestmark = pytest.mark.slow

MODULE = 11

# ── Performance thresholds ────────────────────────────────────────────────────
P99_SEQUENTIAL_MS  =  15.0   # 11.1
P99_CONCURRENT_MS  =  15.0   # 11.2  (50 concurrent)
P99_STRESS_MS      =  30.0   # 11.3  (200 concurrent)
STATS_RESPONSE_MS  = 200.0   # 11.6
PROFILE_GET_MS     =  50.0   # 11.7

# ── Seed dataset constants ────────────────────────────────────────────────────
SEED_POOL_SUBNET   = "100.68.0.0/14"    # 2^18 = 262 144 usable → enough for 300K (with /14)
SEED_PROFILE_COUNT = 300_000
SEED_BATCH_SIZE    = 1_000              # profiles per bulk POST
SEED_ACCOUNT       = "PerfAccount"
SEED_MARKER_IMSI   = make_imsi(MODULE, 1)   # first seed IMSI — used to check if seeded


class _PerfSetup:
    """Class-level shared state for all performance tests."""
    pool_id:   str | None = None
    seeded:    bool = False


def _is_seeded(http: httpx.Client) -> bool:
    """Return True if the seed dataset is already loaded."""
    r = http.get("/profiles", params={"imsi": SEED_MARKER_IMSI})
    if r.status_code == 200:
        data = r.json()
        profiles = data if isinstance(data, list) else data.get("profiles", [])
        return len(profiles) > 0
    return False


def _seed_dataset(http: httpx.Client, pool_id: str) -> None:
    """Seed SEED_PROFILE_COUNT profiles via bulk API in SEED_BATCH_SIZE batches."""
    from conftest import poll_until

    print(f"\nSeeding {SEED_PROFILE_COUNT:,} profiles for performance tests …")
    total_batches = SEED_PROFILE_COUNT // SEED_BATCH_SIZE

    for batch_idx in range(total_batches):
        base_seq = batch_idx * SEED_BATCH_SIZE + 1
        profiles = []
        for i in range(SEED_BATCH_SIZE):
            seq = base_seq + i
            imsi = make_imsi(MODULE, seq)
            # Distribute IPs across the /14 address space
            fourth = (seq % 253) + 1
            third  = ((seq // 253) % 256)
            second = 68 + ((seq // (253 * 256)) % 4)
            ip = f"100.{second}.{third}.{fourth}"
            profiles.append({
                "iccid":         None,
                "account_name":  SEED_ACCOUNT,
                "status":        "active",
                "ip_resolution": "imsi",
                "imsis": [
                    {"imsi": imsi,
                     "apn_ips": [{"static_ip": ip, "pool_id": pool_id,
                                  "pool_name": "perf-pool"}]},
                ],
            })

        r = http.post("/profiles/bulk", json=profiles, timeout=120.0)
        assert r.status_code == 202, \
            f"Bulk seed batch {batch_idx} failed: {r.status_code} {r.text}"
        job_id = r.json()["job_id"]

        # Poll for completion before next batch
        def check_job():
            return http.get(f"/jobs/{job_id}").json()

        result = poll_until(
            check_job,
            condition=lambda j: j.get("status") in ("completed", "failed"),
            timeout=300.0,
            interval=10.0,
            label=f"seed batch {batch_idx + 1}/{total_batches}",
        )
        if result["status"] != "completed":
            raise RuntimeError(
                f"Seed batch {batch_idx} ended with status={result['status']}: {result}"
            )
        if (batch_idx + 1) % 50 == 0:
            print(f"  {(batch_idx + 1) * SEED_BATCH_SIZE:,} / {SEED_PROFILE_COUNT:,} seeded …")

    print(f"Seed complete: {SEED_PROFILE_COUNT:,} profiles loaded.")


class TestPerformance:

    @classmethod
    def setup_class(cls):
        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=120.0) as c:
            if _is_seeded(c):
                # Dataset already present — find the pool
                r = c.get("/profiles", params={"imsi": SEED_MARKER_IMSI})
                data = r.json()
                profiles = data if isinstance(data, list) else data.get("profiles", [])
                if profiles:
                    _PerfSetup.pool_id = profiles[0].get("pool_id")
                _PerfSetup.seeded = True
                return

            # Create pool and seed
            p = create_pool(c, subnet=SEED_POOL_SUBNET,
                            pool_name="perf-pool", account_name=SEED_ACCOUNT,
                            replace_on_conflict=True)
            _PerfSetup.pool_id = p["pool_id"]
            _seed_dataset(c, _PerfSetup.pool_id)
            _PerfSetup.seeded = True

    @classmethod
    def teardown_class(cls):
        # NOTE: We intentionally do NOT delete the seeded pool/profiles here.
        # The 300K dataset takes ~3 min to seed; destroying it would force a
        # re-seed on the next run.  Clean up manually with:
        #   DELETE FROM sim_profiles WHERE account_name='PerfAccount';
        pass

    # ── Async helper ──────────────────────────────────────────────────────────

    @staticmethod
    async def _concurrent_lookups(
        base_url: str,
        auth: str,
        params_list: list[dict],
        timeout: float = 10.0,
    ) -> list[tuple[int, float]]:
        """Fire params_list concurrently; return [(status_code, latency_ms)]."""
        async with httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {auth}"},
            timeout=timeout,
        ) as client:
            async def one(params: dict) -> tuple[int, float]:
                t0 = time.perf_counter()
                r = await client.get("/lookup", params=params)
                return r.status_code, (time.perf_counter() - t0) * 1000.0

            return await asyncio.gather(*[one(p) for p in params_list])

    # 11.1 ────────────────────────────────────────────────────────────────────
    def test_01_sequential_lookup_p99(
            self, lookup_http: httpx.Client, timing: TimingRecorder):
        """100 sequential GET /lookup (warm DB, existing profiles) → p99 ≤ 15 ms."""
        latencies: list[float] = []
        for seq in range(1, 101):
            imsi = make_imsi(MODULE, seq)
            t0 = time.perf_counter()
            r = lookup_http.get("/lookup",
                                params={"imsi": imsi,
                                        "apn": "internet.operator.com",
                                        "use_case_id": USE_CASE_ID})
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            assert r.status_code == 200, \
                f"Lookup failed for {imsi}: {r.status_code}"
            latencies.append(elapsed_ms)

        p99 = percentile(latencies, 99)
        timing.record("test_11_sequential", p99)
        assert p99 <= P99_SEQUENTIAL_MS, \
            f"p99 sequential = {p99:.2f} ms > {P99_SEQUENTIAL_MS} ms threshold"

    # 11.2 ────────────────────────────────────────────────────────────────────
    def test_02_concurrent_50_lookup_p99(self, timing: TimingRecorder):
        """50 concurrent GET /lookup → p99 ≤ 15 ms; 0 errors."""
        params_list = [
            {"imsi": make_imsi(MODULE, seq), "apn": "internet.operator.com"}
            for seq in range(101, 151)
        ]

        results = asyncio.run(
            self._concurrent_lookups(LOOKUP_BASE, JWT_TOKEN, params_list)
        )

        statuses  = [r[0] for r in results]
        latencies = [r[1] for r in results]
        errors    = [s for s in statuses if s != 200]
        assert not errors, f"{len(errors)} lookup error(s): {errors}"

        p99 = percentile(latencies, 99)
        timing.record("test_11_concurrent_50", p99)
        assert p99 <= P99_CONCURRENT_MS, \
            f"p99 (50 concurrent) = {p99:.2f} ms > {P99_CONCURRENT_MS} ms"

    # 11.3 ────────────────────────────────────────────────────────────────────
    def test_03_concurrent_200_lookup_p99(self, timing: TimingRecorder):
        """200 concurrent GET /lookup (stress) → p99 ≤ 30 ms; 0 errors."""
        params_list = [
            {"imsi": make_imsi(MODULE, seq), "apn": "internet.operator.com"}
            for seq in range(151, 351)
        ]

        results = asyncio.run(
            self._concurrent_lookups(LOOKUP_BASE, JWT_TOKEN, params_list)
        )

        statuses  = [r[0] for r in results]
        latencies = [r[1] for r in results]
        errors    = [s for s in statuses if s != 200]
        assert not errors, f"{len(errors)} lookup error(s) under 200-concurrent: {errors}"

        p99 = percentile(latencies, 99)
        timing.record("test_11_stress_200", p99)
        assert p99 <= P99_STRESS_MS, \
            f"p99 (200 concurrent) = {p99:.2f} ms > {P99_STRESS_MS} ms"

    # 11.4 ────────────────────────────────────────────────────────────────────
    def test_04_concurrent_bulk_jobs(self, http: httpx.Client):
        """10 concurrent POST /profiles/bulk (100 profiles each) → all complete; 0 errors."""
        import threading
        from conftest import poll_until

        base_seq_start = 290_000   # well into the seeded range for unique sequences

        job_ids:    list[str] = []
        lock = threading.Lock()

        def submit(batch_offset: int) -> None:
            profiles = []
            for i in range(100):
                seq  = base_seq_start + batch_offset * 100 + i + 1
                imsi = make_imsi(MODULE, seq)
                fourth = (seq % 253) + 1
                third  = ((seq // 253) % 256)
                second = 72 + ((seq // (253 * 256)) % 4)
                ip = f"100.{second}.{third}.{fourth}"
                profiles.append({
                    "iccid": None,
                    "account_name": SEED_ACCOUNT,
                    "status": "active",
                    "ip_resolution": "imsi",
                    "imsis": [
                        {"imsi": imsi,
                         "apn_ips": [{"static_ip": ip,
                                      "pool_id": _PerfSetup.pool_id,
                                      "pool_name": "perf-pool"}]},
                    ],
                })
            r = http.post("/profiles/bulk", json=profiles, timeout=60.0)
            assert r.status_code == 202, \
                f"Bulk submit failed: {r.status_code} {r.text}"
            with lock:
                job_ids.append(r.json()["job_id"])

        threads = [threading.Thread(target=submit, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(job_ids) == 10, \
            f"Expected 10 job_ids, got {len(job_ids)}"

        # Poll all jobs to completion
        for jid in job_ids:
            result = poll_until(
                lambda: http.get(f"/jobs/{jid}").json(),
                condition=lambda j: j.get("status") in ("completed", "failed"),
                timeout=300.0,
                interval=10.0,
                label=f"concurrent bulk job {jid}",
            )
            assert result["status"] == "completed", \
                f"Bulk job {jid} failed: {result}"
            assert result.get("failed", 0) == 0

    # 11.5 ────────────────────────────────────────────────────────────────────
    def test_05_concurrent_first_connection_no_duplicates(self, http: httpx.Client):
        """10 concurrent first-connection requests for 10 distinct IMSIs → all succeed; 0 dup IPs."""
        import threading

        # Use a fresh tiny pool for this sub-test to keep things isolated
        from fixtures.range_configs import create_range_config, delete_range_config

        with httpx.Client(base_url=PROVISION_BASE,
                          headers={"Authorization": f"Bearer {JWT_TOKEN}"},
                          timeout=30.0) as c:
            p2 = create_pool(c, subnet="100.67.0.0/28",   # 14 usable IPs
                             pool_name="perf-fc-pool",
                             account_name=SEED_ACCOUNT)
            pool2_id = p2["pool_id"]
            fc_f = make_imsi(MODULE, 400_001)
            fc_t = make_imsi(MODULE, 400_099)
            rc2 = create_range_config(
                c, f_imsi=fc_f, t_imsi=fc_t,
                pool_id=pool2_id,
                ip_resolution="imsi",
                account_name=SEED_ACCOUNT,
            )
            rc2_id = rc2["id"]

        allocated_ips: list[str] = []
        sim_ids:    list[str] = []
        errors:        list[Exception] = []
        lock = threading.Lock()

        def do_fc(seq: int) -> None:
            try:
                r = http.post("/profiles/first-connection",
                              json={"imsi": make_imsi(MODULE, 400_000 + seq),
                                    "apn": "internet.operator.com"})
                if r.status_code == 201:
                    with lock:
                        sim_ids.append(r.json()["sim_id"])
                        allocated_ips.append(r.json()["static_ip"])
            except Exception as ex:
                with lock:
                    errors.append(ex)

        threads = [threading.Thread(target=do_fc, args=(i,)) for i in range(1, 11)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread exceptions: {errors}"
        assert len(allocated_ips) == len(set(allocated_ips)), \
            f"Duplicate IPs: {allocated_ips}"

        # Teardown
        with httpx.Client(base_url=base,
                          headers={"Authorization": f"Bearer {jwt}"},
                          timeout=30.0) as c:
            from fixtures.range_configs import delete_range_config
            for did in sim_ids:
                c.delete(f"/profiles/{did}")
            delete_range_config(c, rc2_id)
            delete_pool(c, pool2_id)

    # 11.6 ────────────────────────────────────────────────────────────────────
    def test_06_pool_stats_with_large_allocation(
            self, http: httpx.Client, timing: TimingRecorder):
        """GET /pools/{pool_id}/stats with 300K allocated rows → response ≤ 200 ms."""
        assert _PerfSetup.pool_id, "Pool not set — seed must have succeeded"

        t0 = time.perf_counter()
        r  = http.get(f"/pools/{_PerfSetup.pool_id}/stats")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert r.status_code == 200, f"Pool stats failed: {r.status_code}"
        stats = r.json()
        assert stats["allocated"] >= 1_000, \
            f"Expected ≥1000 allocated, got {stats['allocated']}"

        timing.record("test_11_pool_stats", elapsed_ms)
        assert elapsed_ms <= STATS_RESPONSE_MS, \
            f"Pool stats took {elapsed_ms:.1f} ms > {STATS_RESPONSE_MS} ms threshold"

    # 11.7 ────────────────────────────────────────────────────────────────────
    def test_07_get_profile_response_time(
            self, http: httpx.Client, timing: TimingRecorder):
        """GET /profiles/{sim_id} for a full profile (many IMSIs) → ≤ 50 ms."""
        # Find a profile that exists in the seeded dataset
        r_list = http.get("/profiles", params={"imsi": make_imsi(MODULE, 1)})
        assert r_list.status_code == 200
        data = r_list.json()
        profiles = data if isinstance(data, list) else data.get("profiles", [])
        assert profiles, "Seed profile not found — seed must have succeeded"

        sim_id = profiles[0]["sim_id"]

        latencies: list[float] = []
        for _ in range(20):
            t0 = time.perf_counter()
            r = http.get(f"/profiles/{sim_id}")
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            assert r.status_code == 200
            latencies.append(elapsed_ms)

        p99 = percentile(latencies, 99)
        timing.record("test_11_get_profile", p99)
        assert p99 <= PROFILE_GET_MS, \
            f"GET /profiles p99 = {p99:.2f} ms > {PROFILE_GET_MS} ms threshold"
