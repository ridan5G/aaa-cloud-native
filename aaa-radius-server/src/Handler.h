#pragma once

#include "Config.h"
#include "HttpClient.h"
#include "Radius.h"

#include <string>
#include <vector>

// ---------------------------------------------------------------------------
// Handler — two-stage AAA request handler
//
// Stage 1: GET /lookup?imsi=...&apn=...&use_case_id=...
//   200 → Access-Accept with Framed-IP-Address from response
//   403 → Access-Reject (subscriber suspended)
//   404 → proceed to Stage 2
//
// Stage 2: POST /v1/first-connection {imsi, apn, imei, use_case_id}
//   200 → Access-Accept with allocated IP
//   404/503 → Access-Reject (range not configured or pool exhausted)
//
// use_case_id is sourced from 3GPP-Charging-Characteristics VSA (10415:13).
// It is appended to every upstream call so the lookup service and provisioning
// API can apply per-use-case routing, pool selection, or policy logic.
// When absent (empty) the parameter is omitted from both requests.
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

    // Returns the static_ip on success, empty string on 404/not-found.
    // Throws on 403 (suspended) or other HTTP errors.
    // useCaseId sourced from 3GPP-Charging-Characteristics — forwarded as
    // query param use_case_id; omitted when empty.
    std::string lookup(const std::string& imsi,
                       const std::string& apn,
                       const std::string& useCaseId);

    // Returns the static_ip on success, empty string on 404/503.
    // Throws on unexpected HTTP errors.
    // useCaseId forwarded as JSON field "use_case_id"; omitted when empty.
    std::string firstConnection(const std::string& imsi,
                                const std::string& apn,
                                const std::string& imei,
                                const std::string& useCaseId);
};
