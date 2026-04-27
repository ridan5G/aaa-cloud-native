#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

// ---------------------------------------------------------------------------
// RADIUS protocol constants (RFC 2865)
// ---------------------------------------------------------------------------
enum class RadiusCode : uint8_t {
    AccessRequest  = 1,
    AccessAccept   = 2,
    AccessReject   = 3,
};

// ---------------------------------------------------------------------------
// All attributes extracted from an Access-Request
//
// Standard RADIUS (RFC 2865):
//   [1]   User-Name          → fallback IMSI (NAI or raw digits)
//   [4]   NAS-IP-Address     → NAS IPv4 address (dotted-decimal string)
//   [5]   NAS-Port           → NAS port number (uint32)
//   [6]   Service-Type       → 2=Framed (expected from PGW/GGSN)
//   [7]   Framed-Protocol    → 7=GPRS-PDP-Context (3GPP) or 1=PPP
//   [30]  Called-Station-Id  → APN
//   [31]  Calling-Station-Id → MSISDN
//   [32]  NAS-Identifier     → NAS hostname
//   [61]  NAS-Port-Type      → 18=Wireless-Other, 5=Virtual
//
// 3GPP VSAs (vendor 10415, TS 29.061 §16.4):
//   [26/10415:1]  3GPP-IMSI                  → preferred IMSI source
//   [26/10415:8]  3GPP-IMSI-MCC-MNC          → subscriber's home MCC+MNC
//   [26/10415:9]  3GPP-GGSN-MCC-MNC          → GGSN/PGW MCC+MNC
//   [26/10415:10] 3GPP-NSAPI                 → PDP context NSAPI (1 byte, 5–15)
//   [26/10415:12] 3GPP-Selection-Mode        → APN selection mode
//   [26/10415:13] 3GPP-Charging-Characteristics → charging class (hex string)
//   [26/10415:20] 3GPP-IMEISV               → IMEI+SVN (16 digits: TAC+SNR+SVN)
//   [26/10415:21] 3GPP-RAT-Type             → radio access type (1 byte; 6=E-UTRAN)
//   [26/10415:22] 3GPP-User-Location-Info   → binary TAI+ECGI or CGI/SAI/RAI
//   [26/10415:23] 3GPP-MS-TimeZone          → binary timezone offset (2 bytes)
// ---------------------------------------------------------------------------
struct RadiusRequest {
    uint8_t  id{};
    uint8_t  authenticator[16]{};

    // ── Standard RADIUS attributes (RFC 2865) ─────────────────────────────
    std::string  userName;           // attr  1 — User-Name (fallback IMSI)
    std::string  nasIpAddress;       // attr  4 — NAS-IP-Address (dotted-decimal)
    uint32_t     nasPort{0};         // attr  5 — NAS-Port
    uint32_t     serviceType{0};     // attr  6 — Service-Type (2=Framed)
    uint32_t     framedProtocol{0};  // attr  7 — Framed-Protocol (7=GPRS-PDP-Context)
    std::string  calledStationId;    // attr 30 — Called-Station-Id → APN
    std::string  callingStationId;   // attr 31 — Calling-Station-Id → MSISDN
    std::string  nasIdentifier;      // attr 32 — NAS-Identifier
    uint32_t     nasPortType{0};     // attr 61 — NAS-Port-Type (18=Wireless-Other)

    // ── 3GPP VSAs (vendor 10415, TS 29.061) ───────────────────────────────
    std::string  imsi3gpp;           // VSA 10415:1  — 3GPP-IMSI (preferred source)
    std::string  imsiMccMnc;         // VSA 10415:8  — 3GPP-IMSI-MCC-MNC
    std::string  ggsnMccMnc;         // VSA 10415:9  — 3GPP-GGSN-MCC-MNC
    uint8_t      nsapi{0};           // VSA 10415:10 — 3GPP-NSAPI (1 byte, 5–15)
    std::string  selectionMode;      // VSA 10415:12 — 3GPP-Selection-Mode
    std::string  chargingChars;      // VSA 10415:13 — 3GPP-Charging-Characteristics
    std::string  imeiSv;             // VSA 10415:20 — 3GPP-IMEISV
    uint8_t      ratType{0};         // VSA 10415:21 — 3GPP-RAT-Type (1 byte; 6=E-UTRAN)
    std::vector<uint8_t> userLocationInfo; // VSA 10415:22 — binary TAI+ECGI
    std::vector<uint8_t> msTimeZone;       // VSA 10415:23 — binary timezone (2 bytes)

    // ── Helpers ────────────────────────────────────────────────────────────
    // Resolved IMSI: 3GPP-IMSI VSA first, User-Name fallback.
    std::string imsi() const { return imsi3gpp.empty() ? userName : imsi3gpp; }

    // APN: Called-Station-Id as-is.
    const std::string& apn() const { return calledStationId; }

    // IMEI: 3GPP-IMEISV is 16 digits (14 TAC+SNR + 2 SVN).
    // Expose 14 significant digits (IMEI base = TAC+SNR).
    std::string imei() const {
        return imeiSv.size() >= 14 ? imeiSv.substr(0, 14) : imeiSv;
    }
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

// Parse raw UDP payload. Returns nullopt if malformed or not Access-Request.
std::optional<RadiusRequest> parseAccessRequest(const uint8_t* data, std::size_t len);

// Build Access-Accept with Framed-IP-Address (attr 8).
// Response authenticator = MD5(code+id+len+reqAuth+attrs+secret).
std::vector<uint8_t> buildAccessAccept(
    uint8_t            id,
    const uint8_t      requestAuth[16],
    const std::string& framedIp,
    const std::string& secret);

// Build Access-Reject (no attributes).
std::vector<uint8_t> buildAccessReject(
    uint8_t            id,
    const uint8_t      requestAuth[16],
    const std::string& secret);
