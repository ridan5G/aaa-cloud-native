"""
test_12_radius.py — End-to-end RADIUS authentication server tests.

Sends real UDP RADIUS Access-Request packets to aaa-radius-server and
verifies the two-stage AAA flow:

  Stage 1: server calls GET /lookup?imsi=&apn= on aaa-lookup-service
    200 → Access-Accept + Framed-IP-Address
    403 → Access-Reject  (subscriber suspended)
    404 → Stage 2 ↓

  Stage 2: server calls POST /v1/first-connection {imsi, apn, imei}
    200 → Access-Accept + Framed-IP-Address
    404/503 → Access-Reject

Requires RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET env vars
(defaults: localhost, 1812; RADIUS_SECRET from env or .env file).

Test cases 12.1 – 12.10
"""
import socket
import time
import threading

import httpx
import pytest

from conftest import ACCOUNT_NAME, PROVISION_BASE, JWT_TOKEN, RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET
from fixtures.pools import create_pool, delete_pool, get_pool_stats
from fixtures.profiles import create_profile_imsi, delete_profile
from fixtures.radius import RadiusClient, CODE_ACCESS_ACCEPT, CODE_ACCESS_REJECT

# ── IMSI ranges — module 12, no overlap with any other test module ────────────

# Range A: pre-provisioned profiles (tests 12.2 – 12.5)
KNOWN_POOL_SUBNET = "100.65.120.200/29"   # 6 usable IPs (.201–.206)
IMSI_KNOWN        = "278771200000001"      # pre-provisioned via HTTP API
KNOWN_STATIC_IP   = "100.65.120.201"      # the IP recorded in the profile

# Range B: first-connection via RADIUS (tests 12.6 – 12.7)
FC_POOL_SUBNET    = "100.65.120.208/29"   # 6 usable IPs (.209–.214)
IMSI_FC_F         = "278771200001001"
IMSI_FC_T         = "278771200001099"
IMSI_FC_NEW       = "278771200001001"     # no profile exists before test 12.6

# Out-of-range IMSI — not covered by any range config (tests 12.8)
IMSI_OOB          = "278771209999001"

# APN used for all requests
TEST_APN = "internet.operator.com"


# ── Helper to detect if the RADIUS server is reachable ───────────────────────

def _radius_available(host: str, port: int, secret: str) -> bool:
    """Return True if aaa-radius-server responds within 3 seconds."""
    rc = RadiusClient(host, port, secret, timeout=3.0)
    try:
        # IMSI_OOB is outside all range configs → server will answer Reject
        rc.authenticate(IMSI_OOB, "health-check")
        return True
    except (socket.timeout, OSError):
        return False


# ── Test class ────────────────────────────────────────────────────────────────

