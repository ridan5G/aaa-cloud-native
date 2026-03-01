#include "Metrics.h"

#include <prometheus/exposer.h>
#include <stdexcept>

// ---------------------------------------------------------------------------
// Metrics::init — build all metric families and start the pull endpoint.
// Must be called once before drogon::app().run().
// ---------------------------------------------------------------------------
void Metrics::init(uint16_t metricsPort) {
    registry_ = std::make_shared<prometheus::Registry>();

    // ── aaa_lookup_requests_total ──────────────────────────────────────────
    lookupResultFamily_ = &prometheus::BuildCounter()
        .Name("aaa_lookup_requests_total")
        .Help("Total AAA lookup requests by outcome")
        .Register(*registry_);

    cntResolved_    = &lookupResultFamily_->Add({{"result", "resolved"}});
    cntNotFound_    = &lookupResultFamily_->Add({{"result", "not_found"}});
    cntSuspended_   = &lookupResultFamily_->Add({{"result", "suspended"}});
    cntApnNotFound_ = &lookupResultFamily_->Add({{"result", "apn_not_found"}});
    cntBadRequest_  = &lookupResultFamily_->Add({{"result", "bad_request"}});
    cntDbError_     = &lookupResultFamily_->Add({{"result", "db_error"}});

    // ── aaa_lookup_duration_seconds ────────────────────────────────────────
    // Buckets span 1ms → 500ms; tightly clustered around the 15ms SLA.
    lookupDurationFamily_ = &prometheus::BuildHistogram()
        .Name("aaa_lookup_duration_seconds")
        .Help("End-to-end latency of GET /lookup requests")
        .Register(*registry_);

    histDuration_ = &lookupDurationFamily_->Add(
        {},
        prometheus::Histogram::BucketBoundaries{
            0.001, 0.003, 0.005, 0.008,
            0.010, 0.015, 0.025, 0.050,
            0.100, 0.500
        });

    // ── aaa_in_flight_requests ─────────────────────────────────────────────
    inFlightFamily_ = &prometheus::BuildGauge()
        .Name("aaa_in_flight_requests")
        .Help("Number of GET /lookup requests currently being processed")
        .Register(*registry_);

    gaugeInFlight_ = &inFlightFamily_->Add({});

    // ── aaa_db_errors_total ────────────────────────────────────────────────
    dbErrorFamily_ = &prometheus::BuildCounter()
        .Name("aaa_db_errors_total")
        .Help("PostgreSQL read replica errors (connection failures, timeouts)")
        .Register(*registry_);

    cntDbErrors_ = &dbErrorFamily_->Add({});

    // ── Prometheus pull endpoint on metricsPort ────────────────────────────
    // Runs its own CivetWeb HTTP server — separate from the Drogon API port.
    auto* exposer = new prometheus::Exposer{
        "0.0.0.0:" + std::to_string(metricsPort)
    };
    exposer->RegisterCollectable(registry_);
    // Exposer owns its thread; we intentionally leak the pointer so it lives
    // for the whole process lifetime.
}

// ---------------------------------------------------------------------------
void Metrics::recordLookup(const std::string& result, double latencySeconds) {
    histDuration_->Observe(latencySeconds);

    if      (result == "resolved")      cntResolved_->Increment();
    else if (result == "not_found")     cntNotFound_->Increment();
    else if (result == "suspended")     cntSuspended_->Increment();
    else if (result == "apn_not_found") cntApnNotFound_->Increment();
    else if (result == "bad_request")   cntBadRequest_->Increment();
    else if (result == "db_error")      cntDbError_->Increment();
}

void Metrics::incrementInFlight() { gaugeInFlight_->Increment(); }
void Metrics::decrementInFlight() { gaugeInFlight_->Decrement(); }
void Metrics::recordDbError()     { cntDbErrors_->Increment(); }
