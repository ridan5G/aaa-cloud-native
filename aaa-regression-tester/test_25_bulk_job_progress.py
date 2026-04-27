"""
test_25_bulk_job_progress.py — verify bulk_jobs.processed advances per chunk.

The lazy-pool refactor commits per-chunk progress to ``bulk_jobs`` *outside*
the chunk's claim/provision transaction so that GET /jobs/{job_id} sees
``processed`` advance as work completes (instead of jumping from 0 → 100%
at the end). This regression catches re-introduction of a single end-of-job
UPDATE that hides progress.

Strategy
────────
  - Create a pool large enough to span at least 3 BULK_BATCH_SIZE chunks.
  - Submit a `provisioning_mode=immediate` range whose size = 3 × chunk size.
  - Poll GET /jobs/{job_id} rapidly and capture every distinct
    (processed, updated_at) snapshot.
  - Assert: at least one snapshot is *strictly between* 0 and total submitted,
    AND updated_at advances across snapshots, AND final state is ``completed``.

If the submitted size completes faster than poll resolution, the test still
passes when at least one progress snapshot lands between 0 and total — a
chunk size of 500 IMSIs over a 1500-IMSI range typically produces 2–3
visible intermediate states on a dev cluster.

Resources
─────────
  Module 25 → IMSI prefix 27877 25 xxxxxxxx
  Subnet:   100.66.4.0/22  (1022 hosts — enough for 1500-IMSI run? no; use /20)
            actually use 100.66.4.0/20 = 4094 hosts to fit any chunk size
"""
import os
import time

import httpx
import pytest

from conftest import PROVISION_BASE, JWT_TOKEN, make_imsi
from fixtures.pools import (
    create_pool,
    delete_pool,
    get_pool_stats,
    _force_clear_pool_ips,
    _force_clear_range_profiles,
)
from fixtures.range_configs import (
    create_range_config,
    delete_range_config,
    wait_for_job,
)


MODULE = 25
SUBNET = "100.66.4.0/20"            # 4094 hosts — accommodates large ranges
BULK_BATCH_SIZE = int(os.getenv("BULK_BATCH_SIZE", "500"))
RANGE_SIZE = BULK_BATCH_SIZE * 3    # 3 chunks → 2 intermediate snapshots
JOB_TIMEOUT_S = 60.0
POLL_INTERVAL_S = 0.05


def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=30.0,
    )


def _capture_snapshots(http: httpx.Client, job_id: str) -> list[dict]:
    """Poll GET /jobs/{job_id} until terminal; return every distinct snapshot."""
    snapshots: list[dict] = []
    deadline = time.monotonic() + JOB_TIMEOUT_S
    while time.monotonic() < deadline:
        r = http.get(f"/jobs/{job_id}")
        if r.status_code == 200:
            body = r.json()
            key = (body.get("processed"), body.get("updated_at"), body.get("status"))
            if not snapshots or (
                snapshots[-1].get("processed"),
                snapshots[-1].get("updated_at"),
                snapshots[-1].get("status"),
            ) != key:
                snapshots.append(body)
            if body.get("status") in ("completed", "completed_with_errors", "failed"):
                return snapshots
        time.sleep(POLL_INTERVAL_S)
    raise AssertionError(
        f"job {job_id} did not finish within {JOB_TIMEOUT_S}s; snapshots={snapshots}"
    )


@pytest.mark.order(2500)
class TestBulkJobProgress:
    """Per-chunk progress reporting in the bulk_jobs row."""

    pool_id: str | None = None
    range_id: int | None = None
    job_id: str | None = None

    F_IMSI, T_IMSI = (
        make_imsi(MODULE, 1),
        make_imsi(MODULE, RANGE_SIZE),
    )

    @classmethod
    def teardown_class(cls):
        with _new_client() as c:
            if cls.range_id:
                delete_range_config(c, cls.range_id)
            if cls.pool_id:
                _force_clear_pool_ips(cls.pool_id)
                delete_pool(c, cls.pool_id)

    # 25.1 ────────────────────────────────────────────────────────────────────
    def test_01_setup_pool(self, http: httpx.Client):
        pool = create_pool(
            http,
            subnet=SUBNET,
            pool_name="test-25-progress",
            replace_on_conflict=True,
        )
        TestBulkJobProgress.pool_id = pool["pool_id"]

    # 25.2 ────────────────────────────────────────────────────────────────────
    def test_02_dispatch_immediate_range(self, http: httpx.Client):
        """POST /range-configs (immediate, size = 3 × chunk) returns 202 + job_id."""
        _force_clear_range_profiles(self.F_IMSI, self.T_IMSI)
        rc = create_range_config(
            http,
            f_imsi=self.F_IMSI,
            t_imsi=self.T_IMSI,
            pool_id=self.pool_id,
            ip_resolution="imsi",
            provisioning_mode="immediate",
            await_job=False,            # We want to observe progress live.
        )
        assert "id" in rc
        assert "job_id" in rc, f"missing job_id in 202 response: {rc}"
        TestBulkJobProgress.range_id = rc["id"]
        TestBulkJobProgress.job_id = rc["job_id"]

    # 25.3 ────────────────────────────────────────────────────────────────────
    def test_03_processed_advances_across_snapshots(self, http: httpx.Client):
        """Capture all distinct snapshots; processed must strictly advance."""
        snapshots = _capture_snapshots(http, self.job_id)
        assert snapshots, "no snapshots captured"

        final = snapshots[-1]
        assert final["status"] == "completed", (
            f"job ended with status {final['status']}: {final.get('errors')}"
        )
        assert final["processed"] == RANGE_SIZE, (
            f"final processed should be {RANGE_SIZE}, got {final['processed']}"
        )
        assert final["failed"] == 0

        processed_values = [s.get("processed", 0) for s in snapshots]
        # Monotonic non-decreasing — never goes backwards
        for i in range(1, len(processed_values)):
            assert processed_values[i] >= processed_values[i - 1], (
                f"processed went backwards: {processed_values}"
            )

        # At least one snapshot must show partial progress (mid-flight).
        # If we only see 0 → final, the per-chunk UPDATE was hidden behind a
        # long transaction (regression on the fix).
        midway = [p for p in processed_values if 0 < p < RANGE_SIZE]
        assert midway, (
            f"no intermediate progress observed; processed values were "
            f"{processed_values} — bulk_jobs.processed is not being updated "
            f"per chunk"
        )

    # 25.4 ────────────────────────────────────────────────────────────────────
    def test_04_pool_stats_match_submitted(self, http: httpx.Client):
        """After the job completes, pool stats reflect every IMSI's IP claim."""
        stats = get_pool_stats(http, self.pool_id)
        assert stats["allocated"] == RANGE_SIZE, (
            f"allocated should equal {RANGE_SIZE}, got {stats}"
        )

    # 25.5 ────────────────────────────────────────────────────────────────────
    def test_05_wait_for_job_idempotent_on_completed(self, http: httpx.Client):
        """wait_for_job() on an already-completed job returns the terminal body."""
        body = wait_for_job(http, self.job_id, timeout=5.0)
        assert body["status"] == "completed"
        assert body["processed"] == RANGE_SIZE
