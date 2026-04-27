"""
fixtures/radius.py — Full 3GPP RADIUS authentication client for regression testing.

Implements RFC 2865 Access-Request / Access-Accept / Access-Reject with all
standard and 3GPP AVPs verified against pcap captures.

Attribute sources (TS 29.061 §16.4 + RFC 2865):

Standard RADIUS:
  [1]  User-Name          → IMSI (fallback; NAI or raw digits)
  [4]  NAS-IP-Address     → NAS IPv4 address
  [5]  NAS-Port           → NAS port number (uint32)
  [6]  Service-Type       → 2=Framed
  [7]  Framed-Protocol    → 7=GPRS-PDP-Context or 1=PPP
  [8]  Framed-IP-Address  → allocated IP (in Access-Accept only)
  [30] Called-Station-Id  → APN
  [31] Calling-Station-Id → MSISDN
  [32] NAS-Identifier     → NAS hostname
  [61] NAS-Port-Type      → 18=Wireless-Other

3GPP VSAs (vendor 10415):
  type=1  3GPP-IMSI                → preferred IMSI source (confirmed in pcap)
  type=8  3GPP-IMSI-MCC-MNC        → subscriber home MCC+MNC
  type=9  3GPP-GGSN-MCC-MNC        → GGSN/PGW MCC+MNC
  type=10 3GPP-NSAPI               → PDP context NSAPI (1 byte, 5–15)
  type=12 3GPP-Selection-Mode      → APN selection mode
  type=13 3GPP-Charging-Characteristics → charging class (4-hex string)
  type=20 3GPP-IMEISV              → IMEI+SVN (16 digits; confirmed in pcap)
  type=21 3GPP-RAT-Type            → radio access type (1 byte; 6=E-UTRAN)
  type=22 3GPP-User-Location-Info  → binary TAI+ECGI
  type=23 3GPP-MS-TimeZone         → binary timezone (2 bytes)
"""
import hashlib
import os
import socket
import struct
from dataclasses import dataclass, field
from typing import Optional

# ── RADIUS codes (RFC 2865 §4) ────────────────────────────────────────────────
CODE_ACCESS_REQUEST = 1
CODE_ACCESS_ACCEPT  = 2
CODE_ACCESS_REJECT  = 3

# ── Standard RADIUS attribute types (RFC 2865) ───────────────────────────────
ATTR_USER_NAME          = 1
ATTR_NAS_IP_ADDRESS     = 4
ATTR_NAS_PORT           = 5
ATTR_SERVICE_TYPE       = 6
ATTR_FRAMED_PROTOCOL    = 7
ATTR_FRAMED_IP_ADDRESS  = 8
ATTR_VENDOR_SPECIFIC    = 26
ATTR_CALLED_STATION_ID  = 30
ATTR_CALLING_STATION_ID = 31
ATTR_NAS_IDENTIFIER     = 32
ATTR_NAS_PORT_TYPE      = 61

# ── Service-Type values ───────────────────────────────────────────────────────
SERVICE_TYPE_FRAMED     = 2
SERVICE_TYPE_CALL_CHECK = 10

# ── Framed-Protocol values ────────────────────────────────────────────────────
FRAMED_PROTOCOL_PPP          = 1
FRAMED_PROTOCOL_GPRS_PDP     = 7   # GPRS PDP Context (3GPP TS 29.061)

# ── NAS-Port-Type values ──────────────────────────────────────────────────────
NAS_PORT_TYPE_VIRTUAL        = 5
NAS_PORT_TYPE_WIRELESS_OTHER = 18

# ── 3GPP vendor and VSA sub-type constants ────────────────────────────────────
VENDOR_3GPP              = 10415   # 0x000028AF

VSA_3GPP_IMSI            = 1       # 3GPP-IMSI
VSA_3GPP_IMSI_MCC_MNC    = 8       # 3GPP-IMSI-MCC-MNC
VSA_3GPP_GGSN_MCC_MNC    = 9       # 3GPP-GGSN-MCC-MNC
VSA_3GPP_NSAPI           = 10      # 3GPP-NSAPI
VSA_3GPP_SELECTION_MODE  = 12      # 3GPP-Selection-Mode
VSA_3GPP_CHARGING_CHARS  = 13      # 3GPP-Charging-Characteristics
VSA_3GPP_IMEISV          = 20      # 3GPP-IMEISV
VSA_3GPP_RAT_TYPE        = 21      # 3GPP-RAT-Type
VSA_3GPP_ULI             = 22      # 3GPP-User-Location-Info
VSA_3GPP_MS_TIMEZONE     = 23      # 3GPP-MS-TimeZone

