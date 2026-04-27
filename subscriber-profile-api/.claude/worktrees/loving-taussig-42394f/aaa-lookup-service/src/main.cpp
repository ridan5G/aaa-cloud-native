//
// aaa-lookup-service — AAA hot-path IMSI lookup (Plan 3)
//
// Architecture:
//   • Single endpoint: GET /v1/lookup?imsi=&apn=
//   • Strictly read-only — one connection pool to the local PostgreSQL read replica
//   • First-connection IMSIs return 404; aaa-radius-server falls through to
//     subscriber-profile-api (Plan 4) for allocation — not our concern
//   • SLA: <15ms p99 end-to-end
//
// Ports:
//   8081 — HTTP API (Drogon)
//   9090 — Prometheus metrics (prometheus-cpp Exposer / CivetWeb)
//

#include <drogon/drogon.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>

#include <csignal>
#include <cstdlib>
#include <exception>
#include <string>
#include <thread>

#include "Config.h"
#include "Metrics.h"

// ---------------------------------------------------------------------------
// Signal handler — graceful shutdown on SIGTERM / SIGINT (Kubernetes sends
// SIGTERM before SIGKILL; we have the pod's terminationGracePeriodSeconds
// to drain in-flight requests).
// ---------------------------------------------------------------------------
static void handleSignal(int sig) {
    spdlog::info("Received signal {} — initiating graceful shutdown", sig);
    drogon::app().quit();
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
int main() {
    // ── 1. Load configuration ─────────────────────────────────────────────
    try {
        Config::instance().load();
    } catch (const std::exception& ex) {
        spdlog::critical("Configuration error: {}", ex.what());
        return 1;
    }
    const auto& cfg = Config::instance();

    // ── 2. Configure structured logger ───────────────────────────────────
    auto console = spdlog::stdout_color_mt("aaa-lookup");
    spdlog::set_default_logger(console);

    if      (cfg.logLevel == "trace") spdlog::set_level(spdlog::level::trace);
    else if (cfg.logLevel == "debug") spdlog::set_level(spdlog::level::debug);
    else if (cfg.logLevel == "warn")  spdlog::set_level(spdlog::level::warn);
    else if (cfg.logLevel == "error") spdlog::set_level(spdlog::level::err);
    else                              spdlog::set_level(spdlog::level::info);

    spdlog::info("aaa-lookup-service starting — HTTP:{} Metrics:{} DBPool:{}",
        cfg.httpPort, cfg.metricsPort, cfg.dbPoolSize);

    if (cfg.jwtSkipVerify)
        spdlog::warn("JWT_SKIP_VERIFY=true — DEVELOPMENT MODE ONLY");

    // ── 3. Start Prometheus metrics endpoint ─────────────────────────────
    // Runs in its own thread inside prometheus-cpp's CivetWeb server.
    try {
        Metrics::instance().init(cfg.metricsPort);
        spdlog::info("Prometheus metrics endpoint on :{}/metrics", cfg.metricsPort);
    } catch (const std::exception& ex) {
        spdlog::critical("Failed to start metrics endpoint: {}", ex.what());
        return 1;
    }

    // ── 4. Register signal handlers ───────────────────────────────────────
    std::signal(SIGTERM, handleSignal);
    std::signal(SIGINT,  handleSignal);

    // ── 5. Configure Drogon ───────────────────────────────────────────────
    auto& app = drogon::app();

    // Disable Drogon's built-in log (we use spdlog instead).
    app.setLogLevel(trantor::Logger::kWarn);

    // HTTP listener
    app.addListener("0.0.0.0", cfg.httpPort);

    // Thread pool: 0 = auto-detect (logical CPU count).
    // Each thread handles requests asynchronously via the event loop.
    const int threads = (cfg.threadCount > 0)
        ? cfg.threadCount
        : static_cast<int>(std::thread::hardware_concurrency());
    app.setThreadNum(threads);
    spdlog::info("Drogon event-loop threads: {}", threads);

    // ── 6. PostgreSQL read replica connection pool ────────────────────────
    // This is the ONLY DB connection this service holds.
    // It connects to the LOCAL read replica — never to the primary.
app.createDbClient(
    "postgresql",        // driver
    cfg.dbHost,          // host
    cfg.dbPort,          // port
    cfg.dbName,          // database
    cfg.dbUser,          // user
    cfg.dbPassword,      // password
    cfg.dbPoolSize,      // connectionNum
    "",                  // filename (unused for postgres)
    "aaa_replica",       // name (client name — used in getDbClient())
    false,               // isFast
    "utf8",              // characterSet
    cfg.dbTimeout,       // timeout (seconds)
    false                // autoBatch
);
    spdlog::info("DB read replica: {}@{}:{}/{} pool={}",
        cfg.dbUser, cfg.dbHost, cfg.dbPort, cfg.dbName, cfg.dbPoolSize);

    // ── 7. Controllers are auto-registered via METHOD_LIST macros ─────────
    // LookupController  → GET /v1/lookup, GET /lookup
    // HealthController  → GET /health, GET /health/db

    // ── 8. Run (blocks until drogon::app().quit() is called) ──────────────
    spdlog::info("Ready to accept requests on port {}", cfg.httpPort);
    app.run();

    spdlog::info("aaa-lookup-service stopped cleanly");
    return 0;
}
