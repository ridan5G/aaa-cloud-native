#!/usr/bin/env python3
"""
radius_load.py — RADIUS protocol load test.

Setup phase (runs once before load):
  - Creates (or finds) the first-connect IP pool  (100.65.0.0/20) via subscriber-profile-api
  - Creates (or finds) the IMSI range config covering first-connect IMSIs
  - Probes one fast-path IMSI via RADIUS to confirm fast-path data is seeded

Two concurrent senders:
  A. Fast-path     : stepped tiers 300 → 400 → 500 → 600 RPS
                     Random known IMSI from 10K pre-provisioned pool.
                     Expected response: Access-Accept (IP already in imsi_apn_ips).

  B. First-connect : constant 2 RPS throughout all tiers.
                     Sequential new IMSIs (in imsi_range_configs but NOT in imsi2sim).
                     Expected response: Access-Accept after subscriber-profile-api
                     first-connection provisioning.

Prometheus CPU + RAM collected per pod after each tier.

Outputs (./results/):
  summary.json    — per-tier latency + error stats
  pod-metrics.json — CPU/RAM avg/max per pod per tier
  report.md       — human-readable Markdown tables
"""

import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import requests as _requests

from radius_client import CODE_ACCESS_ACCEPT, CODE_ACCESS_REJECT, RadiusClient

# ── Config from environment ───────────────────────────────────────────────────

RADIUS_HOST    = os.environ.get("RADIUS_HOST",    "aaa-radius-server")
RADIUS_PORT    = int(os.environ.get("RADIUS_PORT", "1812"))
RADIUS_SECRET  = os.environ.get("RADIUS_SECRET",  "testing123")

API_URL        = os.environ.get("API_URL", "http://aaa-platform-subscriber-profile-api:8080")
API_TOKEN      = os.environ.get("API_TOKEN", "dev-load-test")  # ignored when JWT_SKIP_VERIFY=true

PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://aaa-platform-kube-promethe-prometheus.aaa-platform.svc:9090",
)

IMSI_COUNT       = int(os.environ.get("IMSI_COUNT",       "10000"))
FIRSTCONN_RPS    = int(os.environ.get("FIRSTCONN_RPS",    "2"))
TIER_DURATION_S  = int(os.environ.get("TIER_DURATION_S",  "300"))

# First-connect IMSI pool base — created dynamically by setup()
_FIRSTCONN_BASE = int(os.environ.get("FIRSTCONN_IMSI_START", "1010000011001"))

# Fast-path pool parameters (pool seeded once; warmed up via RADIUS in setup)
# imsi_apn resolution: one IP per IMSI+APN combo — 10K IMSIs × 3 APNs = 30K IPs needed
# 100.64.0.0/16 provides 65 534 usable hosts
_FP_POOL_NAME   = "load-test-fastpath"
_FP_POOL_SUBNET = "100.64.0.0/16"
_FP_ACCOUNT     = "LoadTestAccount"
_FP_IMSI_FROM   = "001010000001001"
_FP_IMSI_TO     = "001010000011000"

# First-connect pool parameters
_FC_POOL_NAME   = "load-test-firstconn"
_FC_POOL_SUBNET = "100.65.0.0/20"
_FC_ACCOUNT     = "LoadTestAccount"
_FC_IMSI_FROM   = "001010000011001"
_FC_IMSI_TO     = "001010000013600"

# Warmup concurrency — gentle on subscriber-profile-api during initial provisioning
_WARMUP_WORKERS = 50

# ── IMSI / APN pools ──────────────────────────────────────────────────────────

APNS = ["internet", "mms", "ims"]

# Fast-path: 001010000001001 – 001010000011000  (10 K known subscribers)
# Base = 1010000001000 so that i=1 → 001010000001001 (_FP_IMSI_FROM)
#                              and i=10000 → 001010000011000 (_FP_IMSI_TO)
_FAST_PATH_IMSIS = [
    str(1010000001000 + i).zfill(15) for i in range(1, IMSI_COUNT + 1)
]

# ── Load tier definitions ─────────────────────────────────────────────────────

@dataclass
class LoadTier:
    rps:        int
    duration_s: int
    label:      str


def _build_tiers() -> list[LoadTier]:
    d = TIER_DURATION_S
    return [
        LoadTier(rps=100, duration_s=d, label="tier-100"),
        LoadTier(rps=200, duration_s=d, label="tier-200"),
        LoadTier(rps=300, duration_s=d, label="tier-300"),
    ]


