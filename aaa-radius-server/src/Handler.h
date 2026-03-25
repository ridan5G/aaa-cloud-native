#pragma once

#include "Config.h"
#include "HttpClient.h"
#include "Radius.h"

#include <string>
#include <vector>

// ---------------------------------------------------------------------------
// Handler — RADIUS ↔ REST adapter
//
// Makes a single upstream call: GET /lookup?imsi=...&apn=...&imei=...&use_case_id=...
// The lookup service handles DB resolution and first-connection allocation
// internally, so the radius server no longer needs to know about staging.
//
//   200 → Access-Accept with Framed-IP-Address from response
//   403 → Access-Reject (subscriber suspended)
//   404 → Access-Reject (no range config for IMSI)
//   503 → Access-Reject (IP pool exhausted)
//
// use_case_id is sourced from 3GPP-Charging-Characteristics VSA (10415:13).
// imei is sourced from 3GPP-IMEISV VSA (10415:20).
// Both are forwarded as query params; omitted when empty.
//
// NOT thread-safe: each worker thread must own its own Handler instance
// (so each has a dedicated CURL handle via HttpClient).
// ---------------------------------------------------------------------------
class Handler {
public:
    explicit Handler(const Config& cfg);

    std::vector<uint8_t> handle(const RadiusRequest& req);

private:
    const Config& cfg_;
    HttpClient    http_;

    // Returns the static_ip on success, empty string on 404/503 (reject).
    // Throws on 403 (suspended) or other HTTP errors.
    // imei and useCaseId are forwarded as query params; omitted when empty.
    std::string lookup(const std::string& imsi,
                       const std::string& apn,
                       const std::string& imei,
                       const std::string& useCaseId);
};