# ── RAT-Type values (3GPP TS 29.061) ──────────────────────────────────────────
RAT_TYPE_WLAN            = 3
RAT_TYPE_GAN             = 4
RAT_TYPE_HSPA_EVOLUTION  = 5
RAT_TYPE_EUTRAN          = 6
RAT_TYPE_VIRTUAL         = 7
RAT_TYPE_EUTRAN_NB_IOT   = 8
RAT_TYPE_LTE_M           = 9
RAT_TYPE_NR              = 10
RAT_TYPE_NR_U            = 11


# ── Response dataclass ────────────────────────────────────────────────────────

@dataclass
class RadiusResponse:
    code:            int
    id:              int
    # Access-Accept attributes
    framed_ip:       Optional[str]   = None    # attr 8 — Framed-IP-Address
    # Parsed from any response
    reply_message:   Optional[str]   = None    # attr 18 — Reply-Message
    # Raw per-type attribute bytes (type → first occurrence raw bytes)
    raw_attrs:       dict            = field(repr=False, default_factory=dict)
    raw_auth:        bytes           = field(repr=False, default=b"")  # 16-byte response auth

    @property
    def is_accept(self) -> bool:
        return self.code == CODE_ACCESS_ACCEPT

    @property
    def is_reject(self) -> bool:
        return self.code == CODE_ACCESS_REJECT


# ── Low-level attribute builders ─────────────────────────────────────────────

def _attr(attr_type: int, value: bytes) -> bytes:
    """Build a standard RADIUS attribute: type(1) + length(1) + value."""
    return struct.pack("!BB", attr_type, 2 + len(value)) + value


def _attr_uint32(attr_type: int, value: int) -> bytes:
    """Build a 4-byte integer RADIUS attribute."""
    return _attr(attr_type, struct.pack("!I", value))


def _attr_ipv4(attr_type: int, ip_str: str) -> bytes:
    """Build a 4-byte IPv4 RADIUS attribute from dotted-decimal string."""
    return _attr(attr_type, socket.inet_aton(ip_str))


def _vsa_3gpp(vsa_type: int, value: bytes) -> bytes:
    """Build a 3GPP Vendor-Specific attribute.

    Wire layout (verified against pcap captures):
      outer:  type=26(1B) + attr_len(1B) + vendor_id(4B) + vsa_type(1B) + vsa_len(1B) + value
      vsa_len = 2 + len(value)  (includes the vsa_type and vsa_len bytes themselves)
    """
    vsa_payload = struct.pack("!IBB", VENDOR_3GPP, vsa_type, 2 + len(value)) + value
    return _attr(ATTR_VENDOR_SPECIFIC, vsa_payload)


def _vsa_3gpp_uint8(vsa_type: int, value: int) -> bytes:
    """Build a single-byte 3GPP VSA."""
    return _vsa_3gpp(vsa_type, struct.pack("!B", value))


# ── Packet building ───────────────────────────────────────────────────────────

