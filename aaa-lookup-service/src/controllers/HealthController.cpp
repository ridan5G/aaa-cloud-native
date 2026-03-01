#include "HealthController.h"

#include <drogon/drogon.h>
#include <spdlog/spdlog.h>

// ---------------------------------------------------------------------------
// GET /health — liveness probe (fast, no I/O)
// ---------------------------------------------------------------------------
void HealthController::liveness(
        const drogon::HttpRequestPtr& /*req*/,
        std::function<void(const drogon::HttpResponsePtr&)>&& callback) {

    Json::Value body;
    body["status"] = "ok";
    auto resp = drogon::HttpResponse::newHttpJsonResponse(body);
    resp->setStatusCode(drogon::k200OK);
    callback(resp);
}

// ---------------------------------------------------------------------------
// GET /health/db — readiness probe (async SELECT 1 on the read replica)
//
// A 503 here causes Kubernetes to remove this pod from the Service endpoint
// slice — FreeRADIUS will not receive traffic until the DB reconnects.
// ---------------------------------------------------------------------------
void HealthController::readiness(
        const drogon::HttpRequestPtr& /*req*/,
        std::function<void(const drogon::HttpResponsePtr&)>&& callback) {

    auto dbClient = drogon::app().getDbClient("aaa_replica");

    dbClient->execSqlAsync(
        "SELECT 1",

        // ── DB reachable ───────────────────────────────────────────────────
        [callback](const drogon::orm::Result& /*r*/) mutable {
            Json::Value body;
            body["status"]  = "ok";
            body["replica"] = "connected";
            auto resp = drogon::HttpResponse::newHttpJsonResponse(body);
            resp->setStatusCode(drogon::k200OK);
            callback(resp);
        },

        // ── DB unreachable ─────────────────────────────────────────────────
        [callback](const drogon::orm::DrogonDbException& ex) mutable {
            spdlog::error("Health/DB check failed: {}", ex.base().what());
            Json::Value body;
            body["status"]  = "error";
            body["replica"] = "unreachable";
            body["detail"]  = ex.base().what();
            auto resp = drogon::HttpResponse::newHttpJsonResponse(body);
            resp->setStatusCode(drogon::k503ServiceUnavailable);
            callback(resp);
        }
    );
}
