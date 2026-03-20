#include "Handler.h"
#include "Metrics.h"

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <chrono>
#include <format>
#include <stdexcept>

Handler::Handler(const Config& cfg) : cfg_(cfg) {}

// ---------------------------------------------------------------------------
// handle — main entry point
// ---------------------------------------------------------------------------
std::vector<uint8_t> Handler::handle(const RadiusRequest& req) {
    const auto t0 = std::chrono::steady_clock::now();
    const std::string imsi = req.imsi();
    const std::string apn  = req.apn();

    auto finish = [&](const std::string& result, const std::string& stage,
                      std::vector<uint8_t> pkt) -> std::vector<uint8_t> {
        double ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - t0).count();
        Metrics::instance().recordRequestDuration(ms);
        Metrics::instance().incRadiusRequest(result, stage);
        return pkt;
    };

    if (imsi.empty()) {
        spdlog::warn("RADIUS id={} — no IMSI (User-Name or 3GPP-IMSI VSA missing), rejecting",
                     req.id);
        Metrics::instance().incResponseRejects();
        return finish("reject", "1",
            buildAccessReject(req.id, req.authenticator, cfg_.radiusSecret));
    }
    if (apn.empty()) {
        spdlog::warn("RADIUS id={} IMSI={} — no APN (Called-Station-Id missing), rejecting",
                     req.id, imsi);
        Metrics::instance().incResponseRejects();
        return finish("reject", "1",
            buildAccessReject(req.id, req.authenticator, cfg_.radiusSecret));
    }

    spdlog::debug(
        "RADIUS id={} IMSI={} APN={} NAS={}/{} RAT={} NSAPI={} MSISDN={} "
        "MCC-MNC={} ChgChars={} SelectMode={} IMEI={}",
        req.id, imsi, apn,
        req.nasIpAddress.empty() ? "-" : req.nasIpAddress,
        req.nasIdentifier.empty() ? "-" : req.nasIdentifier,
        static_cast<int>(req.ratType),
        static_cast<int>(req.nsapi),
        req.callingStationId.empty() ? "-" : req.callingStationId,
        req.imsiMccMnc.empty() ? "-" : req.imsiMccMnc,
        req.chargingChars.empty() ? "-" : req.chargingChars,
        req.selectionMode.empty() ? "-" : req.selectionMode,
        req.imei().empty() ? "-" : req.imei());

    // ── Stage 1: hot-path lookup ──────────────────────────────────────────
    try {
        std::string ip = lookup(imsi, apn, req.chargingChars);
        if (!ip.empty()) {
            spdlog::info("RADIUS id={} IMSI={} APN={} → Accept IP={}", req.id, imsi, apn, ip);
            Metrics::instance().incResponseAccepts();
            return finish("accept", "1",
                buildAccessAccept(req.id, req.authenticator, ip, cfg_.radiusSecret));
        }
    } catch (const std::exception& ex) {
        // 403 (suspended) or unexpected error → reject immediately
        spdlog::warn("RADIUS id={} IMSI={} lookup: {} → Reject", req.id, imsi, ex.what());
        Metrics::instance().incResponseRejects();
        return finish("reject", "1",
            buildAccessReject(req.id, req.authenticator, cfg_.radiusSecret));
    }

    // ── Stage 2: first-connection allocation (lookup returned 404) ────────
    spdlog::info("RADIUS id={} IMSI={} APN={} not found — initiating first-connection",
                 req.id, imsi, apn);
    try {
        std::string ip = firstConnection(imsi, apn, req.imei(), req.chargingChars);
        if (!ip.empty()) {
            spdlog::info("RADIUS id={} IMSI={} → first-connection Accept IP={}",
                         req.id, imsi, ip);
            Metrics::instance().incResponseAccepts();
            return finish("accept", "2",
                buildAccessAccept(req.id, req.authenticator, ip, cfg_.radiusSecret));
        }
    } catch (const std::exception& ex) {
        spdlog::error("RADIUS id={} IMSI={} first-connection error: {}", req.id, imsi, ex.what());
    }

    spdlog::warn("RADIUS id={} IMSI={} → Reject (no IP available)", req.id, imsi);
    Metrics::instance().incResponseRejects();
    return finish("reject", "2",
        buildAccessReject(req.id, req.authenticator, cfg_.radiusSecret));
}

// ---------------------------------------------------------------------------
// lookup — Stage 1
// ---------------------------------------------------------------------------
std::string Handler::lookup(const std::string& imsi,
                             const std::string& apn,
                             const std::string& useCaseId) {
    std::string url = cfg_.lookupUrl + "/lookup?imsi=" + imsi + "&apn=" + apn;
    if (!useCaseId.empty())
        url += "&use_case_id=" + useCaseId;

    Metrics::instance().incLookupRequests();
    auto resp = http_.get(url);

    if (resp.statusCode == 200) {
        Metrics::instance().incLookupResponse(200);
        auto j = nlohmann::json::parse(resp.body);
        return j.at("static_ip").get<std::string>();
    }
    if (resp.statusCode == 404) {
        Metrics::instance().incLookupResponse(404);
        // {"error":"not_found"} — caller will try first-connection
        return {};
    }
    if (resp.statusCode == 403) {
        Metrics::instance().incLookupResponse(403);
        // {"error":"suspended"} — subscriber suspended, do not allocate
        throw std::runtime_error("subscriber suspended");
    }
    // -1 (curl error) or unexpected HTTP status
    Metrics::instance().incLookupResponse(resp.statusCode);
    std::string sc = resp.statusCode == -1 ? "curl_error" : std::to_string(resp.statusCode);
    Metrics::instance().incUpstreamError("lookup", sc);
    throw std::runtime_error(
        std::format("lookup returned HTTP {} body={}", resp.statusCode, resp.body));
}

// ---------------------------------------------------------------------------
// firstConnection — Stage 2 (POST /v1/first-connection)
// ---------------------------------------------------------------------------
std::string Handler::firstConnection(const std::string& imsi,
                                     const std::string& apn,
                                     const std::string& imei,
                                     const std::string& useCaseId) {
    nlohmann::json body;
    body["imsi"] = imsi;
    body["apn"]  = apn;
    if (!imei.empty())       body["imei"]        = imei;
    if (!useCaseId.empty())  body["use_case_id"] = useCaseId;

    std::string url  = cfg_.provisioningUrl + "/v1/first-connection";
    Metrics::instance().incFirstConnRequests();
    auto resp = http_.post(url, body.dump());

    if (resp.statusCode == 200 || resp.statusCode == 201) {
        Metrics::instance().incFirstConnResponse(200);
        auto j = nlohmann::json::parse(resp.body);
        return j.at("static_ip").get<std::string>();
    }
    if (resp.statusCode == 404 || resp.statusCode == 503) {
        Metrics::instance().incFirstConnResponse(resp.statusCode);
        // not_found: no range config for this IMSI
        // pool_exhausted: no IPs left in pool
        return {};
    }
    // -1 (curl error) or unexpected HTTP status
    Metrics::instance().incFirstConnResponse(resp.statusCode);
    std::string sc = resp.statusCode == -1 ? "curl_error" : std::to_string(resp.statusCode);
    Metrics::instance().incUpstreamError("first_connection", sc);
    throw std::runtime_error(
        std::format("first-connection returned HTTP {} body={}",
                    resp.statusCode, resp.body));
}
