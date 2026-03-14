#pragma once

#include "Config.h"
#include "HttpClient.h"
#include "Radius.h"

#include <string>
#include <vector>

// ---------------------------------------------------------------------------
// Handler — two-stage AAA request handler
//
// Stage 1: GET /lookup?imsi=...&apn=...
//   200 → Access-Accept with Framed-IP-Address from response
//   403 → Access-Reject (subscriber suspended)
//   404 → proceed to Stage 2
//
// Stage 2: POST /v1/first-connection {imsi, apn, imei}
//   200 → Access-Accept with allocated IP
//   404/503 → Access-Reject (range not configured or pool exhausted)
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
    std::string lookup(const std::string& imsi, const std::string& apn);

    // Returns the static_ip on success, empty string on 404/503.
    // Throws on unexpected HTTP errors.
    std::string firstConnection(const std::string& imsi,
                                const std::string& apn,
                                const std::string& imei);
};
