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

    // ── first_connection_requests_total ───────────────────────────────────
    auto& fcReqFamily = prometheus::BuildCounter()
        .Name("first_connection_requests_total")
        .Help("Total POST /v1/first-connection requests sent by the lookup service")
        .Register(*registry_);
    firstConnRequests_ = &fcReqFamily.Add({});

    auto& fcRespFamily = prometheus::BuildCounter()
        .Name("first_connection_responses_total")
        .Help("first-connection responses by HTTP status code")
        .Register(*registry_);
    firstConnResp200_   = &fcRespFamily.Add({{"status", "200"}});
    firstConnResp404_   = &fcRespFamily.Add({{"status", "404"}});
    firstConnResp503_   = &fcRespFamily.Add({{"status", "503"}});
    firstConnRespError_ = &fcRespFamily.Add({{"status", "error"}});

    // ── first_connection_duration_seconds ─────────────────────────────────────
    // Measures only the HTTP round-trip from lookup → subscriber-profile-api.
    // Buckets span 5 ms → 2.5 s; values above 500 ms will push RADIUS p99 past SLA.
    firstConnDurationFamily_ = &prometheus::BuildHistogram()
        .Name("first_connection_duration_seconds")
        .Help("Time the lookup service waits for POST /v1/first-connection response")
        .Register(*registry_);

    histFirstConnDuration_ = &firstConnDurationFamily_->Add(
        {},
        prometheus::Histogram::BucketBoundaries{
            0.005, 0.010, 0.025, 0.050, 0.100,
            0.250, 0.500, 1.0, 2.5
        });

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

void Metrics::incFirstConnRequests() {
    if (firstConnRequests_) firstConnRequests_->Increment();
}

void Metrics::incFirstConnResponse(int statusCode) {
    if      (statusCode == 200 || statusCode == 201) { if (firstConnResp200_)   firstConnResp200_->Increment(); }
    else if (statusCode == 404)                       { if (firstConnResp404_)   firstConnResp404_->Increment(); }
    else if (statusCode == 503)                       { if (firstConnResp503_)   firstConnResp503_->Increment(); }
    else                                              { if (firstConnRespError_) firstConnRespError_->Increment(); }
}

void Metrics::observeFirstConnDuration(double seconds) {
    if (histFirstConnDuration_) histFirstConnDuration_->Observe(seconds);
}
