#include "LookupController.h"

#include <chrono>
#include <fstream>
#include <string>
#include <vector>

#include <drogon/drogon.h>
#include <jwt-cpp/jwt.h>
#include <spdlog/spdlog.h>

#include "../Config.h"
#include "../Metrics.h"
#include "../Resolver.h"

// ---------------------------------------------------------------------------
// Hot-path SQL query (Plan 2 — DB plan, read replica, no writes).
//
// Returns one row per (imsi_apn_ips × iccid_ips) combination.
// Resolver::resolve() picks the correct row based on ip_resolution mode.
// ---------------------------------------------------------------------------
static constexpr auto HOT_PATH_SQL = R"SQL(
SELECT
    sp.status           AS sim_status,
    sp.ip_resolution,
    si.status           AS imsi_status,
    sa.apn              AS imsi_apn,
    sa.static_ip        AS imsi_static_ip,
    ci.apn              AS iccid_apn,
    ci.static_ip        AS iccid_static_ip
FROM        imsi2sim       si
JOIN        sim_profiles   sp ON sp.sim_id    = si.sim_id
LEFT JOIN   imsi_apn_ips  sa ON sa.imsi       = si.imsi
LEFT JOIN   sim_apn_ips   ci ON ci.sim_id     = sp.sim_id
WHERE       si.imsi = $1
)SQL";

// ---------------------------------------------------------------------------
// Pre-qualification SQL — runs on the read replica when HOT_PATH_SQL misses.
// If no row covers the IMSI, the request is rejected with 404 "unqualified"
// without involving subscriber-profile-api or the primary DB.
//
// Mirrored in subscriber-profile-api/app/routers/first_connection.py:247 —
// keep the status filter ('active','provisioned') in sync.
// ---------------------------------------------------------------------------
static constexpr auto PREQUALIFY_SQL = R"SQL(
SELECT 1
FROM   imsi_range_configs
WHERE  f_imsi <= $1
  AND  t_imsi >= $1
  AND  status IN ('active', 'provisioned')
LIMIT  1
)SQL";

// ---------------------------------------------------------------------------
// Parameter validation helpers
// ---------------------------------------------------------------------------
static bool isValidImsi(const std::string& imsi) {
    if (imsi.size() != 15) return false;
    for (char c : imsi)
        if (c < '0' || c > '9') return false;
    return true;
}

// ---------------------------------------------------------------------------
// LookupController::errorResponse
// ---------------------------------------------------------------------------
drogon::HttpResponsePtr LookupController::errorResponse(
        drogon::HttpStatusCode code,
        const std::string& error,
        const std::string& param) {

    Json::Value body;
    body["error"] = error;
    if (!param.empty())
        body["param"] = param;

    auto resp = drogon::HttpResponse::newHttpJsonResponse(body);
    resp->setStatusCode(code);
    return resp;
}

// ---------------------------------------------------------------------------
// JWT verification — reads the RS256 public key once (cached) and verifies
// the Authorization: Bearer <token> header.
// When JWT_SKIP_VERIFY=true (dev only), always passes.
// ---------------------------------------------------------------------------
#include <jwt-cpp/traits/nlohmann-json/traits.h>
bool LookupController::verifyJwt(
        const drogon::HttpRequestPtr& req,
        std::function<void(const drogon::HttpResponsePtr&)>& callback) {

    const auto& cfg = Config::instance();
    if (cfg.jwtSkipVerify) return true;

    // Cache the public key (read once on first request).
    static std::string cachedPem = []() {
        std::ifstream f(Config::instance().jwtPublicKeyPath);
        if (!f) throw std::runtime_error(
            "Cannot open JWT public key: " + Config::instance().jwtPublicKeyPath);
        return std::string(std::istreambuf_iterator<char>(f),
                           std::istreambuf_iterator<char>());
    }();

    const std::string authHeader = req->getHeader("Authorization");
    if (authHeader.substr(0, 7) != "Bearer ") {
        callback(errorResponse(drogon::k401Unauthorized, "missing_token"));
        return false;
    }
    const std::string token = authHeader.substr(7);

    using jwt_traits = jwt::traits::nlohmann_json;

auto verifier = jwt::verify<jwt_traits>()
    .allow_algorithm(jwt::algorithm::rs256(cachedPem, "", "", ""))
    .with_issuer("aaa-platform");  // adjust to your OIDC issuer

auto decoded = jwt::decode<jwt_traits>(token);
verifier.verify(decoded);
return true;
}

