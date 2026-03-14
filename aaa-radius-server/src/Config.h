#pragma once

#include <cstdint>
#include <cstdlib>
#include <stdexcept>
#include <string>

// ---------------------------------------------------------------------------
// Config — singleton loaded from environment variables
//
// Env vars:
//   RADIUS_PORT        UDP port to listen on               (default: 1812)
//   RADIUS_SECRET      Shared secret with NAS clients      (required)
//   LOOKUP_URL         aaa-lookup-service base URL         (default: http://aaa-lookup-service:8081)
//   PROVISIONING_URL   subscriber-profile-api base URL     (default: http://subscriber-profile-api:8080)
//   WORKER_THREADS     Thread pool size for request work   (default: 8)
//   LOG_LEVEL          trace|debug|info|warn|error         (default: info)
// ---------------------------------------------------------------------------
struct Config {
    static Config& instance() {
        static Config cfg;
        return cfg;
    }

    uint16_t    radiusPort      = 1812;
    std::string radiusSecret    = "testing123";
    std::string lookupUrl       = "http://aaa-lookup-service:8081";
    std::string provisioningUrl = "http://subscriber-profile-api:8080";
    int         workerThreads   = 8;
    std::string logLevel        = "info";

    void load() {
        if (auto* v = getenv("RADIUS_PORT"))        radiusPort      = static_cast<uint16_t>(std::stoi(v));
        if (auto* v = getenv("RADIUS_SECRET"))      radiusSecret    = v;
        if (auto* v = getenv("LOOKUP_URL"))         lookupUrl       = v;
        if (auto* v = getenv("PROVISIONING_URL"))   provisioningUrl = v;
        if (auto* v = getenv("WORKER_THREADS"))     workerThreads   = std::stoi(v);
        if (auto* v = getenv("LOG_LEVEL"))          logLevel        = v;

        if (radiusSecret.empty())
            throw std::runtime_error("RADIUS_SECRET must not be empty");
        if (workerThreads < 1 || workerThreads > 256)
            throw std::runtime_error("WORKER_THREADS must be between 1 and 256");
    }

private:
    Config() = default;
};
