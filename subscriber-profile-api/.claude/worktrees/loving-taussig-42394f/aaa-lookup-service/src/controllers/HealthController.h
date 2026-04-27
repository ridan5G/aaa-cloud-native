#pragma once

// ---------------------------------------------------------------------------
// HealthController — liveness and readiness probes.
//
// GET /health     → 200 {"status":"ok"}
//                   Kubernetes liveness probe.  Fails only if the process
//                   itself is broken (will trigger a pod restart).
//
// GET /health/db  → 200 {"status":"ok","replica":"connected"}
//                   Kubernetes readiness probe.  Fails if the read replica
//                   is unreachable (removes pod from Service endpoints so
//                   aaa-radius-server stops sending traffic to a DB-less pod).
// ---------------------------------------------------------------------------

#include <drogon/HttpController.h>

class HealthController
    : public drogon::HttpController<HealthController> {
public:
    METHOD_LIST_BEGIN
    ADD_METHOD_TO(HealthController::liveness,  "/health",    drogon::Get);
    ADD_METHOD_TO(HealthController::readiness, "/health/db", drogon::Get);
    METHOD_LIST_END

    void liveness (const drogon::HttpRequestPtr& req,
                   std::function<void(const drogon::HttpResponsePtr&)>&& callback);

    void readiness(const drogon::HttpRequestPtr& req,
                   std::function<void(const drogon::HttpResponsePtr&)>&& callback);
};