# ── Per-tier statistics ───────────────────────────────────────────────────────

@dataclass
class TierStats:
    label:      str
    sender:     str   # "fast_path" | "first_connect"
    target_rps: int
    actual_rps: float = 0.0
    sent:       int   = 0
    accepted:   int   = 0
    rejected:   int   = 0
    errors:     int   = 0
    p50_ms:     float = 0.0
    p95_ms:     float = 0.0
    p99_ms:     float = 0.0
    start_ts:   float = 0.0
    end_ts:     float = 0.0
    # Raw latency samples — excluded from JSON output
    _latencies: list = field(default_factory=list, repr=False)

    def finalise(self) -> None:
        """Compute percentiles and actual RPS from collected samples."""
        dur = max(self.end_ts - self.start_ts, 0.001)
        self.actual_rps = round(self.sent / dur, 2)
        if self._latencies:
            s = sorted(self._latencies)
            self.p50_ms = round(_pct(s, 50), 2)
            self.p95_ms = round(_pct(s, 95), 2)
            self.p99_ms = round(_pct(s, 99), 2)


def _pct(sorted_data: list[float], pct: float) -> float:
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_data) - 1)
    return sorted_data[lo] + (sorted_data[hi] - sorted_data[lo]) * (k - lo)


def _to_dict(s: TierStats) -> dict:
    d = asdict(s)
    d.pop("_latencies", None)
    return d


# ── Token bucket rate limiter ─────────────────────────────────────────────────

class _TokenBucket:
    """Thread-safe token bucket — call acquire() before each dispatch."""

    def __init__(self, rate_rps: int) -> None:
        self._rate   = float(rate_rps)
        self._tokens = float(rate_rps)
        self._last   = time.monotonic()
        self._lock   = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._tokens + (now - self._last) * self._rate,
                    self._rate,
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)


# ── Thread-local RADIUS client ────────────────────────────────────────────────

_tls = threading.local()


def _client() -> RadiusClient:
    """Return (or create) a per-thread RadiusClient."""
    if not hasattr(_tls, "rc"):
        _tls.rc = RadiusClient(RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET, timeout=5.0)
    return _tls.rc


# ── Core request function (runs in worker threads) ────────────────────────────

def _send(imsi: str, apn: str, stats: TierStats, lock: threading.Lock) -> None:
    t0 = time.monotonic()
    try:
        resp = _client().authenticate(imsi, apn)
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        with lock:
            stats.sent     += 1
            stats._latencies.append(elapsed_ms)
            if resp.code == CODE_ACCESS_ACCEPT:
                stats.accepted += 1
            elif resp.code == CODE_ACCESS_REJECT:
                stats.rejected += 1
            else:
                stats.errors += 1
    except Exception:
        with lock:
            stats.sent   += 1
            stats.errors += 1


# ── Fast-path tier runner ─────────────────────────────────────────────────────

def run_tier(tier: LoadTier) -> TierStats:
    stats    = TierStats(label=tier.label, sender="fast_path", target_rps=tier.rps)
    lock     = threading.Lock()
    bucket   = _TokenBucket(tier.rps)
    # Workers = rps * expected_p99_s with a safety factor.
    # Assume p99 ≤ 200ms under load → workers = rps * 0.2, min 20.
    workers  = max(tier.rps // 5, 20)
    deadline = time.monotonic() + tier.duration_s

    print(
        f"\n[{tier.label}] fast-path {tier.rps} RPS × {tier.duration_s}s "
        f"({workers} workers)"
    )

    stats.start_ts = time.time()
    futures = []

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fp") as pool:
        while time.monotonic() < deadline:
            bucket.acquire()
            imsi = random.choice(_FAST_PATH_IMSIS)
            apn  = random.choice(APNS)
            futures.append(pool.submit(_send, imsi, apn, stats, lock))

        for f in futures:
            try:
                f.result(timeout=6.0)
            except Exception:
                pass

    stats.end_ts = time.time()
    stats.finalise()
    _print_stats(stats)
    return stats


# ── First-connect background sender ──────────────────────────────────────────

class _AtomicCounter:
    def __init__(self, start: int = 0) -> None:
        self._val  = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            v = self._val
            self._val += 1
            return v


def run_firstconn_background(
    stop: threading.Event,
    result_holder: list,
    fc_lock: threading.Lock,
) -> None:
    """Daemon thread — sends FIRSTCONN_RPS first-connect requests throughout all tiers."""
    counter = _AtomicCounter(start=0)
    stats   = TierStats(label="all-tiers", sender="first_connect", target_rps=FIRSTCONN_RPS)
    lock    = threading.Lock()
    bucket  = _TokenBucket(FIRSTCONN_RPS)

    stats.start_ts = time.time()

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="fc") as pool:
        while not stop.is_set():
            bucket.acquire()
            idx  = counter.next()
            imsi = str(_FIRSTCONN_BASE + idx).zfill(15)
            apn  = "internet"   # first-connect always uses internet APN
            pool.submit(_send, imsi, apn, stats, lock)

    stats.end_ts = time.time()
    stats.finalise()
    _print_stats(stats)

    with fc_lock:
        result_holder.append(stats)


