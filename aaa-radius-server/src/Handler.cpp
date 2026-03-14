#include "Handler.h"

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <format>
#include <stdexcept>

Handler::Handler(const Config& cfg) : cfg_(cfg) {}

// ---------------------------------------------------------------------------
// handle — main entry point
// ---------------------------------------------------------------------------
std::vector<uint8_t> Handler::handle(const RadiusRequest& req) {
    const std::string imsi = req.imsi();
    const std::string apn  = req.apn();

    if (imsi.empty()) {
        spdlog::warn("RADIUS id={} — no IMSI (User-Name or 3GPP-IMSI VSA missing), rejecting",
                     req.id);
        return buildAccessReject(req.id, req.authenticator, cfg_.radiusSecret);
    }
    if (apn.empty()) {
        spdlog::warn("RADIUS id={} IMSI={} — no APN (Called-Station-Id missing), rejecting",
                     req.id, imsi);
        return buildAccessReject(req.id, req.authenticator, cfg_.radiusSecret);
    }

    spdlog::debug("RADIUS id={} IMSI={} APN={}", req.id, imsi, apn);

    // ── Stage 1: hot-path lookup ──────────────────────────────────────────
    try {
        std::string ip = lookup(imsi, apn);
        if (!ip.empty()) {
            spdlog::info("RADIUS id={} IMSI={} APN={} → Accept IP={}", req.id, imsi, apn, ip);
            return buildAccessAccept(req.id, req.authenticator, ip, cfg_.radiusSecret);
        }
    } catch (const std::exception& ex) {
        // 403 (suspended) or unexpected error → reject immediately
        spdlog::warn("RADIUS id={} IMSI={} lookup: {} → Reject", req.id, imsi, ex.what());
        return buildAccessReject(req.id, req.authenticator, cfg_.radiusSecret);
    }

    // ── Stage 2: first-connection allocation (lookup returned 404) ────────
    spdlog::info("RADIUS id={} IMSI={} APN={} not found — initiating first-connection",
                 req.id, imsi, apn);
    try {
        std::string ip = firstConnection(imsi, apn, req.imei());
        if (!ip.empty()) {
            spdlog::info("RADIUS id={} IMSI={} → first-connection Accept IP={}",
                         req.id, imsi, ip);
            return buildAccessAccept(req.id, req.authenticator, ip, cfg_.radiusSecret);
        }
    } catch (const std::exception& ex) {
        spdlog::error("RADIUS id={} IMSI={} first-connection error: {}", req.id, imsi, ex.what());
    }

    spdlog::warn("RADIUS id={} IMSI={} → Reject (no IP available)", req.id, imsi);
    return buildAccessReject(req.id, req.authenticator, cfg_.radiusSecret);
}

// ---------------------------------------------------------------------------
// lookup — Stage 1
// ---------------------------------------------------------------------------
std::string Handler::lookup(const std::string& imsi, const std::string& apn) {
    std::string url = cfg_.lookupUrl + "/lookup?imsi=" + imsi + "&apn=" + apn;
    auto resp = http_.get(url);

    if (resp.statusCode == 200) {
        auto j = nlohmann::json::parse(resp.body);
        return j.at("static_ip").get<std::string>();
    }
    if (resp.statusCode == 404) {
        // {"error":"not_found"} — caller will try first-connection
        return {};
    }
    if (resp.statusCode == 403) {
        // {"error":"suspended"} — subscriber suspended, do not allocate
        throw std::runtime_error("subscriber suspended");
    }
    throw std::runtime_error(
        std::format("lookup returned HTTP {} body={}", resp.statusCode, resp.body));
}

// ---------------------------------------------------------------------------
// firstConnection — Stage 2 (POST /v1/first-connection)
// ---------------------------------------------------------------------------
std::string Handler::firstConnection(const std::string& imsi,
                                     const std::string& apn,
                                     const std::string& imei) {
    nlohmann::json body;
    body["imsi"] = imsi;
    body["apn"]  = apn;
    if (!imei.empty()) body["imei"] = imei;

    std::string url  = cfg_.provisioningUrl + "/v1/first-connection";
    auto        resp = http_.post(url, body.dump());

    if (resp.statusCode == 200) {
        auto j = nlohmann::json::parse(resp.body);
        return j.at("static_ip").get<std::string>();
    }
    if (resp.statusCode == 404 || resp.statusCode == 503) {
        // not_found: no range config for this IMSI
        // pool_exhausted: no IPs left in pool
        return {};
    }
    throw std::runtime_error(
        std::format("first-connection returned HTTP {} body={}",
                    resp.statusCode, resp.body));
}
