#pragma once

// ---------------------------------------------------------------------------
// LookupController — handles GET /v1/lookup?imsi=&apn=
//
// This is the ONLY endpoint that aaa-radius-server calls (Stage 1).
// The controller is fully async: the DB query callback resolves the HTTP
// response without blocking any Drogon event loop thread.
//
// Hot path (happy path):
//   1. Validate params (imsi 15 digits, apn present)
//   2. Verify JWT Bearer token
//   3. Fire async SQL query against read replica
//   4. Apply Resolver::resolve() on the result set
//   5. Return 200/403/404 JSON + emit log line + record Prometheus metrics
// ---------------------------------------------------------------------------

#include <drogon/HttpController.h>

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
    // JWT header verification (returns false and sends 401 if invalid).
    bool verifyJwt(const drogon::HttpRequestPtr& req,
                   std::function<void(const drogon::HttpResponsePtr&)>& callback);

    // Convenience: JSON error response.
    static drogon::HttpResponsePtr errorResponse(drogon::HttpStatusCode code,
                                                 const std::string& error,
                                                 const std::string& param = "");
};