# ── Setup: create first-connect pool + range config via subscriber-profile-api ─

def _api_headers() -> dict:
    return {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}


def _api_post(url: str, **kwargs) -> "_requests.Response":
    """POST with retry on transient timeouts (deployment rolling / cold start)."""
    timeout = kwargs.pop("timeout", 30)
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            return _requests.post(url, timeout=timeout, **kwargs)
        except (_requests.exceptions.Timeout, _requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            wait = attempt * 5
            print(
                f"  [setup] POST {url} attempt {attempt} failed ({exc.__class__.__name__}), "
                f"retrying in {wait}s …"
            )
            time.sleep(wait)
    raise RuntimeError(f"POST {url} failed after 3 attempts: {last_exc}") from last_exc


def _get_or_create_pool(name: str, subnet: str, account: str) -> str:
    """Ensure a named pool exists. Returns pool_id (UUID string).

    All subscriber-profile-api routes are under the /v1 prefix.
    On 409 pool_overlap the response body contains `conflicting_pool_id` —
    we GET that pool directly to verify it's the one we want.
    """
    headers = _api_headers()

    r = _api_post(
        f"{API_URL}/v1/pools",
        json={"name": name, "account_name": account, "routing_domain": "default", "subnet": subnet},
        headers=headers,
        timeout=30,
    )
    if r.status_code == 201:
        pool_id = r.json()["pool_id"]
        print(f"  [setup] Created pool '{name}' ({subnet}) → {pool_id}")
        return pool_id

    if r.status_code == 409:
        body = r.json()
        # API returns conflicting_pool_id directly in the 409 body
        conflict_id = body.get("conflicting_pool_id")
        if conflict_id:
            r2 = _requests.get(
                f"{API_URL}/v1/pools/{conflict_id}", headers=headers, timeout=15
            )
            r2.raise_for_status()
            existing = r2.json()
            existing_name = existing.get("name") or existing.get("pool_name", "")
            pool_id = existing["pool_id"]
            if existing_name == name or existing.get("subnet") == subnet:
                print(f"  [setup] Pool '{name}' already exists → {pool_id}")
                return pool_id
            raise RuntimeError(
                f"Subnet {subnet} overlaps with a different pool "
                f"'{existing_name}' ({pool_id}). Choose a non-overlapping subnet."
            )
        # Fallback: list by account and match by name
        r3 = _requests.get(
            f"{API_URL}/v1/pools", params={"account_name": account}, headers=headers, timeout=15
        )
        r3.raise_for_status()
        for p in r3.json().get("items", []):
            if (p.get("name") or p.get("pool_name", "")) == name or p.get("subnet") == subnet:
                pool_id = p["pool_id"]
                print(f"  [setup] Pool '{name}' already exists (list fallback) → {pool_id}")
                return pool_id
        raise RuntimeError(
            f"409 from POST /v1/pools but pool '{name}' not found: {r.text}"
        )

    r.raise_for_status()
    raise RuntimeError(f"POST /v1/pools returned {r.status_code}: {r.text}")


def _get_or_create_range_config(
    f_imsi: str, t_imsi: str, pool_id: str, account: str, ip_resolution: str
) -> int:
    """Ensure an IMSI range config exists. Returns config id."""
    headers = _api_headers()

    r = _requests.get(
        f"{API_URL}/v1/range-configs",
        params={"account_name": account, "pool_id": pool_id},
        headers=headers,
        timeout=15,
    )
    r.raise_for_status()
    # GET /v1/range-configs returns {"items": [...]}
    for cfg in r.json().get("items", []):
        if cfg.get("f_imsi") == f_imsi and cfg.get("t_imsi") == t_imsi:
            cfg_id = cfg["id"]
            print(f"  [setup] Range config {f_imsi}–{t_imsi} already exists → id={cfg_id}")
            return cfg_id

    r2 = _requests.post(
        f"{API_URL}/v1/range-configs",
        json={
            "account_name":  account,
            "f_imsi":        f_imsi,
            "t_imsi":        t_imsi,
            "pool_id":       pool_id,
            "ip_resolution": ip_resolution,
            "status":        "active",
        },
        headers=headers,
        timeout=15,
    )
    r2.raise_for_status()
    cfg_id = r2.json()["id"]
    print(f"  [setup] Created range config {f_imsi}–{t_imsi} → id={cfg_id}")
    return cfg_id


def _fast_path_provisioned() -> bool:
    """Return True if the full fast-path range is already provisioned.

    Checks the FIRST and LAST IMSI via subscriber-profile-api GET /v1/profiles.
    This is a pure read — no RADIUS request, no first-connect side-effect.
    Both must return a non-empty profile list to confirm the full range was warmed.
    """
    headers = _api_headers()
    for label, imsi in [("first", _FAST_PATH_IMSIS[0]), ("last", _FAST_PATH_IMSIS[-1])]:
        try:
            r = _requests.get(
                f"{API_URL}/v1/profiles",
                params={"imsi": imsi},
                headers=headers,
                timeout=10,
            )
            if r.status_code != 200:
                print(
                    f"  [setup] Warmup probe ({label} IMSI {imsi}): "
                    f"HTTP {r.status_code} → warmup needed."
                )
                return False
            body  = r.json()
            items = body if isinstance(body, list) else body.get("items", body.get("profiles", []))
            if not items:
                print(
                    f"  [setup] Warmup probe ({label} IMSI {imsi}): "
                    f"no profile found → warmup needed."
                )
                return False
            print(
                f"  [setup] Warmup probe ({label} IMSI {imsi}): "
                f"profile found (sim_id={items[0].get('sim_id','?')[:8]}…) ✓"
            )
        except Exception as exc:
            print(f"  [setup] Warmup probe ({label} IMSI {imsi}): error {exc} → warmup needed.")
            return False
    return True


def _warmup_fast_path() -> None:
    """Pre-provision all fast-path IMSI×APN combinations via RADIUS.

    Sends one Access-Request per (IMSI, APN) pair.
    - First run  : triggers first-connection (creates profile + allocates IP)
    - Re-runs    : skipped — checks API for existing profiles (no RADIUS side-effect)

    The old RADIUS probe was replaced because it triggered first-connect for
    IMSI #1, received Accept, and incorrectly skipped the remaining 9,999 IMSIs.
    """
    if _fast_path_provisioned():
        print(
            f"  [setup] Fast-path already provisioned "
            f"(first={_FAST_PATH_IMSIS[0]}, last={_FAST_PATH_IMSIS[-1]}) — skipping warmup."
        )
        return

    pairs = [(imsi, apn) for imsi in _FAST_PATH_IMSIS for apn in APNS]
    total = len(pairs)
    print(
        f"  [setup] Warming up {len(_FAST_PATH_IMSIS):,} IMSIs × {len(APNS)} APNs "
        f"= {total:,} requests  ({_WARMUP_WORKERS} workers) …"
    )

    done   = [0]
    errors = [0]
    lock   = threading.Lock()

    def _provision(imsi: str, apn: str) -> None:
        client = RadiusClient(RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET, timeout=10.0)
        try:
            client.authenticate(imsi, apn)
        except Exception:
            with lock:
                errors[0] += 1
            return
        with lock:
            done[0] += 1
            if done[0] % 1000 == 0:
                print(f"  [setup] Warmup progress: {done[0]}/{total} ({done[0]*100//total}%)")

    with ThreadPoolExecutor(max_workers=_WARMUP_WORKERS, thread_name_prefix="warmup") as pool:
        futs = [pool.submit(_provision, imsi, apn) for imsi, apn in pairs]
        for f in futs:
            try:
                f.result()
            except Exception:
                pass

    print(
        f"  [setup] Warmup complete — {done[0]}/{total} OK, "
        f"{errors[0]} errors ({errors[0]*100//total if total else 0}%)"
    )
    if errors[0] > total * 0.05:
        print(
            f"  [setup] WARNING: {errors[0]} warmup errors exceed 5% threshold. "
            f"Fast-path subscribers may be partially missing — load test results unreliable.",
            file=sys.stderr,
        )


def _wait_for_api(timeout_s: int = 120, interval_s: int = 5) -> None:
    """Block until subscriber-profile-api is fully ready (health + DB).

    Checks /health first (fast), then GET /v1/pools to confirm DB connectivity.
    A pod mid-restart passes /health but times out on DB-backed routes.
    """
    deadline = time.time() + timeout_s
    attempt  = 0
    print(f"  [setup] Waiting for API at {API_URL} (timeout {timeout_s}s) …")
    while time.time() < deadline:
        attempt += 1
        try:
            # Step 1: HTTP reachability
            r = _requests.get(f"{API_URL}/health", timeout=5)
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            # Step 2: DB connectivity (a cheap read — no rows needed)
            r2 = _requests.get(
                f"{API_URL}/v1/pools",
                params={"account_name": "__probe__"},
                headers=_api_headers(),
                timeout=10,
            )
            if r2.status_code in (200, 404):
                print(f"  [setup] API ready (attempt {attempt}).")
                return
            raise ValueError(f"DB probe returned HTTP {r2.status_code}")
        except Exception as exc:
            print(
                f"  [setup] API not ready (attempt {attempt}): {exc} "
                f"— retrying in {interval_s}s …"
            )
        time.sleep(interval_s)
    raise RuntimeError(
        f"subscriber-profile-api did not become ready within {timeout_s}s "
        f"after {attempt} attempts."
    )


def _check_prometheus() -> None:
    """Warn if Prometheus is unreachable or has no cadvisor data."""
    try:
        r = _requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": 'container_cpu_usage_seconds_total{namespace="aaa-platform",pod!=""}'},
            timeout=10,
        )
        r.raise_for_status()
        result = r.json().get("data", {}).get("result", [])
        if result:
            pods = sorted({s.get("metric", {}).get("pod", "?") for s in result})
            print(f"  [setup] Prometheus OK — {len(result)} cadvisor series, pods: {', '.join(pods)}")
        else:
            print(
                f"  [setup] WARNING: Prometheus reachable but no cadvisor data for "
                f"namespace=aaa-platform — pod metrics will be empty.",
                file=sys.stderr,
            )
    except Exception as exc:
        print(
            f"  [setup] WARNING: Prometheus unreachable ({exc}) — pod metrics will be skipped.",
            file=sys.stderr,
        )


