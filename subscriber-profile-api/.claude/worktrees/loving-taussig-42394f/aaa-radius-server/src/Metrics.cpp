#include "Metrics.h"

#include <prometheus/counter.h>
#include <prometheus/exposer.h>
#include <prometheus/histogram.h>
#include <prometheus/registry.h>
#include <spdlog/spdlog.h>

void Metrics::init(const std::string& bindAddress) {
    registry_ = std::make_shared<prometheus::Registry>();

    // ── RADIUS layer ───────────────────────────────────────────────────────────
    auto& radReqFam = prometheus::BuildCounter()
        .Name("radius_access_requests_total")
        .Help("Total RADIUS Access-Request packets received and dispatched to workers")
        .Register(*registry_);
    accessRequests_ = &radReqFam.Add({});

    auto& droppedFam = prometheus::BuildCounter()
        .Name("radius_packets_dropped_total")
        .Help("Malformed or non-AccessRequest RADIUS packets silently dropped")
        .Register(*registry_);
    packetsDropped_ = &droppedFam.Add({});

    auto& radRespFam = prometheus::BuildCounter()
        .Name("radius_responses_total")
        .Help("RADIUS responses sent, labeled by result (accept|reject)")
        .Register(*registry_);
    responseAccepts_ = &radRespFam.Add({{"result", "accept"}});
    responseRejects_ = &radRespFam.Add({{"result", "reject"}});

    // radius_requests_total{result}
    auto& radReqLabeledFam = prometheus::BuildCounter()
        .Name("radius_requests_total")
        .Help("RADIUS requests completed, labeled by result (accept|reject)")
        .Register(*registry_);
    radiusReqAccept_ = &radReqLabeledFam.Add({{"result", "accept"}});
    radiusReqReject_ = &radReqLabeledFam.Add({{"result", "reject"}});

    // radius_request_duration_ms histogram — end-to-end RADIUS latency
    auto& durationFam = prometheus::BuildHistogram()
        .Name("radius_request_duration_ms")
        .Help("End-to-end RADIUS Access-Request handling latency in milliseconds")
        .Register(*registry_);
    durationHist_ = &durationFam.Add({},
        prometheus::Histogram::BucketBoundaries{1, 5, 10, 25, 50, 100, 250, 500, 1000});

    // radius_upstream_errors_total{upstream, status_code} — Family stored for dynamic labels
    upstreamErrorsFamily_ = &prometheus::BuildCounter()
        .Name("radius_upstream_errors_total")
        .Help("Unexpected errors from upstream HTTP services (non-business HTTP errors or curl failures)")
        .Register(*registry_);

    // ── Lookup metrics ─────────────────────────────────────────────────────────
    auto& lookReqFam = prometheus::BuildCounter()
        .Name("lookup_requests_total")
        .Help("Total HTTP GET requests sent to the lookup service")
        .Register(*registry_);
    lookupRequests_ = &lookReqFam.Add({});

    auto& lookRespFam = prometheus::BuildCounter()
        .Name("lookup_responses_total")
        .Help("Lookup service HTTP responses, labeled by status code")
        .Register(*registry_);
    lookupResp200_   = &lookRespFam.Add({{"status", "200"}});
    lookupResp403_   = &lookRespFam.Add({{"status", "403"}});
    lookupResp404_   = &lookRespFam.Add({{"status", "404"}});
    lookupResp503_   = &lookRespFam.Add({{"status", "503"}});
    lookupRespError_ = &lookRespFam.Add({{"status", "error"}});

    // ── Start HTTP exposition server ───────────────────────────────────────────
    exposer_ = std::make_unique<prometheus::Exposer>(bindAddress);
    exposer_->RegisterCollectable(registry_);

    spdlog::info("Prometheus metrics listening on http://{}/metrics", bindAddress);
}

void Metrics::incLookupResponse(int statusCode) {
    switch (statusCode) {
        case 200: if (lookupResp200_)   lookupResp200_->Increment();   break;
        case 403: if (lookupResp403_)   lookupResp403_->Increment();   break;
        case 404: if (lookupResp404_)   lookupResp404_->Increment();   break;
        case 503: if (lookupResp503_)   lookupResp503_->Increment();   break;
        default:  if (lookupRespError_) lookupRespError_->Increment(); break;
    }
}

void Metrics::incRadiusRequest(const std::string& result) {
    if (result == "accept") { if (radiusReqAccept_) radiusReqAccept_->Increment(); }
    else                    { if (radiusReqReject_) radiusReqReject_->Increment(); }
}

void Metrics::incUpstreamError(const std::string& upstream, const std::string& statusCode) {
    if (!upstreamErrorsFamily_) return;
    // Add() is idempotent for the same label set — returns existing counter if already created.
    upstreamErrorsFamily_->Add({{"upstream", upstream}, {"status_code", statusCode}}).Increment();
}
