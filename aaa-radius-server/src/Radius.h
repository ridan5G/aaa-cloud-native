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
// Attributes extracted from an Access-Request that we care about
//
// Attribute sources (from pcap analysis):
//   [1]  User-Name          → fallback IMSI (NAI or raw digits)
//   [26] Vendor-Specific
//          vendor=10415 (3GPP), type=1  → 3GPP-IMSI  (preferred IMSI source)
//          vendor=10415 (3GPP), type=20 → 3GPP-IMEISV (IMEI base)
//   [30] Called-Station-Id  → APN
//   [31] Calling-Station-Id → MSISDN
// ---------------------------------------------------------------------------
struct RadiusRequest {
    uint8_t     id{};
    uint8_t     authenticator[16]{};

    std::string userName;           // attr  1 — User-Name (fallback IMSI)
    std::string calledStationId;    // attr 30 — Called-Station-Id → APN
    std::string callingStationId;   // attr 31 — Calling-Station-Id → MSISDN
    std::string imsi3gpp;           // VSA 10415:1  — 3GPP-IMSI (preferred)
    std::string imeiSv;             // VSA 10415:20 — 3GPP-IMEISV

    // Resolved IMSI: 3GPP-IMSI VSA first, User-Name fallback.
    std::string imsi() const { return imsi3gpp.empty() ? userName : imsi3gpp; }

    // APN: Called-Station-Id as-is.
    const std::string& apn() const { return calledStationId; }

    // IMEI: 3GPP-IMEISV is 16 digits (14 TAC+SNR + 2 SVN).
    // We expose 14 significant digits (TAC+SNR) as the IMEI base.
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
