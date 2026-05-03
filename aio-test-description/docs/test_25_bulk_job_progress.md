# Test Suite 25 — Per-Chunk Bulk Job Progress

## What this test suite validates

The lazy-pool refactor commits per-chunk progress to the `bulk_jobs` row **outside** each chunk's claim/provision transaction so that `GET /jobs/{job_id}` sees `processed` advance as work completes — instead of jumping from 0 → 100% only at the very end. This regression test catches re-introduction of a single end-of-job UPDATE that hides progress.

The strategy:

1. Create a pool large enough to span at least three `BULK_BATCH_SIZE` chunks.
2. Submit a `provisioning_mode=immediate` range whose size equals `3 × BULK_BATCH_SIZE` (typically 1500 IMSIs over a 500-chunk).
3. Poll `GET /jobs/{job_id}` rapidly and capture every distinct `(processed, updated_at, status)` snapshot.
4. Assert: at least one snapshot shows `0 < processed < total` (mid-flight), `processed` is monotonically non-decreasing, and the final state is `completed`.

If the job finishes faster than poll resolution (50 ms), the test still passes provided at least one intermediate snapshot lands.

## Pre-conditions (Setup)

- Module 25 → IMSI prefix `27877 25 xxxxxxxx`
- Subnet: `100.66.32.0/20` (4094 hosts, accommodates a 3-chunk run with headroom)
- `BULK_BATCH_SIZE` defaults to **500** (overridable via env var).
- `RANGE_SIZE = BULK_BATCH_SIZE × 3` → 1500 IMSIs.
- Job timeout: 60 s; poll interval: 50 ms.

A single `TestBulkJobProgress` class runs all five tests sequentially with `@pytest.mark.order(2500)`.

---

## Test 25.1 — Pool setup

Create the `100.66.32.0/20` pool. Capture `pool_id` for later tests.

## Test 25.2 — Dispatch an immediate-mode range and capture the job_id

**Goal:** `POST /range-configs` with `provisioning_mode="immediate"` and `await_job=False` returns the new range plus a `job_id` for the background provisioning job.

1. Create the range config with `f_imsi`/`t_imsi` covering 1500 IMSIs.
2. Assert the response contains both `id` and `job_id`.

## Test 25.3 — `processed` advances strictly across snapshots

**Goal:** The core regression assertion.

1. Poll `GET /jobs/{job_id}` every 50 ms until the status reaches a terminal state (`completed`, `completed_with_errors`, or `failed`). Capture every snapshot whose `(processed, updated_at, status)` tuple changed.
2. Assert the final snapshot has `status="completed"`, `processed == 1500`, `failed == 0`.
3. Assert the `processed` values across snapshots are monotonically non-decreasing (never go backwards).
4. Assert **at least one** snapshot exists with `0 < processed < 1500`. If we only see `0 → 1500`, the per-chunk UPDATE was hidden behind a long transaction — the regression. The error message lists the captured `processed` values to make diagnosis easy.

## Test 25.4 — Pool stats match the submitted size

**Goal:** End-to-end accounting check after the job finishes.

1. `GET /pools/{id}/stats`.
2. Assert `allocated == 1500`.

## Test 25.5 — `wait_for_job()` is idempotent on a completed job

**Goal:** The fixture helper returns the terminal body cleanly even if the job has already finished.

1. Call `wait_for_job(http, job_id, timeout=5.0)`.
2. Assert `status="completed"` and `processed == 1500`.

---

## Post-conditions (Teardown)

The class deletes the range config (releases all 1500 IPs), force-clears any leftover pool IPs in `ip_pool_available`, and deletes the pool.