def setup() -> None:
    """Wait for API, create pools + range configs, then warm up fast-path subscribers."""
    print("[setup] Preparing test data via subscriber-profile-api …")
    _wait_for_api()
    _check_prometheus()

    # Fast-path pool + range config (10K IMSIs × 3 APNs, imsi_apn resolution)
    fp_pool_id = _get_or_create_pool(_FP_POOL_NAME, _FP_POOL_SUBNET, _FP_ACCOUNT)
    _get_or_create_range_config(
        _FP_IMSI_FROM, _FP_IMSI_TO, fp_pool_id, _FP_ACCOUNT, "imsi_apn"
    )

    # First-connect pool + range config (sequential new IMSIs)
    fc_pool_id = _get_or_create_pool(_FC_POOL_NAME, _FC_POOL_SUBNET, _FC_ACCOUNT)
    _get_or_create_range_config(
        _FC_IMSI_FROM, _FC_IMSI_TO, fc_pool_id, _FC_ACCOUNT, "imsi_apn"
    )

    # Warm up all fast-path IMSI×APN combinations
    _warmup_fast_path()

    print("[setup] Done.\n")


# ── Prometheus metrics collection ─────────────────────────────────────────────

# Use pod!="" — works on both standard K8s cadvisor (multi-container label)
# and Docker Desktop cadvisor (emits only pod-level rows with cpu="total").
# Covers all aaa-platform pods incl. PostgreSQL + PgBouncer pooler.
_PROM_QUERIES = {
    "cpu_cores": (
        'sum by (pod) ('
        '  rate(container_cpu_usage_seconds_total'
        '    {namespace="aaa-platform",pod!=""}[1m])'
        ')'
    ),
    "mem_bytes": (
        'sum by (pod) ('
        '  container_memory_working_set_bytes'
        '    {namespace="aaa-platform",pod!=""}'
        ')'
    ),
}