// ---------------------------------------------------------------------------
// LookupController::callFirstConnection — Stage 2 fallback
// ---------------------------------------------------------------------------
void LookupController::callFirstConnection(
        const std::string& imsi,
        const std::string& apn,
        const std::string& imei,
        const std::string& useCaseId,
        std::shared_ptr<std::function<void(const drogon::HttpResponsePtr&)>> sharedCb) {

    // Lazily initialise the HTTP client (reused across requests).
    if (!firstConnClient_) {
        firstConnClient_ = drogon::HttpClient::newHttpClient(
            Config::instance().provisioningUrl);
    }

    Json::Value fcBody;
    fcBody["imsi"] = imsi;
    fcBody["apn"]  = apn;
    if (!imei.empty())       fcBody["imei"]        = imei;
    if (!useCaseId.empty())  fcBody["use_case_id"] = useCaseId;

    auto fcReq = drogon::HttpRequest::newHttpJsonRequest(fcBody);
    fcReq->setPath("/v1/first-connection");
    fcReq->setMethod(drogon::Post);

    Metrics::instance().incFirstConnRequests();
    const auto fcStart = std::chrono::steady_clock::now();

    firstConnClient_->sendRequest(fcReq,
        [sharedCb, imsi, apn, fcStart](drogon::ReqResult res,
                                        const drogon::HttpResponsePtr& fcResp) {
            auto& cb = *sharedCb;

            if (res != drogon::ReqResult::Ok) {
                spdlog::error(
                    R"({{"imsi":"{}","apn":"{}","result":"first_conn_error","error":"network"}})",
                    imsi, apn);
                Metrics::instance().incFirstConnResponse(-1);
                const double fcLatency = std::chrono::duration<double>(
                    std::chrono::steady_clock::now() - fcStart).count();
                Metrics::instance().observeFirstConnDuration(fcLatency);
                cb(LookupController::errorResponse(
                    drogon::k503ServiceUnavailable, "upstream_error"));
                return;
            }

            const int code = static_cast<int>(fcResp->getStatusCode());
            Metrics::instance().incFirstConnResponse(code);
            const double fcLatency = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - fcStart).count();
            Metrics::instance().observeFirstConnDuration(fcLatency);

            if (code == 200 || code == 201) {
                auto j = fcResp->getJsonObject();
                Json::Value body;
                body["static_ip"] = (*j)["static_ip"];
                auto resp = drogon::HttpResponse::newHttpJsonResponse(body);
                resp->setStatusCode(drogon::k200OK);
                spdlog::info(
                    R"({{"imsi":"{}","apn":"{}","result":"first_conn_allocated","ip":"{}"}})",
                    imsi, apn, (*j)["static_ip"].asString());
                cb(resp);
            } else if (code == 404) {
                spdlog::info(
                    R"({{"imsi":"{}","apn":"{}","result":"first_conn_not_found"}})",
                    imsi, apn);
                cb(LookupController::errorResponse(drogon::k404NotFound, "not_found"));
            } else {
                // 503 (pool exhausted) or unexpected
                spdlog::warn(
                    R"({{"imsi":"{}","apn":"{}","result":"first_conn_rejected","status":{}}})",
                    imsi, apn, code);
                cb(LookupController::errorResponse(
                    drogon::k503ServiceUnavailable, "pool_exhausted"));
            }
        });
}

