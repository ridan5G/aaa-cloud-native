"""
fixtures/profiles.py — helpers for subscriber_profiles (all three modes).
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
    """POST /profiles with ip_resolution=iccid (Profile A).

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
    """POST /profiles with ip_resolution=imsi (Profile B).

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
    """POST /profiles with ip_resolution=imsi_apn (Profile C)."""
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


def delete_profile(http: httpx.Client, device_id: str) -> None:
    """DELETE /profiles/{device_id} — best-effort teardown (soft-delete)."""
    resp = http.delete(f"/profiles/{device_id}")
    if resp.status_code not in (204, 404):
        raise AssertionError(
            f"delete_profile({device_id}) returned {resp.status_code}: {resp.text}"
        )