@pytest.mark.radius
class TestRadiusServer:
    # Set by setup_class; read by all test methods
    known_pool_id:   str | None = None
    known_device_id: str | None = None
    fc_pool_id:      str | None = None
    fc_range_id:     str | None = None
    fc_device_id:    str | None = None   # filled by test_06
    fc_allocated_ip: str | None = None   # filled by test_06

    @classmethod
    def _cleanup_previous_run(cls, c: httpx.Client) -> None:
        """Remove any artifacts left by a previous interrupted test run.

        Deletion order: profiles → range_configs → pools (FK safe).
        All errors are swallowed so a dirty DB never blocks setup.
        """
        # 1. Delete leftover profiles for our IMSIs
        for imsi in (IMSI_KNOWN, IMSI_FC_NEW):
            try:
                r = c.get("/profiles", params={"imsi": imsi})
                if r.status_code == 200:
                    data = r.json()
                    items = data if isinstance(data, list) else data.get("profiles", data.get("items", []))
                    for p in items:
                        c.delete(f"/profiles/{p['device_id']}")
            except Exception:
                pass

        # 2. Delete leftover range_configs covering our IMSI range
        try:
            r = c.get("/range-configs")
            if r.status_code == 200:
                for item in r.json().get("items", []):
                    if item.get("f_imsi") == IMSI_FC_F and item.get("t_imsi") == IMSI_FC_T:
                        c.delete(f"/range-configs/{item['id']}")
        except Exception:
            pass

        # 3. Delete leftover pools with our fixed names
        _OUR_POOLS = {"pool-radius-known-12", "pool-radius-fc-12"}
        try:
            r = c.get("/pools")
            if r.status_code == 200:
                for pool in r.json().get("items", []):
                    if pool.get("pool_name") in _OUR_POOLS:
                        c.delete(f"/pools/{pool['pool_id']}")
        except Exception:
            pass

    @classmethod
    def setup_class(cls):
        """Create fixtures via the provisioning HTTP API before RADIUS tests run."""
        if not _radius_available(RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET):
            pytest.skip(
                f"aaa-radius-server not reachable at {RADIUS_HOST}:{RADIUS_PORT} — "
                "skipping test_12 (set RADIUS_HOST to enable)"
            )

        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            cls._cleanup_previous_run(c)
            # ── Pool A + pre-provisioned profile (for tests 12.2–12.5) ────────
            pool_a = create_pool(
                c,
                subnet=KNOWN_POOL_SUBNET,
                pool_name="pool-radius-known-12",
                account_name=ACCOUNT_NAME,
            )
            cls.known_pool_id = pool_a["pool_id"]

            profile = create_profile_imsi(
                c,
                iccid=None,
                account_name=ACCOUNT_NAME,
                imsis=[{
                    "imsi":      IMSI_KNOWN,
                    "static_ip": KNOWN_STATIC_IP,
                    "pool_id":   cls.known_pool_id,
                }],
                pool_name="pool-radius-known-12",
            )
            cls.known_device_id = profile["device_id"]

            # ── Pool B + range config (for tests 12.6–12.7) ──────────────────
            from fixtures.range_configs import create_range_config
            pool_b = create_pool(
                c,
                subnet=FC_POOL_SUBNET,
                pool_name="pool-radius-fc-12",
                account_name=ACCOUNT_NAME,
            )
            cls.fc_pool_id = pool_b["pool_id"]

            rc = create_range_config(
                c,
                f_imsi=IMSI_FC_F,
                t_imsi=IMSI_FC_T,
                pool_id=cls.fc_pool_id,
                ip_resolution="imsi",
                account_name=ACCOUNT_NAME,
            )
            cls.fc_range_id = rc["id"]

    @classmethod
    def teardown_class(cls):
        with httpx.Client(
            base_url=PROVISION_BASE,
            headers={"Authorization": f"Bearer {JWT_TOKEN}"},
            timeout=30.0,
        ) as c:
            # Remove profiles created during tests
            for did in filter(None, [cls.known_device_id, cls.fc_device_id]):
                try:
                    c.delete(f"/profiles/{did}")
                except Exception:
                    pass

            # Remove range config and pools
            from fixtures.range_configs import delete_range_config
            if cls.fc_range_id:
                delete_range_config(c, cls.fc_range_id)
            if cls.known_pool_id:
                delete_pool(c, cls.known_pool_id)
            if cls.fc_pool_id:
                delete_pool(c, cls.fc_pool_id)

    @pytest.fixture(autouse=True)
    def rc(self) -> RadiusClient:
        """Per-test RADIUS client."""
        return RadiusClient(
            host=RADIUS_HOST,
            port=RADIUS_PORT,
            secret=RADIUS_SECRET,
        )

    # 12.1 ────────────────────────────────────────────────────────────────────
    def test_01_fixtures_verified(self, http: httpx.Client, lookup_http: httpx.Client):
        """Pre-conditions: profile exists and lookup resolves before any RADIUS test."""
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI_KNOWN, "apn": TEST_APN})
        assert r.status_code == 200, \
            f"Pre-condition failed: lookup returned {r.status_code} {r.text}"
        assert r.json()["static_ip"] == KNOWN_STATIC_IP, \
            f"Pre-condition failed: lookup returned wrong IP {r.json()}"

    # 12.2 ────────────────────────────────────────────────────────────────────
    def test_02_known_imsi_returns_access_accept(self, rc: RadiusClient):
        """
        Stage 1: aaa-radius-server calls GET /lookup → 200.
        Expected RADIUS response: Access-Accept (code=2).
        """
        resp = rc.authenticate(IMSI_KNOWN, TEST_APN)
        assert resp.is_accept, \
            f"Expected Access-Accept (code=2), got code={resp.code}"

    # 12.3 ────────────────────────────────────────────────────────────────────
    def test_03_framed_ip_matches_provisioned_static_ip(self, rc: RadiusClient):
        """
        Framed-IP-Address in the Accept must equal the profile's static_ip.
        This verifies the server correctly reads static_ip from the /lookup JSON.
        """
        resp = rc.authenticate(IMSI_KNOWN, TEST_APN)
        assert resp.is_accept
        assert resp.framed_ip == KNOWN_STATIC_IP, \
            f"Framed-IP-Address={resp.framed_ip!r}, expected {KNOWN_STATIC_IP!r}"

    # 12.4 ────────────────────────────────────────────────────────────────────
    def test_04_suspended_subscriber_returns_access_reject(
            self, http: httpx.Client, rc: RadiusClient):
        """
        PATCH subscriber status=suspended → GET /lookup returns 403.
        Expected RADIUS response: Access-Reject (code=3).
        """
        # Suspend
        r = http.patch(f"/profiles/{TestRadiusServer.known_device_id}",
                       json={"status": "suspended"})
        assert r.status_code == 200, f"PATCH suspend failed: {r.status_code} {r.text}"

        resp = rc.authenticate(IMSI_KNOWN, TEST_APN)
        assert resp.is_reject, \
            f"Expected Access-Reject for suspended subscriber, got code={resp.code}"

        # Verify lookup also reflects suspension
        r2 = http.get(f"/profiles/{TestRadiusServer.known_device_id}")
        assert r2.json().get("status") == "suspended"

    # 12.5 ────────────────────────────────────────────────────────────────────
    def test_05_reactivated_subscriber_returns_access_accept(
            self, http: httpx.Client, rc: RadiusClient):
        """
        PATCH subscriber status=active → GET /lookup returns 200 again.
        Expected RADIUS response: Access-Accept with the original Framed-IP.
        """
        r = http.patch(f"/profiles/{TestRadiusServer.known_device_id}",
                       json={"status": "active"})
        assert r.status_code == 200, f"PATCH reactivate failed: {r.status_code} {r.text}"

        resp = rc.authenticate(IMSI_KNOWN, TEST_APN)
        assert resp.is_accept, \
            f"Expected Access-Accept after reactivation, got code={resp.code}"
        assert resp.framed_ip == KNOWN_STATIC_IP, \
            f"Framed-IP changed after reactivation: {resp.framed_ip}"

    # 12.6 ────────────────────────────────────────────────────────────────────
    def test_06_first_connection_via_radius_returns_accept(
            self, lookup_http: httpx.Client, http: httpx.Client, rc: RadiusClient):
        """
        Stage 1: GET /lookup for IMSI_FC_NEW → 404 (no profile yet).
        Stage 2: aaa-radius-server calls POST /v1/first-connection → allocates IP.
        Expected RADIUS response: Access-Accept with the allocated Framed-IP.

        After the test the profile is stored in cls.fc_device_id for teardown
        and subsequent idempotency check (test_07).
        """
        # Confirm no profile exists before the test
        r_pre = lookup_http.get("/lookup",
                                params={"imsi": IMSI_FC_NEW, "apn": TEST_APN})
        assert r_pre.status_code == 404, \
            f"Pre-condition failed: IMSI_FC_NEW already has a profile ({r_pre.status_code})"

        resp = rc.authenticate(IMSI_FC_NEW, TEST_APN, imei="35812300000000")
        assert resp.is_accept, (
            f"Expected Access-Accept via first-connection, got code={resp.code}. "
            "Check that aaa-radius-server's PROVISIONING_URL points to subscriber-profile-api."
        )
        assert resp.framed_ip is not None, \
            "Access-Accept must contain Framed-IP-Address after first-connection"

        # Store for teardown and test_07
        TestRadiusServer.fc_allocated_ip = resp.framed_ip

        # Fetch the auto-created device_id for teardown
        r_profile = http.get("/profiles", params={"imsi": IMSI_FC_NEW})
        if r_profile.status_code == 200:
            data = r_profile.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            if profiles:
                TestRadiusServer.fc_device_id = profiles[0]["device_id"]

        # Stage 1 should now resolve the newly allocated IP
        r_post = lookup_http.get("/lookup",
                                 params={"imsi": IMSI_FC_NEW, "apn": TEST_APN})
        assert r_post.status_code == 200, \
            f"Lookup should succeed after first-connection, got {r_post.status_code}"
        assert r_post.json()["static_ip"] == resp.framed_ip, \
            "Framed-IP in Accept does not match the static_ip returned by lookup"

    # 12.7 ────────────────────────────────────────────────────────────────────
    def test_07_first_connection_idempotent_same_ip(self, rc: RadiusClient):
        """
        Second Access-Request for the same IMSI (profile now exists).
        Stage 1 returns 200 directly → Access-Accept with the SAME IP as test_06.
        """
        assert TestRadiusServer.fc_allocated_ip is not None, \
            "test_06 must run first to populate fc_allocated_ip"

        resp = rc.authenticate(IMSI_FC_NEW, TEST_APN)
        assert resp.is_accept, \
            f"Expected Access-Accept for already-provisioned IMSI, got code={resp.code}"
        assert resp.framed_ip == TestRadiusServer.fc_allocated_ip, (
            f"IP changed on second request: "
            f"first={TestRadiusServer.fc_allocated_ip!r}, second={resp.framed_ip!r}"
        )

    # 12.8 ────────────────────────────────────────────────────────────────────
    def test_08_imsi_outside_all_ranges_returns_access_reject(self, rc: RadiusClient):
        """
        IMSI not covered by any range config.
        Stage 1 → 404 (no profile), Stage 2 → 404 (no range config).
        Expected RADIUS response: Access-Reject (code=3).
        """
        resp = rc.authenticate(IMSI_OOB, TEST_APN)
        assert resp.is_reject, \
            f"Expected Access-Reject for out-of-range IMSI, got code={resp.code}"

    # 12.9 ────────────────────────────────────────────────────────────────────
    def test_09_response_authenticator_is_valid(self, rc: RadiusClient):
        """
        RFC 2865 §3: ResponseAuth = MD5(Code|ID|Length|RequestAuth|Attrs|Secret).
        The RadiusClient.authenticate() already verifies this and raises ValueError
        on mismatch; reaching this assertion means the check passed.
        """
        from fixtures.radius import verify_response_auth, build_access_request
        import struct

        pkt_id = 77
        packet, request_auth = build_access_request(pkt_id, IMSI_KNOWN, TEST_APN)

        with __import__("socket").socket(
            __import__("socket").AF_INET, __import__("socket").SOCK_DGRAM
        ) as sock:
            sock.settimeout(rc.timeout)
            sock.sendto(packet, (rc.host, rc.port))
            raw, _ = sock.recvfrom(4096)

        secret = rc.secret
        assert verify_response_auth(raw, request_auth, secret), \
            "Response authenticator did not verify — wrong secret or server bug"

    # 12.10 ───────────────────────────────────────────────────────────────────
    def test_10_access_reject_has_no_framed_ip(self, rc: RadiusClient):
        """
        Access-Reject for an out-of-range IMSI must NOT contain Framed-IP-Address
        (attr 8).  Sending an IP in a Reject violates RFC 2865 and could mislead
        the NAS into routing traffic incorrectly.
        """
        resp = rc.authenticate(IMSI_OOB, TEST_APN)
        assert resp.is_reject, \
            f"Expected Access-Reject for IMSI_OOB, got code={resp.code}"
        assert resp.framed_ip is None, \
            f"Access-Reject must not carry Framed-IP-Address, got {resp.framed_ip!r}"