// ---------------------------------------------------------------------------
// LookupController::lookup — the hot path
// ---------------------------------------------------------------------------
void LookupController::lookup(
        const drogon::HttpRequestPtr& req,
        std::function<void(const drogon::HttpResponsePtr&)>&& callback) {

    // ── 1. JWT ────────────────────────────────────────────────────────────
    if (!verifyJwt(req, callback)) return;

    // ── 2. Parameter extraction & validation ──────────────────────────────
    const std::string imsi      = req->getParameter("imsi");
    const std::string apn       = req->getParameter("apn");
    const std::string imei      = req->getParameter("imei");       // optional
    const std::string useCaseId = req->getParameter("use_case_id"); // optional

    if (imsi.empty()) {
        Metrics::instance().recordLookup("bad_request", 0.0);
        callback(errorResponse(drogon::k400BadRequest, "missing_param", "imsi"));
        return;
    }
    if (apn.empty()) {
        Metrics::instance().recordLookup("bad_request", 0.0);
        callback(errorResponse(drogon::k400BadRequest, "missing_param", "apn"));
        return;
    }
    if (!isValidImsi(imsi)) {
        Metrics::instance().recordLookup("bad_request", 0.0);
        callback(errorResponse(drogon::k400BadRequest, "invalid_param", "imsi"));
        return;
    }

    // ── 3. Start timing + in-flight gauge ─────────────────────────────────
    const auto t0 = std::chrono::steady_clock::now();
    Metrics::instance().incrementInFlight();

    // ── 4. Async DB query (read replica only — see Plan 3) ────────────────
    auto dbClient = drogon::app().getDbClient("aaa_replica");

    // Wrap callback in shared_ptr — both success and error lambdas need it,
    // but std::move can only transfer ownership once.
    auto sharedCb = std::make_shared<std::function<void(const drogon::HttpResponsePtr&)>>(
        std::move(callback));

    dbClient->execSqlAsync(
        HOT_PATH_SQL,

        // ── Success callback ──────────────────────────────────────────────
        [this, sharedCb, imsi, apn, imei, useCaseId, t0](
                const drogon::orm::Result& result) mutable {
            auto& callback = *sharedCb;

            auto& metrics = Metrics::instance();
            metrics.decrementInFlight();

            const double latency = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - t0).count();

            // ── 5. Map result rows to QueryRow vector ─────────────────────
            std::vector<QueryRow> rows;
            rows.reserve(result.size());

            for (const auto& r : result) {
                QueryRow qr;
                qr.sim_status    = r["sim_status"].as<std::string>();
                qr.ip_resolution = r["ip_resolution"].as<std::string>();
                qr.imsi_status   = r["imsi_status"].as<std::string>();

                if (!r["imsi_apn"].isNull())
                    qr.imsi_apn = r["imsi_apn"].as<std::string>();
                if (!r["imsi_static_ip"].isNull())
                    qr.imsi_static_ip = r["imsi_static_ip"].as<std::string>();
                if (!r["iccid_apn"].isNull())
                    qr.iccid_apn = r["iccid_apn"].as<std::string>();
                if (!r["iccid_static_ip"].isNull())
                    qr.iccid_static_ip = r["iccid_static_ip"].as<std::string>();

                rows.push_back(std::move(qr));
            }

            // ── 6. Resolve IP ──────────────────────────────────────────────
            const ResolveResult resolved = Resolver::resolve(rows, apn);

            // ── 7. Build response + emit structured log ────────────────────
            drogon::HttpResponsePtr resp;
            std::string resultLabel;

            switch (resolved.status) {
            case ResolveStatus::Ok: {
                Json::Value body;
                body["static_ip"] = resolved.staticIp.value();
                resp = drogon::HttpResponse::newHttpJsonResponse(body);
                resp->setStatusCode(drogon::k200OK);
                resultLabel = "resolved";
                break;
            }
            case ResolveStatus::Suspended:
                resp = LookupController::errorResponse(
                    drogon::k403Forbidden, "suspended");
                resultLabel = "suspended";
                break;

            case ResolveStatus::NotFound:
                // IMSI not in DB yet. With pre-qualification disabled, fall
                // straight through to first-connection allocation as before.
                // With it enabled, run the imsi_range_configs pre-check on the
                // read replica first — short-circuit "unqualified" IMSIs so
                // they never hit subscriber-profile-api or the primary DB.
                metrics.decrementInFlight();
                if (!Config::instance().prequalifyEnabled) {
                    metrics.recordLookup("not_found", latency);
                    callFirstConnection(imsi, apn, imei, useCaseId, sharedCb);
                    return;
                }
                runPrequalify(imsi, apn, imei, useCaseId, sharedCb, t0);
                return;  // response will be sent by runPrequalify or callFirstConnection

            case ResolveStatus::ApnNotFound:
                resp = LookupController::errorResponse(
                    drogon::k404NotFound, "apn_not_found");
                resultLabel = "apn_not_found";
                break;
            }

            spdlog::info(R"({{"imsi":"{}","apn":"{}","result":"{}","ip_resolution":"{}","latency_ms":{:.2f}}})",
                imsi,
                apn,
                resultLabel,
                rows.empty() ? "n/a" : rows.front().ip_resolution,
                latency * 1000.0);

            metrics.recordLookup(resultLabel, latency);
            callback(resp);
        },

        // ── DB error callback ─────────────────────────────────────────────
        [sharedCb, imsi, t0](
                const drogon::orm::DrogonDbException& ex) mutable {
            auto& callback = *sharedCb;

            auto& metrics = Metrics::instance();
            metrics.decrementInFlight();
            metrics.recordDbError();

            const double latency = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - t0).count();

            spdlog::error(R"({{"imsi":"{}","result":"db_error","error":"{}","latency_ms":{:.2f}}})",
                imsi,
                ex.base().what(),
                latency * 1000.0);

            metrics.recordLookup("db_error", latency);

            auto resp = LookupController::errorResponse(
                drogon::k503ServiceUnavailable, "db_error");
            callback(resp);
        },

        // ── Query parameter ───────────────────────────────────────────────
        imsi   // bound to $1
    );
}

