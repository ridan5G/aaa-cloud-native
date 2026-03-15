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


# ── ICCID range config helpers (multi-IMSI SIM provisioning) ─────────────────

def create_iccid_range_config(
    http: httpx.Client,
    *,
    f_iccid: str,
    t_iccid: str,
    ip_resolution: str,
    account_name: str = "TestAccount",
    imsi_count: int = 2,
    pool_id: str | None = None,
    description: str = "regression-test iccid range",
) -> dict:
    """POST /iccid-range-configs and return the response body including id."""
    body = {
        "account_name":  account_name,
        "f_iccid":       f_iccid,
        "t_iccid":       t_iccid,
        "ip_resolution": ip_resolution,
        "imsi_count":    imsi_count,
        "description":   description,
    }
    if pool_id is not None:
        body["pool_id"] = pool_id
    resp = http.post("/iccid-range-configs", json=body)
    assert resp.status_code == 201, (
        f"create_iccid_range_config failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def add_imsi_slot(
    http: httpx.Client,
    *,
    iccid_range_id: int | str,
    f_imsi: str,
    t_imsi: str,
    imsi_slot: int,
    ip_resolution: str,
    pool_id: str | None = None,
    description: str = "regression-test imsi slot",
) -> dict:
    """POST /iccid-range-configs/{id}/imsi-slots and return response including range_config_id."""
    body = {
        "f_imsi":        f_imsi,
        "t_imsi":        t_imsi,
        "ip_resolution": ip_resolution,
        "imsi_slot":     imsi_slot,
        "description":   description,
    }
    if pool_id is not None:
        body["pool_id"] = pool_id
    resp = http.post(f"/iccid-range-configs/{iccid_range_id}/imsi-slots", json=body)
    assert resp.status_code == 201, (
        f"add_imsi_slot failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def add_apn_pool(
    http: httpx.Client,
    *,
    range_config_id: int | str,
    apn: str,
    pool_id: str,
) -> dict:
    """POST /range-configs/{id}/apn-pools and return the response."""
    resp = http.post(f"/range-configs/{range_config_id}/apn-pools",
                     json={"apn": apn, "pool_id": pool_id})
    assert resp.status_code == 201, (
        f"add_apn_pool failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def delete_iccid_range_config(http: httpx.Client, iccid_range_id: int | str) -> None:
    """DELETE /iccid-range-configs/{id} — best-effort teardown (cascades to imsi slots)."""
    resp = http.delete(f"/iccid-range-configs/{iccid_range_id}")
    if resp.status_code not in (204, 404):
        raise AssertionError(
            f"delete_iccid_range_config({iccid_range_id}) returned {resp.status_code}: {resp.text}"
        )
