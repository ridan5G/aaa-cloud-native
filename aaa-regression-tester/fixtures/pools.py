"""
fixtures/pools.py — helpers for creating and tearing down ip_pools.

Each test module that needs a pool calls create_pool() in setup and
delete_pool() in teardown (inside a finally block to guarantee cleanup).
"""
import httpx


def create_pool(
    http: httpx.Client,
    *,
    subnet: str = "100.65.120.0/24",
    pool_name: str = "test-pool",
    account_name: str = "TestAccount",
    start_ip: str | None = None,
    end_ip: str | None = None,
) -> dict:
    """POST /pools and return the full response body including pool_id."""
    body: dict = {
        "pool_name":    pool_name,
        "account_name": account_name,
        "subnet":       subnet,
    }
    if start_ip:
        body["start_ip"] = start_ip
    if end_ip:
        body["end_ip"] = end_ip

    resp = http.post("/pools", json=body)
    assert resp.status_code == 201, f"create_pool failed: {resp.status_code} {resp.text}"
    return resp.json()


def delete_pool(http: httpx.Client, pool_id: str) -> None:
    """DELETE /pools/{pool_id} — best-effort teardown (ignores 404)."""
    resp = http.delete(f"/pools/{pool_id}")
    if resp.status_code not in (204, 404, 409):
        raise AssertionError(
            f"delete_pool({pool_id}) returned unexpected {resp.status_code}: {resp.text}"
        )


def get_pool_stats(http: httpx.Client, pool_id: str) -> dict:
    """GET /pools/{pool_id}/stats and return the body."""
    resp = http.get(f"/pools/{pool_id}/stats")
    assert resp.status_code == 200, f"get_pool_stats failed: {resp.status_code}"
    return resp.json()
