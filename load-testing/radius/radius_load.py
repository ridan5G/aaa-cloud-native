#!/usr/bin/env python3
"""
radius_load.py — RADIUS protocol load test.

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

PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090",
)

IMSI_COUNT       = int(os.environ.get("IMSI_COUNT",       "10000"))
FIRSTCONN_RPS    = int(os.environ.get("FIRSTCONN_RPS",    "2"))
TIER_DURATION_S  = int(os.environ.get("TIER_DURATION_S",  "300"))

# First-connect IMSI pool base — must match seed SQL (001010000011001+)
_FIRSTCONN_BASE = int(os.environ.get("FIRSTCONN_IMSI_START", "1010000011001"))

# ── IMSI / APN pools ──────────────────────────────────────────────────────────

APNS = ["internet", "mms", "ims"]

# Fast-path: 001010000001001 – 001010000011000  (10 K known subscribers)
_FAST_PATH_IMSIS = [
    str(1010000000000 + i).zfill(15) for i in range(1, IMSI_COUNT + 1)
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
        LoadTier(rps=300, duration_s=d, label="tier-300"),
        LoadTier(rps=400, duration_s=d, label="tier-400"),
        LoadTier(rps=500, duration_s=d, label="tier-500"),
        LoadTier(rps=600, duration_s=d, label="tier-600"),
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
    workers  = max(tier.rps // 40, 20)   # ~25ms headroom; enough for 600 RPS @ 10ms RTT
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


# ── Prometheus metrics collection ─────────────────────────────────────────────

_PROM_QUERIES = {
    "cpu_cores": (
        'avg by (pod) ('
        '  rate(container_cpu_usage_seconds_total'
        '    {namespace="aaa-platform",container!="POD",container!=""}[1m])'
        ')'
    ),
    "mem_bytes": (
        'avg by (pod) ('
        '  container_memory_working_set_bytes'
        '    {namespace="aaa-platform",container!="POD",container!=""}'
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

    print(
        f"RADIUS load test — {len(tiers)} tiers × {TIER_DURATION_S}s each\n"
        f"Target:       {RADIUS_HOST}:{RADIUS_PORT}\n"
        f"Fast-path:    {len(_FAST_PATH_IMSIS):,} IMSIs  (001010000001001 – 001010000011000)\n"
        f"First-connect {FIRSTCONN_RPS} RPS constant  (base IMSI {str(_FIRSTCONN_BASE).zfill(15)}+)\n"
        f"Prometheus:   {PROMETHEUS_URL}\n"
    )

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