def _prom_range(query: str, start: float, end: float, step: int = 15) -> list:
    try:
        r = _requests.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("result", [])
    except Exception as exc:
        print(f"  [prom] WARNING: {exc}", file=sys.stderr)
        return []


def collect_pod_metrics(start_ts: float, end_ts: float) -> dict:
    """Query Prometheus for CPU and RAM per pod over [start_ts, end_ts]."""
    result: dict = {}
    for metric, query in _PROM_QUERIES.items():
        for series in _prom_range(query, start_ts, end_ts):
            pod    = series.get("metric", {}).get("pod", "unknown")
            values = [
                float(v[1]) for v in series.get("values", [])
                if v[1] not in ("NaN", "+Inf", "-Inf")
            ]
            if not values:
                continue
            entry = result.setdefault(pod, {})
            if metric == "cpu_cores":
                entry["cpu_avg_cores"] = round(sum(values) / len(values), 4)
                entry["cpu_max_cores"] = round(max(values), 4)
            elif metric == "mem_bytes":
                entry["mem_avg_mb"] = round(sum(values) / len(values) / 1_048_576, 2)
                entry["mem_max_mb"] = round(max(values)             / 1_048_576, 2)
    return result


# ── Output helpers ────────────────────────────────────────────────────────────

def _print_stats(s: TierStats) -> None:
    err_rate = s.errors / max(s.sent, 1) * 100
    print(
        f"  [{s.label}/{s.sender}] "
        f"sent={s.sent} accept={s.accepted} reject={s.rejected} "
        f"err={s.errors} ({err_rate:.2f}%)  "
        f"actual={s.actual_rps:.1f} RPS  "
        f"p50={s.p50_ms:.1f}ms p95={s.p95_ms:.1f}ms p99={s.p99_ms:.1f}ms"
    )


