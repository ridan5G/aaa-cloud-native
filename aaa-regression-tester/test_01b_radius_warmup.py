"""
test_01b_radius_warmup.py — Single RADIUS packet to seed metrics early.

Runs immediately after test_01_pools so that radius_requests_total and
radius_request_duration_ms timeseries appear in Prometheus from the very
start of the test run.  Without this, RADIUS metrics only appear in Grafana
when test_12 begins (~75 s after lookup-service metrics), making the two
graphs look misaligned even though both services started simultaneously.

No data fixtures are required: an out-of-band IMSI always triggers
Stage 1 (lookup → 404) → Stage 2 (first-connection → 404) → Access-Reject,
which is enough to increment all RADIUS counter/histogram label combinations.

Skipped automatically if aaa-radius-server is unreachable.
"""
import socket

import pytest

from conftest import RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET
from fixtures.radius import RadiusClient

# IMSI outside all range configs — guaranteed reject, no provisioning needed.
_WARMUP_IMSI = "278771209999999"
_WARMUP_APN  = "warmup.internal"


@pytest.mark.radius
def test_radius_warmup(radius_client: RadiusClient) -> None:
    """Send one RADIUS packet so RADIUS metrics are visible in Grafana from t=0."""
    try:
        radius_client.authenticate(_WARMUP_IMSI, _WARMUP_APN)
    except (socket.timeout, OSError):
        pytest.skip("aaa-radius-server not reachable — skipping RADIUS warmup")
    # Accept or Reject — both are valid; the goal is metric generation, not outcome.
