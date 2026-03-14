"""
fixtures/radius.py — minimal RADIUS authentication client for regression testing.

Implements RFC 2865 Access-Request / Access-Accept / Access-Reject only.
Uses the standard library (socket, hashlib, struct, os) — no new dependencies.

Attribute sources verified against pcap captures:
  [1]  User-Name          → IMSI fallback
  [26] VSA vendor=10415 type=1  → 3GPP-IMSI  (preferred)
  [26] VSA vendor=10415 type=20 → 3GPP-IMEISV
  [30] Called-Station-Id  → APN
  [31] Calling-Station-Id → MSISDN
"""
import hashlib
import os
import socket
import struct
from dataclasses import dataclass, field

# ── RADIUS codes (RFC 2865 §4) ────────────────────────────────────────────────
CODE_ACCESS_REQUEST = 1
CODE_ACCESS_ACCEPT  = 2
CODE_ACCESS_REJECT  = 3

# ── Standard RADIUS attribute types ──────────────────────────────────────────
ATTR_USER_NAME          = 1
ATTR_FRAMED_IP_ADDRESS  = 8
ATTR_VENDOR_SPECIFIC    = 26
ATTR_CALLED_STATION_ID  = 30
ATTR_CALLING_STATION_ID = 31

# ── 3GPP vendor-specific ──────────────────────────────────────────────────────
VENDOR_3GPP      = 10415   # 0x000028AF
VSA_3GPP_IMSI    = 1       # 3GPP-IMSI
VSA_3GPP_IMEISV  = 20      # 3GPP-IMEISV


# ── Response dataclass ────────────────────────────────────────────────────────

@dataclass
class RadiusResponse:
    code:      int
    id:        int
    framed_ip: str | None = None
    raw_auth:  bytes = field(repr=False, default=b"")   # 16-byte response authenticator

    @property
    def is_accept(self) -> bool:
        return self.code == CODE_ACCESS_ACCEPT

    @property
    def is_reject(self) -> bool:
        return self.code == CODE_ACCESS_REJECT


# ── Packet building ───────────────────────────────────────────────────────────

def _attr(attr_type: int, value: bytes) -> bytes:
    """Build a standard RADIUS attribute: type(1) + length(1) + value."""
    return struct.pack("!BB", attr_type, 2 + len(value)) + value


def _vsa_3gpp(vsa_type: int, value: bytes) -> bytes:
    """Build a 3GPP Vendor-Specific attribute.

    Layout (verified against pcap captures):
      outer: type=26(1) + attr_len(1) + vendor_id(4) + vsa_type(1) + vsa_len(1) + value
      vsa_len = 2 + len(value)  (includes the vsa_type and vsa_len bytes)
    """
    vsa_payload = struct.pack("!IBB", VENDOR_3GPP, vsa_type, 2 + len(value)) + value
    return _attr(ATTR_VENDOR_SPECIFIC, vsa_payload)


def build_access_request(
    pkt_id: int,
    imsi:   str,
    apn:    str,
    imei:   str = "",
    msisdn: str = "",
) -> tuple[bytes, bytes]:
    """Build a RADIUS Access-Request packet.

    Returns (packet_bytes, request_authenticator).
    The request authenticator is a random 16-byte nonce (RFC 2865 §3).
    """
    request_auth = os.urandom(16)

    attrs = bytearray()
    # [1]  User-Name = IMSI  (fallback for non-3GPP RADIUS clients)
    attrs += _attr(ATTR_USER_NAME, imsi.encode())
    # [30] Called-Station-Id = APN
    attrs += _attr(ATTR_CALLED_STATION_ID, apn.encode())
    # [26] VSA 10415:1 = 3GPP-IMSI  (preferred source in aaa-radius-server)
    attrs += _vsa_3gpp(VSA_3GPP_IMSI, imsi.encode())
    # [26] VSA 10415:20 = 3GPP-IMEISV  (forwarded to first-connection)
    if imei:
        attrs += _vsa_3gpp(VSA_3GPP_IMEISV, imei.encode())
    # [31] Calling-Station-Id = MSISDN  (informational)
    if msisdn:
        attrs += _attr(ATTR_CALLING_STATION_ID, msisdn.encode())

    total_len = 20 + len(attrs)
    header = struct.pack("!BBH", CODE_ACCESS_REQUEST, pkt_id, total_len)
    packet = header + request_auth + bytes(attrs)
    return packet, request_auth


# ── Response parsing and verification ────────────────────────────────────────

def verify_response_auth(response: bytes, request_auth: bytes, secret: str) -> bool:
    """Verify the RADIUS response authenticator (RFC 2865 §3).

    ResponseAuth = MD5(Code | ID | Length | RequestAuth | Attributes | Secret)
    """
    if len(response) < 20:
        return False
    code, rid = response[0], response[1]
    length = struct.unpack_from("!H", response, 2)[0]
    if length < 20 or length > len(response):
        return False
    attrs_bytes = response[20:length]
    expected = hashlib.md5(
        bytes([code, rid])
        + struct.pack("!H", length)
        + request_auth
        + attrs_bytes
        + secret.encode()
    ).digest()
    return response[4:20] == expected


def parse_response(data: bytes, request_auth: bytes, secret: str) -> RadiusResponse:
    """Parse and authenticate a RADIUS response datagram.

    Raises ValueError for short, malformed, or authenticator-mismatched packets.
    """
    if len(data) < 20:
        raise ValueError(f"Response too short: {len(data)} bytes")

    code, rid, length = struct.unpack_from("!BBH", data)
    if length < 20 or length > len(data):
        raise ValueError(f"Invalid RADIUS length field: {length}")

    if not verify_response_auth(data[:length], request_auth, secret):
        raise ValueError(
            "Response authenticator mismatch — wrong shared secret or corrupt packet"
        )

    resp = RadiusResponse(code=code, id=rid, raw_auth=bytes(data[4:20]))

    pos = 20
    while pos + 2 <= length:
        a_type = data[pos]
        a_len  = data[pos + 1]
        if a_len < 2 or pos + a_len > length:
            break
        a_val = data[pos + 2 : pos + a_len]
        if a_type == ATTR_FRAMED_IP_ADDRESS and len(a_val) == 4:
            resp.framed_ip = ".".join(str(b) for b in a_val)
        pos += a_len

    return resp


# ── Client ────────────────────────────────────────────────────────────────────

class RadiusClient:
    """Minimal synchronous RADIUS authentication client (Access-Request only).

    Creates a fresh UDP socket per authenticate() call so the client
    is safely usable from multiple test threads simultaneously.
    """

    def __init__(self, host: str, port: int, secret: str, timeout: float = 10.0):
        self.host    = host
        self.port    = port
        self.secret  = secret
        self.timeout = timeout
        self._id     = 0

    def _next_id(self) -> int:
        self._id = (self._id + 1) % 256
        return self._id

    def authenticate(
        self,
        imsi:   str,
        apn:    str,
        imei:   str = "",
        msisdn: str = "",
    ) -> RadiusResponse:
        """Send one Access-Request; return the parsed Access-Accept or Access-Reject.

        Raises:
            socket.timeout  — server did not respond within self.timeout seconds.
            ValueError      — response is malformed or authenticator is wrong.
        """
        pkt_id = self._next_id()
        packet, request_auth = build_access_request(pkt_id, imsi, apn, imei, msisdn)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self.timeout)
            sock.sendto(packet, (self.host, self.port))
            response_data, _ = sock.recvfrom(4096)

        return parse_response(response_data, request_auth, self.secret)