// ---------------------------------------------------------------------------
// LookupController::runPrequalify — read-replica imsi_range_configs check
//
// Fired from the NotFound branch of lookup() when QUALIFY_PRECHECK_ENABLED is
// true. Three terminal states:
//   • 0 rows  → 404 "unqualified" (do NOT call subscriber-profile-api)
//   • ≥1 row  → fall through to callFirstConnection (today's path)
//   • SQL err → fail-open: log + metric, fall through to callFirstConnection
// ---------------------------------------------------------------------------
void LookupController::runPrequalify(
        const std::string& imsi,
        const std::string& apn,
        const std::string& imei,
        const std::string& useCaseId,
        std::shared_ptr<std::function<void(const drogon::HttpResponsePtr&)>> sharedCb,
        std::chrono::steady_clock::time_point t0) {

    auto db = drogon::app().getDbClient("aaa_replica");
    const auto pqStart = std::chrono::steady_clock::now();

    db->execSqlAsync(
        PREQUALIFY_SQL,

        // ── Success callback ──────────────────────────────────────────────
        [this, imsi, apn, imei, useCaseId, sharedCb, t0, pqStart](
                const drogon::orm::Result& result) mutable {
            auto& metrics = Metrics::instance();
            const double pqLatency = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - pqStart).count();
            metrics.observePrequalifyDuration(pqLatency);

            const double total = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - t0).count();

            if (result.empty()) {
                // No range covers this IMSI — short-circuit. The subscriber-
                // profile-api never sees this request.
                metrics.incUnqualified();
                metrics.recordLookup("unqualified", total);
                spdlog::info(
                    R"({{"imsi":"{}","apn":"{}","result":"unqualified","latency_ms":{:.2f}}})",
                    imsi, apn, total * 1000.0);
                auto& callback = *sharedCb;
                callback(LookupController::errorResponse(
                    drogon::k404NotFound, "unqualified"));
                return;
            }

            // Range exists — preserve today's "not_found" semantics for the
            // HOT_PATH miss and hand off to first-connection.
            metrics.recordLookup("not_found", total);
            callFirstConnection(imsi, apn, imei, useCaseId, sharedCb);
        },

        // ── Error callback (fail-open) ────────────────────────────────────
        [this, imsi, apn, imei, useCaseId, sharedCb, t0, pqStart](
                const drogon::orm::DrogonDbException& ex) mutable {
            auto& metrics = Metrics::instance();
            const double pqLatency = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - pqStart).count();
            metrics.observePrequalifyDuration(pqLatency);
            metrics.incPrequalifyError();

            spdlog::warn(
                R"({{"imsi":"{}","result":"prequalify_error","error":"{}"}})",
                imsi, ex.base().what());

            const double total = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - t0).count();
            metrics.recordLookup("not_found", total);
            callFirstConnection(imsi, apn, imei, useCaseId, sharedCb);
        },

        // ── Query parameter ───────────────────────────────────────────────
        imsi   // bound to $1
    );
}
