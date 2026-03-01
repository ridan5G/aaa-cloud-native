"""
fixtures/range_configs.py — helpers for imsi_range_configs.
"""
import httpx


def create_range_config(
    http: httpx.Client,
    *,
    f_imsi: str,
    t_imsi: str,
    pool_id: str,
    ip_resolution: str = "imsi",
    account_name: str = "TestAccount",
    description: str = "regression-test range",
    status: str = "active",
) -> dict:
    """POST /range-configs and return the response body including id."""
    body = {
        "account_name":  account_name,
        "f_imsi":        f_imsi,
        "t_imsi":        t_imsi,
        "pool_id":       pool_id,
        "ip_resolution": ip_resolution,
        "description":   description,
        "status":        status,
    }
    resp = http.post("/range-configs", json=body)
    assert resp.status_code == 201, (
        f"create_range_config failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def delete_range_config(http: httpx.Client, config_id: int | str) -> None:
    """DELETE /range-configs/{id} — best-effort teardown."""
    resp = http.delete(f"/range-configs/{config_id}")
    if resp.status_code not in (204, 404):
        raise AssertionError(
            f"delete_range_config({config_id}) returned {resp.status_code}: {resp.text}"
        )