def build_access_request(
    pkt_id:          int,
    imsi:            str,
    apn:             str,
    *,
    imei:            str   = "",
    msisdn:          str   = "",
    nas_ip:          str   = "127.0.0.1",
    nas_identifier:  str   = "test-nas-01",
    nas_port:        int   = 0,
    nas_port_type:   int   = NAS_PORT_TYPE_WIRELESS_OTHER,
    service_type:    int   = SERVICE_TYPE_FRAMED,
    framed_protocol: int   = FRAMED_PROTOCOL_GPRS_PDP,
    mcc_mnc:         str   = "",          # 3GPP-IMSI-MCC-MNC / 3GPP-GGSN-MCC-MNC
    nsapi:           int   = 5,           # 3GPP-NSAPI (5–15)
    selection_mode:  str   = "0",         # 3GPP-Selection-Mode
    charging_chars:  str   = "0800",      # 3GPP-Charging-Characteristics
    rat_type:        int   = RAT_TYPE_EUTRAN,
    uli:             bytes = b"",         # 3GPP-User-Location-Info (binary)
    ms_timezone:     bytes = b"",         # 3GPP-MS-TimeZone (binary, 2 bytes)
    user_name_override: str = "",         # if set, overrides User-Name (keeps IMSI in VSA)
) -> tuple[bytes, bytes]:
    """Build a full 3GPP RADIUS Access-Request packet.

    Includes all standard RADIUS attributes and 3GPP VSAs that a real
    PGW/GGSN/SMF would send.  All parameters have sensible test defaults so
    existing callers work without modification.

    Returns (packet_bytes, request_authenticator_16_bytes).
    The request authenticator is a random 16-byte nonce (RFC 2865 §3).
    """
    request_auth = os.urandom(16)

    # Derive mcc_mnc from IMSI prefix if not supplied (first 5 digits = MCC+MNC)
    if not mcc_mnc and len(imsi) >= 5:
        mcc_mnc = imsi[:5]

    # Default ULI: a minimal E-UTRAN TAI+ECGI for test purposes
    # Type=0x82 (TAI+ECGI), MCC=278 MNC=77 TAC=0x0001, ECI=0x0000001
    if not uli:
        uli = bytes([
            0x82,                          # TAI + ECGI indicator
            0x72, 0xF8, 0x27,             # MCC=278, MNC=77 (BCD encoded)
            0x00, 0x01,                    # TAC = 1
            0x72, 0xF8, 0x27,             # MCC=278, MNC=77
            0x00, 0x00, 0x00, 0x01,        # E-Cell-ID = 1
        ])

    # Default MS-TimeZone: UTC+2 (Israel), no DST
    if not ms_timezone:
        ms_timezone = bytes([0x08, 0x00])

    attrs = bytearray()

    # ── Standard RADIUS attributes ──────────────────────────────────────────
    # [1]  User-Name = IMSI (or override for VSA-priority tests)
    user_name = user_name_override if user_name_override else imsi
    attrs += _attr(ATTR_USER_NAME, user_name.encode())

    # [4]  NAS-IP-Address
    attrs += _attr_ipv4(ATTR_NAS_IP_ADDRESS, nas_ip)

    # [5]  NAS-Port
    attrs += _attr_uint32(ATTR_NAS_PORT, nas_port)

    # [6]  Service-Type = Framed (2)
    attrs += _attr_uint32(ATTR_SERVICE_TYPE, service_type)

    # [7]  Framed-Protocol = GPRS-PDP-Context (7)
    attrs += _attr_uint32(ATTR_FRAMED_PROTOCOL, framed_protocol)

    # [30] Called-Station-Id = APN
    attrs += _attr(ATTR_CALLED_STATION_ID, apn.encode())

    # [31] Calling-Station-Id = MSISDN (optional)
    if msisdn:
        attrs += _attr(ATTR_CALLING_STATION_ID, msisdn.encode())

    # [32] NAS-Identifier
    attrs += _attr(ATTR_NAS_IDENTIFIER, nas_identifier.encode())

    # [61] NAS-Port-Type = Wireless-Other (18)
    attrs += _attr_uint32(ATTR_NAS_PORT_TYPE, nas_port_type)

    # ── 3GPP VSAs ────────────────────────────────────────────────────────────
    # VSA 10415:1  — 3GPP-IMSI (preferred IMSI source; always matches real IMSI)
    attrs += _vsa_3gpp(VSA_3GPP_IMSI, imsi.encode())

    # VSA 10415:8  — 3GPP-IMSI-MCC-MNC (subscriber's home network)
    if mcc_mnc:
        attrs += _vsa_3gpp(VSA_3GPP_IMSI_MCC_MNC, mcc_mnc.encode())

    # VSA 10415:9  — 3GPP-GGSN-MCC-MNC (GGSN/PGW home network, same as IMSI for tests)
    if mcc_mnc:
        attrs += _vsa_3gpp(VSA_3GPP_GGSN_MCC_MNC, mcc_mnc.encode())

    # VSA 10415:10 — 3GPP-NSAPI (1 byte)
    attrs += _vsa_3gpp_uint8(VSA_3GPP_NSAPI, nsapi)

    # VSA 10415:12 — 3GPP-Selection-Mode
    attrs += _vsa_3gpp(VSA_3GPP_SELECTION_MODE, selection_mode.encode())

    # VSA 10415:13 — 3GPP-Charging-Characteristics
    attrs += _vsa_3gpp(VSA_3GPP_CHARGING_CHARS, charging_chars.encode())

    # VSA 10415:20 — 3GPP-IMEISV (optional)
    if imei:
        attrs += _vsa_3gpp(VSA_3GPP_IMEISV, imei.encode())

    # VSA 10415:21 — 3GPP-RAT-Type (1 byte)
    attrs += _vsa_3gpp_uint8(VSA_3GPP_RAT_TYPE, rat_type)

    # VSA 10415:22 — 3GPP-User-Location-Info (binary)
    attrs += _vsa_3gpp(VSA_3GPP_ULI, uli)

    # VSA 10415:23 — 3GPP-MS-TimeZone (binary)
    attrs += _vsa_3gpp(VSA_3GPP_MS_TIMEZONE, ms_timezone)

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
    Populates all known AVPs in the returned RadiusResponse; unknown types are
    stored raw in raw_attrs for caller inspection.
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

        # Store raw bytes for every attr (first occurrence wins)
        resp.raw_attrs.setdefault(a_type, a_val)

        if a_type == ATTR_FRAMED_IP_ADDRESS and len(a_val) == 4:
            resp.framed_ip = ".".join(str(b) for b in a_val)

        elif a_type == 18:   # Reply-Message
            try:
                resp.reply_message = a_val.decode("utf-8", errors="replace")
            except Exception:
                pass

        pos += a_len

    return resp


