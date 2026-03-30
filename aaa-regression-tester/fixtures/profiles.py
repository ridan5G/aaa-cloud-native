"""
fixtures/profiles.py — helpers for sim_profiles (all three modes).
"""
import httpx


def create_profile_iccid(
    http: httpx.Client,
    *,
    iccid: str,
    account_name: str = "TestAccount",
    imsis: list[str],
    static_ip: str,
    pool_id: str,
    pool_name: str = "test-pool",
) -> dict:
    """POST /profiles with ip_resolution=iccid (iccid profile).

    All IMSIs on the card share one card-level IP entry (no apn field).
    """
    body = {
        "iccid":         iccid,
        "account_name":  account_name,
        "status":        "active",
        "ip_resolution": "iccid",
        "imsis": [
            {
                "imsi":    imsi,
                "apn_ips": [],              # apn_ips not used in iccid mode
            }
            for imsi in imsis
        ],
        "iccid_ips": [
            {
                "static_ip": static_ip,
                "pool_id":   pool_id,
                "pool_name": pool_name,
            }
        ],
    }
    resp = http.post("/profiles", json=body)
    assert resp.status_code == 201, (
        f"create_profile_iccid failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def create_profile_imsi(
    http: httpx.Client,
    *,
    iccid: str | None = None,
    account_name: str = "TestAccount",
    imsis: list[dict],   # [{"imsi": str, "static_ip": str, "pool_id": str}]
    pool_name: str = "test-pool",
) -> dict:
    """POST /profiles with ip_resolution=imsi (imsi profile).

    Each IMSI gets its own APN-agnostic IP (apn=null in DB).
    """
    body = {
        "iccid":         iccid,
        "account_name":  account_name,
        "status":        "active",
        "ip_resolution": "imsi",
        "imsis": [
            {
                "imsi":    entry["imsi"],
                "apn_ips": [
                    {
                        "static_ip": entry["static_ip"],
                        "pool_id":   entry["pool_id"],
                        "pool_name": pool_name,
                    }
                ],
            }
            for entry in imsis
        ],
    }
    resp = http.post("/profiles", json=body)
    assert resp.status_code == 201, (
        f"create_profile_imsi failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def create_profile_imsi_apn(
    http: httpx.Client,
    *,
    iccid: str | None = None,
    account_name: str = "TestAccount",
    # imsis: list of dicts with keys "imsi" and "apn_ips"
    # apn_ips: list of {"apn": str|None, "static_ip": str, "pool_id": str}
    imsis: list[dict],
    pool_name: str = "test-pool",
) -> dict:
    """POST /profiles with ip_resolution=imsi_apn (imsi_apn profile)."""
    body = {
        "iccid":         iccid,
        "account_name":  account_name,
        "status":        "active",
        "ip_resolution": "imsi_apn",
        "imsis": [
            {
                "imsi":    entry["imsi"],
                "apn_ips": [
                    {
                        "apn":       apn_entry.get("apn"),
                        "static_ip": apn_entry["static_ip"],
                        "pool_id":   apn_entry["pool_id"],
                        "pool_name": pool_name,
                    }
                    for apn_entry in entry["apn_ips"]
                ],
            }
            for entry in imsis
        ],
    }
    resp = http.post("/profiles", json=body)
    assert resp.status_code == 201, (
        f"create_profile_imsi_apn failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def create_profile_iccid_apn(
    http: httpx.Client,
    *,
    iccid: str,
    account_name: str = "TestAccount",
    imsis: list[str],
    apn_ips: list[dict],   # [{"apn": str, "static_ip": str, "pool_id": str}]
    pool_name: str = "test-pool",
) -> dict:
    """POST /profiles with ip_resolution=iccid_apn (iccid_apn profile).

    All IMSIs on the card share card-level IPs, one per APN.
    """
    body = {
        "iccid":         iccid,
        "account_name":  account_name,
        "status":        "active",
        "ip_resolution": "iccid_apn",
        "imsis": [
            {"imsi": imsi, "apn_ips": []}
            for imsi in imsis
        ],
        "iccid_ips": [
            {
                "apn":       entry["apn"],
                "static_ip": entry["static_ip"],
                "pool_id":   entry["pool_id"],
                "pool_name": pool_name,
            }
            for entry in apn_ips
        ],
    }
    resp = http.post("/profiles", json=body)
    assert resp.status_code == 201, (
        f"create_profile_iccid_apn failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def delete_profile(http: httpx.Client, sim_id: str) -> None:
    """DELETE /profiles/{sim_id} — best-effort teardown (soft-delete)."""
    resp = http.delete(f"/profiles/{sim_id}")
    if resp.status_code not in (204, 404):
        raise AssertionError(
            f"delete_profile({sim_id}) returned {resp.status_code}: {resp.text}"
        )


def cleanup_stale_profiles(http: httpx.Client, *imsi_prefixes: str) -> None:
    """Soft-delete any leftover active profiles from previous runs.

    Called at the start of setup_class for dynamic-allocation test modules
    (test_07, test_07b, test_07c).  Each module owns a distinct IMSI prefix so
    the query is precise and never touches another module's data.

    Design rationale
    ─────────────────
    teardown_class no longer deletes profiles — profiles created during a run
    are intentionally left active so they can be inspected via GET /profiles/export
    after the suite finishes.  The next run's setup_class calls this function to
    terminate any survivors before re-creating the infrastructure, guaranteeing a
    clean slate without requiring a full DB flush between runs.
    """
    for prefix in imsi_prefixes:
        r = http.get("/profiles", params={"imsi_prefix": prefix, "limit": 1000})
        if r.status_code != 200:
            continue
        data = r.json()
        items = (
            data
            if isinstance(data, list)
            else data.get("profiles", data.get("items", []))
        )
        for profile in items:
            if profile.get("status") != "terminated":
                try:
                    http.delete(f"/profiles/{profile['sim_id']}")
                except Exception:
                    pass
