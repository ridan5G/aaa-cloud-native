#pragma once

// ---------------------------------------------------------------------------
// Resolver — pure IP resolution logic.
//
// Takes the raw result set from the hot-path SQL query and applies the
// ip_resolution rules defined in Plan 3.  Has no side effects and no I/O.
// ---------------------------------------------------------------------------

#include <optional>
#include <string>
#include <vector>

// ---------------------------------------------------------------------------
// One row from the hot-path JOIN query.
// Both imsi_static_ip / iccid_static_ip are inet-typed in PG; we carry them
// as strings since they are returned verbatim to the caller.
// ---------------------------------------------------------------------------
struct QueryRow {
    std::string              sim_status;      // 'active' | 'suspended' | 'terminated'
    std::string              ip_resolution;   // 'imsi' | 'imsi_apn' | 'iccid' | 'iccid_apn'
    std::string              imsi_status;     // 'active' | 'suspended'
    std::optional<std::string> imsi_apn;      // NULL → wildcard/imsi-mode row
    std::optional<std::string> imsi_static_ip;
    std::optional<std::string> iccid_apn;     // NULL → wildcard/iccid-mode row
    std::optional<std::string> iccid_static_ip;
};

// ---------------------------------------------------------------------------
// ResolveResult — discriminated union returned by Resolver::resolve().
// ---------------------------------------------------------------------------
enum class ResolveStatus {
    Ok,            // 200 — static_ip is valid
    Suspended,     // 403 — SIM or IMSI is suspended
    NotFound,      // 404 {"error":"not_found"} — no rows for this IMSI
    ApnNotFound,   // 404 {"error":"apn_not_found"} — rows exist but APN unmatched
};

struct ResolveResult {
    ResolveStatus            status;
    std::optional<std::string> staticIp;  // valid only when status == Ok
};

// ---------------------------------------------------------------------------
// Resolver
// ---------------------------------------------------------------------------
class Resolver {
public:
    /// Apply ip_resolution logic to the result set from the hot-path query.
    /// @param rows    All rows returned for a given IMSI (may be empty).
    /// @param apn     The APN string from the Access-Request (always present).
    static ResolveResult resolve(const std::vector<QueryRow>& rows,
                                 const std::string& apn);

private:
    static ResolveResult resolveImsi    (const std::vector<QueryRow>& rows);
    static ResolveResult resolveImsiApn (const std::vector<QueryRow>& rows, const std::string& apn);
    static ResolveResult resolveIccid   (const std::vector<QueryRow>& rows);
    static ResolveResult resolveIccidApn(const std::vector<QueryRow>& rows, const std::string& apn);
};
