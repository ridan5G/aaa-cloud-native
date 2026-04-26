"""
fixtures/range_configs.py — helpers for imsi_range_configs.
"""
import time
import httpx


def wait_for_job(
    http: httpx.Client,
    job_id: str,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.25,
) -> dict:
    """Poll GET /jobs/{job_id} until status is terminal; return final body.

    Used by range-config helpers to block on the bulk pre-population / provision
    job dispatched by /range-configs and /iccid-range-configs/{id}/imsi-slots.
    Raises AssertionError on timeout or non-success terminal status.
    """
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        resp = http.get(f"/jobs/{job_id}")
        if resp.status_code == 404:
            time.sleep(poll_interval)
            continue
        assert resp.status_code == 200, f"GET /jobs/{job_id} failed: {resp.status_code} {resp.text}"
        last = resp.json()
        if last.get("status") in ("completed", "completed_with_errors", "failed"):
            assert last["status"] != "failed", (
                f"job {job_id} failed: {last}"
            )
            return last
        time.sleep(poll_interval)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s; last={last}")


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
    apns: list[dict] | None = None,
    provisioning_mode: str | None = None,
    await_job: bool = True,
) -> dict:
    """POST /range-configs and return the response body including id.

    ``apns`` (optional): list of APN entries for imsi_apn / iccid_apn ranges.
    Each entry is ``{"apn": "<apn-string>"}`` or ``{"apn": "...", "pool_id": "..."}``.
    When ``pool_id`` is omitted the range's default pool is used.
    Entries are registered via POST /range-configs/{id}/apn-pools immediately after creation.

    ``await_job`` (default True): if the API returns 202 + ``job_id`` (lazy
    IP pre-population), block until the job finishes so callers can /first-connection
    or /lookup right away. Pass False to inspect the job in flight.
    """
    body = {
        "account_name":  account_name,
        "f_imsi":        f_imsi,
        "t_imsi":        t_imsi,
        "pool_id":       pool_id,
        "ip_resolution": ip_resolution,
        "description":   description,
        "status":        status,
    }
    if provisioning_mode is not None:
        body["provisioning_mode"] = provisioning_mode
    resp = http.post("/range-configs", json=body)
    assert resp.status_code in (201, 202), (
        f"create_range_config failed: {resp.status_code} {resp.text}"
    )
    rc = resp.json()
    if await_job and rc.get("job_id"):
        wait_for_job(http, rc["job_id"])
    if apns:
        for entry in apns:
            add_apn_pool(
                http,
                range_config_id=rc["id"],
                apn=entry["apn"],
                pool_id=entry.get("pool_id") or pool_id,
            )
    return rc


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
    f_iccid: str | None = None,
    t_iccid: str | None = None,
    ip_resolution: str,
    account_name: str = "TestAccount",
    imsi_count: int = 2,
    pool_id: str | None = None,
    description: str = "regression-test iccid range",
    provisioning_mode: str | None = None,
) -> dict:
    """POST /iccid-range-configs and return the response body including id.

    ``f_iccid``/``t_iccid`` are optional — omit both to create an IMSI-only SIM group
    (no ICCID bounds; supports first_connect and immediate provisioning_modes).
    """
    body: dict = {
        "account_name":  account_name,
        "ip_resolution": ip_resolution,
        "imsi_count":    imsi_count,
        "description":   description,
    }
    if f_iccid is not None:
        body["f_iccid"] = f_iccid
    if t_iccid is not None:
        body["t_iccid"] = t_iccid
    if pool_id is not None:
        body["pool_id"] = pool_id
    if provisioning_mode is not None:
        body["provisioning_mode"] = provisioning_mode
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
    await_job: bool = True,
) -> dict:
    """POST /iccid-range-configs/{id}/imsi-slots and return response including range_config_id.

    The API returns 202 + ``job_id`` once the final slot of the iccid range is
    added (the bulk pre-claim / provisioning job is dispatched on the
    completing slot). When ``await_job`` is True (default) we poll until the
    job is in a terminal state so callers can /first-connection right away.
    """
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
    assert resp.status_code in (201, 202), (
        f"add_imsi_slot failed: {resp.status_code} {resp.text}"
    )
    rc = resp.json()
    if await_job and rc.get("job_id"):
        wait_for_job(http, rc["job_id"])
    return rc


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


def add_imsi_slot_apn_pool(
    http: httpx.Client,
    *,
    iccid_range_id: int | str,
    slot: int,
    apn: str,
    pool_id: str,
) -> dict:
    """POST /iccid-range-configs/{id}/imsi-slots/{slot}/apn-pools and return the response."""
    resp = http.post(
        f"/iccid-range-configs/{iccid_range_id}/imsi-slots/{slot}/apn-pools",
        json={"apn": apn, "pool_id": pool_id},
    )
    assert resp.status_code == 201, (
        f"add_imsi_slot_apn_pool failed: {resp.status_code} {resp.text}"
    )
    return resp.json()


def delete_iccid_range_config(http: httpx.Client, iccid_range_id: int | str) -> None:
    """DELETE /iccid-range-configs/{id} — best-effort teardown (cascades to imsi slots)."""
    resp = http.delete(f"/iccid-range-configs/{iccid_range_id}")
    if resp.status_code not in (204, 404):
        raise AssertionError(
            f"delete_iccid_range_config({iccid_range_id}) returned {resp.status_code}: {resp.text}"
        )
