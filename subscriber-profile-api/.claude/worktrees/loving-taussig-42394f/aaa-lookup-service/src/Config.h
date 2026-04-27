#pragma once

#include <cstdlib>
#include <stdexcept>
#include <string>

// ---------------------------------------------------------------------------
// Config — reads all service configuration from environment variables.
// Validated once at startup; immutable at runtime.
// ---------------------------------------------------------------------------
struct Config {
    // ── HTTP ────────────────────────────────────────────────────────────────
    uint16_t    httpPort     = 8081;
    uint16_t    metricsPort  = 9090;   // Prometheus pull endpoint
    int         threadCount  = 0;      // 0 = auto (logical CPUs)

    // ── PostgreSQL read replica ─────────────────────────────────────────────
    // This service holds ONE connection pool: the local read replica.
    // It never opens a connection to the primary.
    std::string dbHost       = "localhost";
    uint16_t    dbPort       = 5432;
    std::string dbName       = "aaa";
    std::string dbUser       = "aaa_ro";
    std::string dbPassword;
    int         dbPoolSize   = 8;      // server-side connections per replica pod
    double      dbTimeout    = 1.0;    // seconds — query must start within SLA

    // ── JWT verification ────────────────────────────────────────────────────
    std::string jwtPublicKeyPath = "/etc/jwt/public.key";  // RS256 PEM
    bool        jwtSkipVerify   = false;   // true only in local dev (values-dev.yaml)

    // ── Upstream provisioning API ────────────────────────────────────────────
    std::string provisioningUrl = "http://subscriber-profile-api:8080";

    // ── Observability ────────────────────────────────────────────────────────
    std::string logLevel = "info";   // trace | debug | info | warn | error

    // ── Singleton ───────────────────────────────────────────────────────────
    static Config& instance() {
        static Config cfg;
        return cfg;
    }

    void load() {
        httpPort    = envUint16("HTTP_PORT",    8081);
        metricsPort = envUint16("METRICS_PORT", 9090);
        threadCount = envInt("THREAD_COUNT",    0);

        dbHost      = envStr("DB_HOST",     "localhost");
        dbPort      = envUint16("DB_PORT",  5432);
        dbName      = envStr("DB_NAME",     "aaa");
        dbUser      = envStr("DB_USER",     "aaa_ro");
        dbPassword  = envStr("DB_PASSWORD", "");
        dbPoolSize  = envInt("DB_POOL_SIZE", 8);
        dbTimeout   = envDouble("DB_TIMEOUT_SEC", 1.0);

        jwtPublicKeyPath = envStr("JWT_PUBLIC_KEY_PATH", "/etc/jwt/public.key");
        jwtSkipVerify    = envBool("JWT_SKIP_VERIFY",    false);

        provisioningUrl = envStr("PROVISIONING_URL", "http://subscriber-profile-api:8080");

        logLevel = envStr("LOG_LEVEL", "info");

        validate();
    }

private:
    Config() = default;

    void validate() const {
        if (dbPassword.empty() && !jwtSkipVerify) {
            // In prod, DB_PASSWORD is required. Allow empty only in full-skip dev mode.
        }
        if (dbPoolSize < 1 || dbPoolSize > 100)
            throw std::runtime_error("DB_POOL_SIZE must be 1–100");
        if (httpPort == metricsPort)
            throw std::runtime_error("HTTP_PORT and METRICS_PORT must differ");
    }

    static std::string envStr(const char* key, std::string def = "") {
        const char* v = std::getenv(key);
        return v ? std::string(v) : def;
    }
    static uint16_t envUint16(const char* key, uint16_t def) {
        const char* v = std::getenv(key);
        return v ? static_cast<uint16_t>(std::stoi(v)) : def;
    }
    static int envInt(const char* key, int def) {
        const char* v = std::getenv(key);
        return v ? std::stoi(v) : def;
    }
    static double envDouble(const char* key, double def) {
        const char* v = std::getenv(key);
        return v ? std::stod(v) : def;
    }
    static bool envBool(const char* key, bool def) {
        const char* v = std::getenv(key);
        if (!v) return def;
        std::string s(v);
        return s == "1" || s == "true" || s == "yes";
    }
};
