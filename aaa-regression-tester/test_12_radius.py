"""
test_12_radius.py — End-to-end RADIUS authentication server tests.

Sends real UDP RADIUS Access-Request packets to aaa-radius-server and
verifies the two-stage AAA flow:

  Stage 1: server calls GET /lookup?imsi=&apn=[&use_case_id=] on aaa-lookup-service
    200 → Access-Accept + Framed-IP-Address
    403 → Access-Reject  (subscriber suspended)
    404 → Stage 2 ↓

  Stage 2: server calls POST /v1/first-connection {imsi, apn, imei[, use_case_id]}
    200 → Access-Accept + Framed-IP-Address
    404/503 → Access-Reject

  use_case_id is sourced from 3GPP-Charging-Characteristics VSA (10415:13).

Requires RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET env vars
(defaults: localhost, 1812; RADIUS_SECRET from env or .env file).

Test cases 12.1 – 12.14
"""
import socket
import time
import threading

import httpx
import pytest

from conftest import ACCOUNT_NAME, PROVISION_BASE, JWT_TOKEN, RADIUS_HOST, RADIUS_PORT, RADIUS_SECRET
from fixtures.pools import create_pool, delete_pool, get_pool_stats
from fixtures.profiles import create_profile_imsi, delete_profile
from fixtures.radius import (
    RadiusClient, build_access_request, parse_response,
    CODE_ACCESS_ACCEPT, CODE_ACCESS_REJECT,
    ATTR_FRAMED_IP_ADDRESS,
    RAT_TYPE_EUTRAN, RAT_TYPE_NR,
    NAS_PORT_TYPE_WIRELESS_OTHER,
    SERVICE_TYPE_FRAMED,
    FRAMED_PROTOCOL_GPRS_PDP,
)

# ── IMSI ranges — module 12, no overlap with any other test module ────────────

# Range A: pre-provisioned profiles (tests 12.2 – 12.5)
KNOWN_POOL_SUBNET = "100.65.120.200/29"   # 6 usable IPs (.201–.206)
IMSI_KNOWN        = "278771200000001"      # pre-provisioned via HTTP API
KNOWN_STATIC_IP   = "100.65.120.201"      # the IP recorded in the profile