def _write_outputs(fast_stats: list, fc_stats: list, pod_metrics: dict, out_dir: Path) -> None:
    all_stats = fast_stats + fc_stats

    # summary.json
    (out_dir / "summary.json").write_text(
        json.dumps([_to_dict(s) for s in all_stats], indent=2)
    )

    # pod-metrics.json
    (out_dir / "pod-metrics.json").write_text(json.dumps(pod_metrics, indent=2))

    # report.md
    lines = ["# RADIUS Load Test Report\n"]

    # Fast-path table
    lines += [
        "## Fast-Path Results\n",
        "| Tier | Target RPS | Actual RPS | Sent | Accepted | Rejected | Errors | p50 ms | p95 ms | p99 ms |",
        "|------|-----------|-----------|------|----------|----------|--------|--------|--------|--------|",
    ]
    for s in fast_stats:
        lines.append(
            f"| {s.label} | {s.target_rps} | {s.actual_rps:.1f} | {s.sent} "
            f"| {s.accepted} | {s.rejected} | {s.errors} "
            f"| {s.p50_ms:.1f} | {s.p95_ms:.1f} | {s.p99_ms:.1f} |"
        )

    # First-connect table
    lines += [
        "\n## First-Connect Results\n",
        "| Sender | Target RPS | Actual RPS | Sent | Accepted | Rejected | Errors | p50 ms | p95 ms | p99 ms |",
        "|--------|-----------|-----------|------|----------|----------|--------|--------|--------|--------|",
    ]
    for s in fc_stats:
        lines.append(
            f"| {s.label} | {s.target_rps} | {s.actual_rps:.1f} | {s.sent} "
            f"| {s.accepted} | {s.rejected} | {s.errors} "
            f"| {s.p50_ms:.1f} | {s.p95_ms:.1f} | {s.p99_ms:.1f} |"
        )

    # Pod metrics per tier
    lines.append("\n## Pod Resource Utilization by Tier\n")
    for tier_label, pods in pod_metrics.items():
        lines += [
            f"\n### {tier_label}\n",
            "| Pod | CPU avg (cores) | CPU max (cores) | RAM avg (MB) | RAM max (MB) |",
            "|-----|-----------------|-----------------|--------------|--------------|",
        ]
        for pod, m in sorted(pods.items()):
            lines.append(
                f"| `{pod}` "
                f"| {m.get('cpu_avg_cores', 'N/A')} "
                f"| {m.get('cpu_max_cores', 'N/A')} "
                f"| {m.get('mem_avg_mb', 'N/A')} "
                f"| {m.get('mem_max_mb', 'N/A')} |"
            )

    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(f"\nResults written to {out_dir}/")

    # ── Print full results to stdout so kubectl logs captures them permanently ──
    # (kubectl cp doesn't work on Failed/Completed pods; logs are always available)
    print("\n" + "─" * 72)
    print("RESULTS_JSON_BEGIN")
    print(json.dumps({
        "summary":     [_to_dict(s) for s in all_stats],
        "pod_metrics": pod_metrics,
    }, indent=2))
    print("RESULTS_JSON_END")
    print("─" * 72)


