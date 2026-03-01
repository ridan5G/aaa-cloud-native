#include "Resolver.h"

#include <algorithm>

// ---------------------------------------------------------------------------
// Resolver::resolve — entry point
// ---------------------------------------------------------------------------
ResolveResult Resolver::resolve(const std::vector<QueryRow>& rows,
                                const std::string& apn) {
    // Step 2: no rows → IMSI unknown
    if (rows.empty())
        return {ResolveStatus::NotFound, std::nullopt};

    // Step 3a: status check (uses the first row — all rows share sim/imsi status)
    const auto& first = rows.front();
    if (first.sim_status != "active" || first.imsi_status != "active")
        return {ResolveStatus::Suspended, std::nullopt};

    // Step 3b: dispatch by ip_resolution
    const std::string& mode = first.ip_resolution;

    if (mode == "imsi")      return resolveImsi(rows);
    if (mode == "imsi_apn")  return resolveImsiApn(rows, apn);
    if (mode == "iccid")     return resolveIccid(rows);
    if (mode == "iccid_apn") return resolveIccidApn(rows, apn);

    // Unknown ip_resolution — treat as not_found (should never happen with DB constraints)
    return {ResolveStatus::NotFound, std::nullopt};
}

// ---------------------------------------------------------------------------
// imsi mode — single APN-agnostic IP per IMSI.
// Find the row where imsi_apn IS NULL.
// ---------------------------------------------------------------------------
ResolveResult Resolver::resolveImsi(const std::vector<QueryRow>& rows) {
    for (const auto& row : rows) {
        if (!row.imsi_apn.has_value() && row.imsi_static_ip.has_value())
            return {ResolveStatus::Ok, row.imsi_static_ip};
    }
    // Should not happen if DB invariants hold
    return {ResolveStatus::NotFound, std::nullopt};
}

// ---------------------------------------------------------------------------
// imsi_apn mode — IP per IMSI+APN pair with optional wildcard fallback.
//   1. Exact match: row where imsi_apn = apn
//   2. Wildcard:    row where imsi_apn IS NULL
//   3. Neither → apn_not_found
// ---------------------------------------------------------------------------
ResolveResult Resolver::resolveImsiApn(const std::vector<QueryRow>& rows,
                                       const std::string& apn) {
    const QueryRow* wildcard = nullptr;

    for (const auto& row : rows) {
        if (!row.imsi_static_ip.has_value()) continue;

        if (row.imsi_apn.has_value() && row.imsi_apn.value() == apn)
            return {ResolveStatus::Ok, row.imsi_static_ip};   // exact match wins

        if (!row.imsi_apn.has_value())
            wildcard = &row;                                   // keep wildcard candidate
    }

    if (wildcard)
        return {ResolveStatus::Ok, wildcard->imsi_static_ip};

    return {ResolveStatus::ApnNotFound, std::nullopt};
}

// ---------------------------------------------------------------------------
// iccid mode — single card-level IP, APN ignored.
// Find the row where iccid_apn IS NULL.
// ---------------------------------------------------------------------------
ResolveResult Resolver::resolveIccid(const std::vector<QueryRow>& rows) {
    for (const auto& row : rows) {
        if (!row.iccid_apn.has_value() && row.iccid_static_ip.has_value())
            return {ResolveStatus::Ok, row.iccid_static_ip};
    }
    return {ResolveStatus::NotFound, std::nullopt};
}

// ---------------------------------------------------------------------------
// iccid_apn mode — IP per card+APN pair with optional wildcard fallback.
//   1. Exact match: row where iccid_apn = apn
//   2. Wildcard:    row where iccid_apn IS NULL
//   3. Neither → apn_not_found
// ---------------------------------------------------------------------------
ResolveResult Resolver::resolveIccidApn(const std::vector<QueryRow>& rows,
                                        const std::string& apn) {
    const QueryRow* wildcard = nullptr;

    for (const auto& row : rows) {
        if (!row.iccid_static_ip.has_value()) continue;

        if (row.iccid_apn.has_value() && row.iccid_apn.value() == apn)
            return {ResolveStatus::Ok, row.iccid_static_ip};  // exact match wins

        if (!row.iccid_apn.has_value())
            wildcard = &row;
    }

    if (wildcard)
        return {ResolveStatus::Ok, wildcard->iccid_static_ip};

    return {ResolveStatus::ApnNotFound, std::nullopt};
}
