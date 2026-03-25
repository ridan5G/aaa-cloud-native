#pragma once

// ---------------------------------------------------------------------------
// LookupController — handles GET /v1/lookup?imsi=&apn=[&imei=][&use_case_id=]
//
// This is the ONLY endpoint that aaa-radius-server calls.
// The controller is fully async: the DB query callback resolves the HTTP
// response without blocking any Drogon event loop thread.
//
// Full resolution path:
//   1. Validate params (imsi 15 digits, apn present)
//   2. Verify JWT Bearer token
//   3. Fire async SQL query against read replica
//   4. Apply Resolver::resolve() on the result set
//   5a. Hit (resolved/suspended/apn_not_found) → return 200/403/404 immediately
//   5b. Not found → POST /v1/first-connection to subscriber-profile-api (async)
//       200/201 → return 200 with static_ip
//       404     → return 404 (no range config)
//       503     → return 503 (pool exhausted)
//   6. Emit log line + record Prometheus metrics
// ---------------------------------------------------------------------------

#include <drogon/HttpController.h>
#include <drogon/HttpClient.h>

#include <functional>
#include <memory>
#include <string>

class LookupController
    : public drogon::HttpController<LookupController> {
public:
    METHOD_LIST_BEGIN
    // v1 prefix matches the Ingress rewrite rule; also accept bare /lookup
    ADD_METHOD_TO(LookupController::lookup, "/v1/lookup", drogon::Get);
    ADD_METHOD_TO(LookupController::lookup, "/lookup",    drogon::Get);
    METHOD_LIST_END

    void lookup(const drogon::HttpRequestPtr& req,
                std::function<void(const drogon::HttpResponsePtr&)>&& callback);

private:
    // Drogon async HTTP client for POST /v1/first-connection.
    // Initialized lazily on first use (thread-safe via Drogon event loop).
    drogon::HttpClientPtr firstConnClient_;

    // JWT header verification (returns false and sends 401 if invalid).
    bool verifyJwt(const drogon::HttpRequestPtr& req,
                   std::function<void(const drogon::HttpResponsePtr&)>& callback);

    // Convenience: JSON error response.
    static drogon::HttpResponsePtr errorResponse(drogon::HttpStatusCode code,
                                                 const std::string& error,
                                                 const std::string& param = "");

    // Async POST to subscriber-profile-api /v1/first-connection.
    // Calls sharedCb with the appropriate HTTP response when done.
    void callFirstConnection(
        const std::string& imsi,
        const std::string& apn,
        const std::string& imei,
        const std::string& useCaseId,
        std::shared_ptr<std::function<void(const drogon::HttpResponsePtr&)>> sharedCb);
};
