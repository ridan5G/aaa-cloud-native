#pragma once

#include <memory>
#include <string>
#include <prometheus/counter.h>
#include <prometheus/exposer.h>

// Forward declarations — avoid pulling prometheus headers into every TU
namespace prometheus {
class Registry;
class Exposer;
class Counter;
}  // namespace prometheus

// ---------------------------------------------------------------------------
// Metrics — process-wide Prometheus counters, exposed via HTTP /metrics
//
// Metrics tracked:
//   RADIUS layer:
//     radius_access_requests_total          — valid Access-Request packets processed
//     radius_packets_dropped_total          — malformed / non-AccessRequest packets
//     radius_responses_total{result}        — accept | reject
//
//   Lookup layer (Stage 1 — GET /lookup):
//     lookup_requests_total                 — HTTP requests sent
//     lookup_responses_total{status}        — 200 | 403 | 404 | error
//
//   First-connection layer (Stage 2 — POST /v1/first-connection):
//     first_connection_requests_total       — HTTP requests sent
//     first_connection_responses_total{status} — 200 | 404 | 503 | error
//
// Thread-safety: prometheus-cpp Counter::Increment() is lock-free/atomic.
// Call init() once from main before spawning worker threads.
// ---------------------------------------------------------------------------
class Metrics {
public:
    static Metrics& instance() {
        static Metrics m;
        return m;
    }

    // Starts the CivetWeb-based HTTP server serving GET /metrics.
    // bindAddress examples: "0.0.0.0:9090", "9090"
    void init(const std::string& bindAddress);

    // ── RADIUS layer ─────────────────────────────────────────────────────────
    void incAccessRequests()  { if (accessRequests_)  accessRequests_->Increment(); }
    void incPacketsDropped()  { if (packetsDropped_)  packetsDropped_->Increment(); }
    void incResponseAccepts() { if (responseAccepts_) responseAccepts_->Increment(); }
    void incResponseRejects() { if (responseRejects_) responseRejects_->Increment(); }

    // ── Lookup layer ──────────────────────────────────────────────────────────
    void incLookupRequests() { if (lookupRequests_) lookupRequests_->Increment(); }
    // statusCode: 200 | 403 | 404 | anything-else (incl. -1 for curl error) → "error"
    void incLookupResponse(int statusCode);

    // ── First-connection layer ────────────────────────────────────────────────
    void incFirstConnRequests() { if (firstConnRequests_) firstConnRequests_->Increment(); }
    // statusCode: 200 | 404 | 503 | anything-else → "error"
    void incFirstConnResponse(int statusCode);

private:
    Metrics() = default;

    std::shared_ptr<prometheus::Registry> registry_;
    std::unique_ptr<prometheus::Exposer>  exposer_;

    // RADIUS
    prometheus::Counter* accessRequests_{};
    prometheus::Counter* packetsDropped_{};
    prometheus::Counter* responseAccepts_{};
    prometheus::Counter* responseRejects_{};

    // Lookup
    prometheus::Counter* lookupRequests_{};
    prometheus::Counter* lookupResp200_{};
    prometheus::Counter* lookupResp403_{};
    prometheus::Counter* lookupResp404_{};
    prometheus::Counter* lookupRespError_{};

    // First-connection
    prometheus::Counter* firstConnRequests_{};
    prometheus::Counter* firstConnResp200_{};
    prometheus::Counter* firstConnResp404_{};
    prometheus::Counter* firstConnResp503_{};
    prometheus::Counter* firstConnRespError_{};
};