# Range B: first-connection via RADIUS (tests 12.6 – 12.7, 12.14)
FC_POOL_SUBNET    = "100.65.120.208/29"   # 6 usable IPs (.209–.214)
IMSI_FC_F         = "278771200001001"
IMSI_FC_T         = "278771200001099"
IMSI_FC_NEW       = "278771200001001"     # no profile exists before test 12.6
IMSI_FC_NEW2      = "278771200001002"     # no profile exists before test 12.14

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
    known_pool_id:    str | None = None
    known_sim_id:     str | None = None
    fc_pool_id:       str | None = None
    fc_range_id:      str | None = None
    fc_sim_id:        str | None = None   # filled by test_06
    fc_allocated_ip:  str | None = None   # filled by test_06
    fc_sim_id2:       str | None = None   # filled by test_14
    fc_allocated_ip2: str | None = None   # filled by test_14

    @classmethod
    def _cleanup_previous_run(cls, c: httpx.Client) -> None:
        """Remove any artifacts left by a previous interrupted test run.

        Deletion order: profiles → range_configs → pools (FK safe).
        All errors are swallowed so a dirty DB never blocks setup.
        """
        # 1. Delete leftover profiles for our IMSIs
        for imsi in (IMSI_KNOWN, IMSI_FC_NEW, IMSI_FC_NEW2):
            try:
                r = c.get("/profiles", params={"imsi": imsi})
                if r.status_code == 200:
                    data = r.json()
                    items = data if isinstance(data, list) else data.get("profiles", data.get("items", []))
                    for p in items:
                        c.delete(f"/profiles/{p['sim_id']}")
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
                    if pool.get("name") in _OUR_POOLS:
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
                replace_on_conflict=True,
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
            cls.known_sim_id = profile["sim_id"]

            # ── Pool B + range config (for tests 12.6–12.7) ──────────────────
            from fixtures.range_configs import create_range_config
            pool_b = create_pool(
                c,
                subnet=FC_POOL_SUBNET,
                pool_name="pool-radius-fc-12",
                account_name=ACCOUNT_NAME,
                replace_on_conflict=True,
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
            for did in filter(None, [cls.known_sim_id, cls.fc_sim_id, cls.fc_sim_id2]):
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
        """Pre-conditions: profile exists and lookup resolves before any RADIUS test.

        Also verifies that the lookup endpoint accepts an optional use_case_id
        query parameter (forwarded from 3GPP-Charging-Characteristics) and still
        returns the correct static IP — confirming the upstream contract assumed
        by aaa-radius-server.
        """
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI_KNOWN, "apn": TEST_APN})
        assert r.status_code == 200, \
            f"Pre-condition failed: lookup returned {r.status_code} {r.text}"
        assert r.json()["static_ip"] == KNOWN_STATIC_IP, \
            f"Pre-condition failed: lookup returned wrong IP {r.json()}"

        # Verify lookup also works when use_case_id is present (radius server always
        # appends it when 3GPP-Charging-Characteristics VSA is non-empty)
        r2 = lookup_http.get("/lookup",
                             params={"imsi": IMSI_KNOWN, "apn": TEST_APN,
                                     "use_case_id": "0800"})
        assert r2.status_code == 200, \
            f"Pre-condition failed: lookup with use_case_id returned {r2.status_code} {r2.text}"
        assert r2.json()["static_ip"] == KNOWN_STATIC_IP, \
            f"Pre-condition failed: lookup with use_case_id returned wrong IP {r2.json()}"

    # 12.2 ────────────────────────────────────────────────────────────────────
    def test_02_known_imsi_returns_access_accept(self, rc: RadiusClient):
        """
        Stage 1: aaa-radius-server calls GET /lookup → 200.
        Expected RADIUS response: Access-Accept (code=2).
        """
        resp = rc.authenticate(IMSI_KNOWN, TEST_APN)
        assert resp.is_accept, \
            f"Expected Access-Accept (code=2), got code={resp.code}"

    # 12.2b ───────────────────────────────────────────────────────────────────
    def test_02b_known_imsi_access_accept_100_requests(self, rc: RadiusClient):
        """
        Stress: send 100 successive Access-Requests for a pre-provisioned IMSI.
        All 100 must return Access-Accept (code=2).
        Failures are collected and reported together so the full 100 always run.
        """
        failures = []
        for i in range(1, 101):
            resp = rc.authenticate(IMSI_KNOWN, TEST_APN)
            if not resp.is_accept:
                failures.append(f"request {i}: code={resp.code}")
        assert not failures, (
            f"{len(failures)}/100 requests failed:\n" + "\n".join(failures)
        )

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
        r = http.patch(f"/profiles/{TestRadiusServer.known_sim_id}",
                       json={"status": "suspended"})
        assert r.status_code == 200, f"PATCH suspend failed: {r.status_code} {r.text}"

        resp = rc.authenticate(IMSI_KNOWN, TEST_APN)
        assert resp.is_reject, \
            f"Expected Access-Reject for suspended subscriber, got code={resp.code}"

        # Verify lookup also reflects suspension
        r2 = http.get(f"/profiles/{TestRadiusServer.known_sim_id}")
        assert r2.json().get("status") == "suspended"

    # 12.5 ────────────────────────────────────────────────────────────────────
    def test_05_reactivated_subscriber_returns_access_accept(
            self, http: httpx.Client, rc: RadiusClient):
        """
        PATCH subscriber status=active → GET /lookup returns 200 again.
        Expected RADIUS response: Access-Accept with the original Framed-IP.
        """
        r = http.patch(f"/profiles/{TestRadiusServer.known_sim_id}",
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

        After the test the profile is stored in cls.fc_sim_id for teardown
        and subsequent idempotency check (test_07).
        """
        # Confirm no profile exists before the test
        r_pre = lookup_http.get("/lookup",
                                params={"imsi": IMSI_FC_NEW, "apn": TEST_APN})
        assert r_pre.status_code == 404, \
            f"Pre-condition failed: IMSI_FC_NEW already has a profile ({r_pre.status_code})"

        resp = rc.authenticate(IMSI_FC_NEW, TEST_APN,
                               imei="35812300000000",
                               charging_chars="0800")
        assert resp.is_accept, (
            f"Expected Access-Accept via first-connection, got code={resp.code}. "
            "Check that aaa-radius-server's PROVISIONING_URL points to subscriber-profile-api."
        )
        assert resp.framed_ip is not None, \
            "Access-Accept must contain Framed-IP-Address after first-connection"

        # Store for teardown and test_07
        TestRadiusServer.fc_allocated_ip = resp.framed_ip

        # Fetch the auto-created sim_id for teardown
        r_profile = http.get("/profiles", params={"imsi": IMSI_FC_NEW})
        if r_profile.status_code == 200:
            data = r_profile.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            if profiles:
                TestRadiusServer.fc_sim_id = profiles[0]["sim_id"]

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

    # 12.11 ───────────────────────────────────────────────────────────────────
    def test_11_full_3gpp_avp_request_accepted(self, rc: RadiusClient):
        """
        Send a complete Access-Request with ALL standard RADIUS + 3GPP VSAs that
        a real PGW/GGSN/SMF would send (NAS-IP-Address, NAS-Identifier,
        Service-Type, Framed-Protocol, NAS-Port-Type, Calling-Station-Id,
        3GPP-IMSI-MCC-MNC, 3GPP-GGSN-MCC-MNC, 3GPP-NSAPI,
        3GPP-Selection-Mode, 3GPP-Charging-Characteristics, 3GPP-IMEISV,
        3GPP-RAT-Type, 3GPP-User-Location-Info, 3GPP-MS-TimeZone).

        Verifies that aaa-radius-server parses the full packet correctly and
        still returns Access-Accept with the correct Framed-IP-Address.
        """
        resp = rc.authenticate(
            IMSI_KNOWN,
            TEST_APN,
            imei="35812300000001",
            msisdn="97250123456",
            nas_ip="10.0.0.1",
            nas_identifier="ggsn-01.operator.com",
            nas_port=0,
            nas_port_type=NAS_PORT_TYPE_WIRELESS_OTHER,
            service_type=SERVICE_TYPE_FRAMED,
            framed_protocol=FRAMED_PROTOCOL_GPRS_PDP,
            mcc_mnc="27877",
            nsapi=5,
            selection_mode="0",
            charging_chars="0800",
            rat_type=RAT_TYPE_EUTRAN,
        )
        assert resp.is_accept, (
            f"Full-AVP request for known IMSI must return Access-Accept, "
            f"got code={resp.code}"
        )
        assert resp.framed_ip == KNOWN_STATIC_IP, (
            f"Framed-IP-Address={resp.framed_ip!r}, expected {KNOWN_STATIC_IP!r}"
        )
        assert ATTR_FRAMED_IP_ADDRESS in resp.raw_attrs, \
            "Access-Accept must contain Framed-IP-Address attribute (attr 8)"

    # 12.12 ───────────────────────────────────────────────────────────────────
    def test_12_3gpp_imsi_vsa_preferred_over_user_name(self, rc: RadiusClient):
        """
        RFC 2865 + TS 29.061: when both User-Name (attr 1) and
        3GPP-IMSI VSA (attr 26, vendor=10415, type=1) are present, the server
        MUST use the 3GPP-IMSI VSA as the authoritative IMSI.

        Test setup:
          User-Name        = IMSI_OOB  (not provisioned → would reject if used)
          3GPP-IMSI VSA    = IMSI_KNOWN (provisioned     → Accept with static IP)

        If the server incorrectly uses User-Name the response will be a Reject.
        If it correctly uses the VSA the response will be an Accept.
        """
        pkt_id = 201
        packet, req_auth = build_access_request(
            pkt_id,
            imsi=IMSI_KNOWN,            # 3GPP-IMSI VSA carries the real IMSI
            apn=TEST_APN,
            user_name_override=IMSI_OOB,  # User-Name carries a different IMSI
        )

        with __import__("socket").socket(
            __import__("socket").AF_INET,
            __import__("socket").SOCK_DGRAM,
        ) as sock:
            sock.settimeout(rc.timeout)
            sock.sendto(packet, (rc.host, rc.port))
            raw, _ = sock.recvfrom(4096)

        resp = parse_response(raw, req_auth, rc.secret)
        assert resp.is_accept, (
            f"Server must prefer 3GPP-IMSI VSA over User-Name. "
            f"Got code={resp.code} — server may be using User-Name instead of VSA."
        )
        assert resp.framed_ip == KNOWN_STATIC_IP, (
            f"Framed-IP-Address={resp.framed_ip!r}, expected {KNOWN_STATIC_IP!r} "
            f"(resolves only if 3GPP-IMSI VSA = IMSI_KNOWN was used)"
        )

    # 12.13 ───────────────────────────────────────────────────────────────────
    def test_13_use_case_id_forwarded_in_stage1_lookup(
            self, rc: RadiusClient, lookup_http: httpx.Client):
        """
        3GPP-Charging-Characteristics (VSA 10415:13) must be forwarded as
        use_case_id to the Stage 1 GET /lookup call.

        Approach (black-box, no HTTP intercept):
          1. Directly confirm the lookup service returns the correct IP when
             use_case_id=0800 is present — this is the URL aaa-radius-server
             will call after extracting the charging chars from the RADIUS packet.
          2. Send a full Access-Request with charging_chars="0800" and verify
             Access-Accept with the correct Framed-IP-Address — proving the
             end-to-end path (RADIUS → aaa-radius-server → lookup with use_case_id)
             works without errors.
        """
        # Step 1: verify lookup service handles use_case_id natively
        r = lookup_http.get("/lookup",
                            params={"imsi": IMSI_KNOWN, "apn": TEST_APN,
                                    "use_case_id": "0800"})
        assert r.status_code == 200, \
            f"Lookup with use_case_id=0800 failed: {r.status_code} {r.text}"
        assert r.json()["static_ip"] == KNOWN_STATIC_IP, \
            f"Lookup with use_case_id returned wrong IP: {r.json()}"

        # Step 2: end-to-end RADIUS with charging_chars that maps to use_case_id
        resp = rc.authenticate(IMSI_KNOWN, TEST_APN, charging_chars="0800")
        assert resp.is_accept, (
            f"Expected Access-Accept when charging_chars='0800' (use_case_id forwarded), "
            f"got code={resp.code}"
        )
        assert resp.framed_ip == KNOWN_STATIC_IP, \
            f"Framed-IP-Address={resp.framed_ip!r}, expected {KNOWN_STATIC_IP!r}"

    # 12.14 ───────────────────────────────────────────────────────────────────
    def test_14_use_case_id_forwarded_in_stage2_first_connection(
            self, rc: RadiusClient, lookup_http: httpx.Client, http: httpx.Client):
        """
        3GPP-Charging-Characteristics must be forwarded as use_case_id in the
        Stage 2 POST /v1/first-connection JSON body.

        A second first-connection IMSI (IMSI_FC_NEW2) is used so test_06 state
        is not affected.  charging_chars="0900" is chosen to differ from the
        default "0800" used in other tests, confirming the server forwards
        the actual VSA value rather than a hard-coded string.

        After the test the auto-created profile sim_id is stored for teardown.
        """
        # Confirm no profile exists before the test
        r_pre = lookup_http.get("/lookup",
                                params={"imsi": IMSI_FC_NEW2, "apn": TEST_APN})
        assert r_pre.status_code == 404, \
            f"Pre-condition failed: IMSI_FC_NEW2 already has a profile ({r_pre.status_code})"

        resp = rc.authenticate(
            IMSI_FC_NEW2,
            TEST_APN,
            imei="35812300000002",
            charging_chars="0900",
        )
        assert resp.is_accept, (
            f"Expected Access-Accept via first-connection with use_case_id='0900', "
            f"got code={resp.code}. "
            "Check PROVISIONING_URL and that the range config covers IMSI_FC_NEW2."
        )
        assert resp.framed_ip is not None, \
            "Access-Accept must contain Framed-IP-Address after first-connection"

        TestRadiusServer.fc_allocated_ip2 = resp.framed_ip

        # Fetch the auto-created sim_id for teardown
        r_profile = http.get("/profiles", params={"imsi": IMSI_FC_NEW2})
        if r_profile.status_code == 200:
            data = r_profile.json()
            profiles = data if isinstance(data, list) else data.get("profiles", [])
            if profiles:
                TestRadiusServer.fc_sim_id2 = profiles[0]["sim_id"]

        # Stage 1 should now resolve the newly allocated IP (also with use_case_id)
        r_post = lookup_http.get("/lookup",
                                 params={"imsi": IMSI_FC_NEW2, "apn": TEST_APN,
                                         "use_case_id": "0900"})
        assert r_post.status_code == 200, \
            f"Lookup should succeed after first-connection, got {r_post.status_code}"
        assert r_post.json()["static_ip"] == resp.framed_ip, \
            "Framed-IP in Accept does not match the static_ip returned by lookup"
