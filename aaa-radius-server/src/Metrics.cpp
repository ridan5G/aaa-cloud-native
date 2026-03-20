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

    // radius_requests_total{result, stage} — result × stage breakdown for Grafana
    auto& radReqLabeledFam = prometheus::BuildCounter()
        .Name("radius_requests_total")
        .Help("RADIUS requests completed, labeled by result (accept|reject) and stage (1=lookup|2=first-connection)")
        .Register(*registry_);
    radiusReqAcceptStage1_ = &radReqLabeledFam.Add({{"result", "accept"}, {"stage", "1"}});
    radiusReqAcceptStage2_ = &radReqLabeledFam.Add({{"result", "accept"}, {"stage", "2"}});
    radiusReqRejectStage1_ = &radReqLabeledFam.Add({{"result", "reject"}, {"stage", "1"}});
    radiusReqRejectStage2_ = &radReqLabeledFam.Add({{"result", "reject"}, {"stage", "2"}});

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

    // ── Lookup (Stage 1) metrics ───────────────────────────────────────────────
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
    lookupRespError_ = &lookRespFam.Add({{"status", "error"}});

    // ── First-connection (Stage 2) metrics ────────────────────────────────────
    auto& fcReqFam = prometheus::BuildCounter()
        .Name("first_connection_requests_total")
        .Help("Total HTTP POST requests sent to the first-connection endpoint")
        .Register(*registry_);
    firstConnRequests_ = &fcReqFam.Add({});

    auto& fcRespFam = prometheus::BuildCounter()
        .Name("first_connection_responses_total")
        .Help("First-connection HTTP responses, labeled by status code")
        .Register(*registry_);
    firstConnResp200_   = &fcRespFam.Add({{"status", "200"}});
    firstConnResp404_   = &fcRespFam.Add({{"status", "404"}});
    firstConnResp503_   = &fcRespFam.Add({{"status", "503"}});
    firstConnRespError_ = &fcRespFam.Add({{"status", "error"}});

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
        default:  if (lookupRespError_) lookupRespError_->Increment(); break;
    }
}

void Metrics::incFirstConnResponse(int statusCode) {
    switch (statusCode) {
        case 200: if (firstConnResp200_)   firstConnResp200_->Increment();   break;
        case 404: if (firstConnResp404_)   firstConnResp404_->Increment();   break;
        case 503: if (firstConnResp503_)   firstConnResp503_->Increment();   break;
        default:  if (firstConnRespError_) firstConnRespError_->Increment(); break;
    }
}

void Metrics::incRadiusRequest(const std::string& result, const std::string& stage) {
    if (result == "accept") {
        if (stage == "1") { if (radiusReqAcceptStage1_) radiusReqAcceptStage1_->Increment(); }
        else              { if (radiusReqAcceptStage2_) radiusReqAcceptStage2_->Increment(); }
    } else {
        if (stage == "1") { if (radiusReqRejectStage1_) radiusReqRejectStage1_->Increment(); }
        else              { if (radiusReqRejectStage2_) radiusReqRejectStage2_->Increment(); }
    }
}

void Metrics::incUpstreamError(const std::string& upstream, const std::string& statusCode) {
    if (!upstreamErrorsFamily_) return;
    // Add() is idempotent for the same label set — returns existing counter if already created.
    upstreamErrorsFamily_->Add({{"upstream", upstream}, {"status_code", statusCode}}).Increment();
}