# ── Pass / fail evaluation ────────────────────────────────────────────────────

_FAST_P99_LIMIT_MS  = 20.0   # p99 < 20 ms
_FAST_ERR_LIMIT     = 0.01   # error rate < 1 %
_FC_P99_LIMIT_MS    = 500.0  # first-connect p99 < 500 ms
_FC_ERR_LIMIT       = 0.02   # error rate < 2 %


def _evaluate(fast_stats: list, fc_stats: list) -> bool:
    print("\n=== Pass / Fail ===")
    passed = True

    for s in fast_stats:
        err = s.errors / max(s.sent, 1)
        ok  = s.p99_ms < _FAST_P99_LIMIT_MS and err < _FAST_ERR_LIMIT
        tag = "PASS" if ok else "FAIL"
        if not ok:
            passed = False
        print(
            f"  {tag}  {s.label} [fast_path] "
            f"p99={s.p99_ms:.1f}ms (limit {_FAST_P99_LIMIT_MS}ms)  "
            f"err={err*100:.2f}% (limit {_FAST_ERR_LIMIT*100:.0f}%)"
        )

    for s in fc_stats:
        err = s.errors / max(s.sent, 1)
        ok  = s.p99_ms < _FC_P99_LIMIT_MS and err < _FC_ERR_LIMIT
        tag = "PASS" if ok else "FAIL"
        if not ok:
            passed = False
        print(
            f"  {tag}  {s.label} [first_connect] "
            f"p99={s.p99_ms:.1f}ms (limit {_FC_P99_LIMIT_MS}ms)  "
            f"err={err*100:.2f}% (limit {_FC_ERR_LIMIT*100:.0f}%)"
        )

    return passed


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)

    tiers      = _build_tiers()
    fast_stats: list[TierStats] = []
    fc_stats:   list[TierStats] = []
    pod_metrics: dict           = {}
    fc_lock     = threading.Lock()

    tier_labels = " → ".join(str(t.rps) for t in tiers)
    print(
        f"RADIUS load test — {len(tiers)} tiers × {TIER_DURATION_S}s each\n"
        f"Tiers:        {tier_labels} RPS\n"
        f"Target:       {RADIUS_HOST}:{RADIUS_PORT}\n"
        f"API:          {API_URL}\n"
        f"Fast-path:    {len(_FAST_PATH_IMSIS):,} IMSIs  ({_FP_IMSI_FROM} – {_FP_IMSI_TO})\n"
        f"First-connect {FIRSTCONN_RPS} RPS constant  (base IMSI {str(_FIRSTCONN_BASE).zfill(15)}+)\n"
        f"Prometheus:   {PROMETHEUS_URL}\n"
    )

    setup()

    # ── Start first-connect background sender ─────────────────────────────────
    stop_fc   = threading.Event()
    fc_thread = threading.Thread(
        target=run_firstconn_background,
        args=(stop_fc, fc_stats, fc_lock),
        name="firstconn-sender",
        daemon=True,
    )
    fc_thread.start()

    # ── Iterate through load tiers ────────────────────────────────────────────
    for tier in tiers:
        stats = run_tier(tier)
        fast_stats.append(stats)

        print(f"  [{tier.label}] Querying Prometheus for pod metrics …", end="", flush=True)
        pm = collect_pod_metrics(stats.start_ts, stats.end_ts)
        pod_metrics[tier.label] = pm
        print(f" {len(pm)} pods found")

    # ── Stop first-connect sender and collect its stats ───────────────────────
    stop_fc.set()
    fc_thread.join(timeout=12)

    # ── Write outputs and evaluate ────────────────────────────────────────────
    _write_outputs(fast_stats, fc_stats, pod_metrics, out_dir)
    passed = _evaluate(fast_stats, fc_stats)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