# ── Client ────────────────────────────────────────────────────────────────────

class RadiusClient:
    """Synchronous 3GPP RADIUS authentication client (Access-Request only).

    Sends full Access-Request packets including all standard RADIUS attributes
    and 3GPP VSAs (TS 29.061) that a real PGW/GGSN/SMF would send.

    Creates a fresh UDP socket per authenticate() call so the client is
    safely usable from multiple test threads simultaneously.
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
        imsi:            str,
        apn:             str,
        *,
        imei:            str   = "",
        msisdn:          str   = "",
        nas_ip:          str   = "127.0.0.1",
        nas_identifier:  str   = "test-nas-01",
        nas_port:        int   = 0,
        nas_port_type:   int   = NAS_PORT_TYPE_WIRELESS_OTHER,
        service_type:    int   = SERVICE_TYPE_FRAMED,
        framed_protocol: int   = FRAMED_PROTOCOL_GPRS_PDP,
        mcc_mnc:         str   = "",
        nsapi:           int   = 5,
        selection_mode:  str   = "0",
        charging_chars:  str   = "0800",
        rat_type:        int   = RAT_TYPE_EUTRAN,
        uli:             bytes = b"",
        ms_timezone:     bytes = b"",
        user_name_override: str = "",
    ) -> RadiusResponse:
        """Send one full 3GPP Access-Request; return the parsed response.

        Raises:
            socket.timeout  — server did not respond within self.timeout seconds.
            ValueError      — response is malformed or authenticator is wrong.
        """
        pkt_id = self._next_id()
        packet, request_auth = build_access_request(
            pkt_id, imsi, apn,
            imei=imei,
            msisdn=msisdn,
            nas_ip=nas_ip,
            nas_identifier=nas_identifier,
            nas_port=nas_port,
            nas_port_type=nas_port_type,
            service_type=service_type,
            framed_protocol=framed_protocol,
            mcc_mnc=mcc_mnc,
            nsapi=nsapi,
            selection_mode=selection_mode,
            charging_chars=charging_chars,
            rat_type=rat_type,
            uli=uli,
            ms_timezone=ms_timezone,
            user_name_override=user_name_override,
        )

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self.timeout)
            sock.sendto(packet, (self.host, self.port))
            response_data, _ = sock.recvfrom(4096)

        return parse_response(response_data, request_auth, self.secret)
