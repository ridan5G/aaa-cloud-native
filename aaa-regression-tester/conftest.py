"""
conftest.py — session-scoped HTTP clients and shared helpers.

All test modules import from here.  No shared mutable state is kept between
modules; each test module creates and tears down its own DB fixtures.
"""
import csv
import os
import time
from pathlib import Path
from typing import Generator

import httpx
import pytest

# ── Base URLs ─────────────────────────────────────────────────────────────────
PROVISION_BASE = os.getenv("PROVISION_URL", "http://localhost:8080/v1")
LOOKUP_BASE    = os.getenv("LOOKUP_URL",    "http://localhost:8081/v1")
JWT_TOKEN      = os.getenv("TEST_JWT",      "dev-skip-verify")

# ── RADIUS server (test_12) ───────────────────────────────────────────────────
RADIUS_HOST   = os.getenv("RADIUS_HOST",   "localhost")
RADIUS_PORT   = int(os.getenv("RADIUS_PORT",   "1812"))
RADIUS_SECRET = os.getenv("RADIUS_SECRET", "testing123")

# ── Common test data ──────────────────────────────────────────────────────────
ACCOUNT_NAME   = "TestAccount"
SUBNET_24      = "100.65.120.0/24"
USABLE_IPS_24  = 253     # /24 minus network (.0) and broadcast (.255) minus .254? → plan says 253

# IMSI ranges — unique prefixes avoid collisions between test modules
# Format: 27877<MM><NNNNNNNN>  MM=module (2 digits), NNNNNNNN=seq (8 digits) = 15 digits total
def make_imsi(module: int, seq: int) -> str:
    return f"27877{module:02d}{seq:08d}"

def make_iccid(module: int, seq: int) -> str:
    """Return a 19-digit ICCID."""
    return f"8944501{module:02d}{seq:010d}"

def make_ip(third: int, fourth: int) -> str:
    return f"100.65.{third}.{fourth}"


# ── HTTP client fixtures ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def http() -> Generator[httpx.Client, None, None]:
    """Authenticated client for the subscriber-profile-api."""
    with httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=30.0,
    ) as client:
        yield client


@pytest.fixture(scope="session")
def lookup_http() -> Generator[httpx.Client, None, None]:
    """Authenticated client for the aaa-lookup-service."""
    with httpx.Client(
        base_url=LOOKUP_BASE,
        headers={"Authorization": f"Bearer {JWT_TOKEN}"},
        timeout=10.0,
    ) as client:
        yield client


@pytest.fixture(scope="session")
def radius_client():
    """RADIUS client pointed at aaa-radius-server (UDP)."""
    from fixtures.radius import RadiusClient
    return RadiusClient(RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET)


@pytest.fixture(scope="session")
def unauthed_http() -> Generator[httpx.Client, None, None]:
    """Unauthenticated client — used by test_10 to verify 401 responses."""
    with httpx.Client(
        base_url=PROVISION_BASE,
        headers={"Authorization": "Bearer invalid-token"},
        timeout=10.0,
    ) as client:
        yield client


# ── Timing helpers ────────────────────────────────────────────────────────────

class TimingRecorder:
    """Collects (test_name, latency_ms) pairs and writes timing.csv on close."""

    def __init__(self, path: str = "results/timing.csv"):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._rows: list[dict] = []

    def record(self, test: str, latency_ms: float) -> None:
        self._rows.append({"test": test, "latency_ms": f"{latency_ms:.3f}"})

    def flush(self) -> None:
        if not self._rows:
            return
        with open(self._path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["test", "latency_ms"])
            w.writeheader()
            w.writerows(self._rows)


@pytest.fixture(scope="session")
def timing() -> Generator[TimingRecorder, None, None]:
    rec = TimingRecorder()
    yield rec
    rec.flush()


# ── Poll helper ───────────────────────────────────────────────────────────────

def poll_until(
    fn,
    condition,
    timeout: float = 600.0,
    interval: float = 5.0,
    label: str = "condition",
):
    """Repeatedly call fn() until condition(result) is True or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if condition(result):
            return result
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {label}")


# ── p-value helpers ───────────────────────────────────────────────────────────

def percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile (0–100) of a list of floats."""
    if not values:
        raise ValueError("Empty values list")
    sorted_vals = sorted(values)
    index = (p / 100) * (len(sorted_vals) - 1)
    lo, hi = int(index), min(int(index) + 1, len(sorted_vals) - 1)
    frac = index - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac
