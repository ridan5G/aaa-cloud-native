#pragma once

// ---------------------------------------------------------------------------
// Metrics — Prometheus instrumentation for aaa-lookup-service.
//
// Exposed at GET :<metricsPort>/metrics in text/plain Prometheus format.
// Scraped by kube-prometheus-stack every 10 seconds (ServiceMonitor).
//
// All metric families are defined here.  The singleton is initialised once
// in main() and then read/written by LookupController on every request.
// ---------------------------------------------------------------------------

#include <memory>
#include <string>

#include <prometheus/counter.h>
#include <prometheus/gauge.h>
#include <prometheus/histogram.h>
#include <prometheus/registry.h>

class Metrics {
public:
    static Metrics& instance() {
        static Metrics m;
        return m;
    }

    // Call once from main() before starting the HTTP server.
    void init(uint16_t metricsPort);

    // ── Per-request instrumentation ─────────────────────────────────────────

    /// Record one completed lookup request.
    /// @param result   One of: "resolved" | "not_found" | "suspended"
    ///                         "apn_not_found" | "bad_request" | "db_error"
    /// @param latencySeconds  wall-clock duration of the full request
    void recordLookup(const std::string& result, double latencySeconds);

    /// Increment / decrement in-flight counter (RAII-friendly).
    void incrementInFlight();
    void decrementInFlight();

    /// Record a DB pool error (connection failure, timeout).
    void recordDbError();

private:
    Metrics() = default;

    std::shared_ptr<prometheus::Registry> registry_;

    // aaa_lookup_requests_total{result="..."} counter
    prometheus::Family<prometheus::Counter>* lookupResultFamily_{nullptr};
    prometheus::Counter* cntResolved_{nullptr};
    prometheus::Counter* cntNotFound_{nullptr};
    prometheus::Counter* cntSuspended_{nullptr};
    prometheus::Counter* cntApnNotFound_{nullptr};
    prometheus::Counter* cntBadRequest_{nullptr};
    prometheus::Counter* cntDbError_{nullptr};

    // aaa_lookup_duration_seconds histogram
    // Buckets tuned to the <15ms p99 SLA:
    // 0.001 0.003 0.005 0.008 0.010 0.015 0.025 0.050 0.100 0.500
    prometheus::Family<prometheus::Histogram>* lookupDurationFamily_{nullptr};
    prometheus::Histogram* histDuration_{nullptr};

    // aaa_in_flight_requests gauge
    prometheus::Family<prometheus::Gauge>* inFlightFamily_{nullptr};
    prometheus::Gauge* gaugeInFlight_{nullptr};

    // aaa_db_errors_total counter
    prometheus::Family<prometheus::Counter>* dbErrorFamily_{nullptr};
    prometheus::Counter* cntDbErrors_{nullptr};
};
