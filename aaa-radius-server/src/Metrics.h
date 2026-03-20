#pragma once

#include <memory>
#include <string>
#include <prometheus/counter.h>
#include <prometheus/exposer.h>
#include <prometheus/family.h>
#include <prometheus/histogram.h>
#include <prometheus/registry.h>

// ---------------------------------------------------------------------------
// Metrics — process-wide Prometheus counters + histogram, exposed via HTTP /metrics
//
// Metrics tracked:
//   RADIUS layer:
//     radius_access_requests_total              — valid Access-Request packets processed
//     radius_packets_dropped_total              — malformed / non-AccessRequest packets
//     radius_responses_total{result}            — accept | reject
//     radius_requests_total{result,stage}       — accept|reject × stage1|stage2
//     radius_request_duration_ms (histogram)    — end-to-end RADIUS request latency
//     radius_upstream_errors_total{upstream,status_code}
//                                               — unexpected errors from lookup/first-connection
//
//   Lookup layer (Stage 1 — GET /lookup):
//     lookup_requests_total                     — HTTP requests sent
//     lookup_responses_total{status}            — 200 | 403 | 404 | error
//
//   First-connection layer (Stage 2 — POST /v1/first-connection):
//     first_connection_requests_total           — HTTP requests sent
//     first_connection_responses_total{status}  — 200 | 404 | 503 | error
//
// Thread-safety: prometheus-cpp Counter::Increment() and Histogram::Observe()
// are lock-free/atomic. Call init() once from main before spawning workers.
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

    // result: "accept" | "reject"   stage: "1" (lookup hit) | "2" (first-connection used)
    void incRadiusRequest(const std::string& result, const std::string& stage);

    // Record end-to-end RADIUS request duration in milliseconds.
    void recordRequestDuration(double ms) { if (durationHist_) durationHist_->Observe(ms); }

    // upstream: "lookup" | "first_connection"   statusCode: HTTP status as string or "curl_error"
    void incUpstreamError(const std::string& upstream, const std::string& statusCode);

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

    // radius_requests_total{result, stage} — pre-created label combinations
    prometheus::Counter* radiusReqAcceptStage1_{};
    prometheus::Counter* radiusReqAcceptStage2_{};
    prometheus::Counter* radiusReqRejectStage1_{};
    prometheus::Counter* radiusReqRejectStage2_{};

    // radius_request_duration_ms histogram
    prometheus::Histogram* durationHist_{};

    // radius_upstream_errors_total — Family kept for dynamic label creation
    prometheus::Family<prometheus::Counter>* upstreamErrorsFamily_{};

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
