import threading
from prometheus_client import Counter, Gauge, Histogram, start_http_server

api_request_duration = Histogram(
    "api_request_duration_ms",
    "API request duration in milliseconds",
    ["method", "path"],
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
)

first_connection_total = Counter(
    "first_connection_total",
    "First-connection allocation outcomes",
    ["result"],
)

pool_exhausted_total = Counter(
    "pool_exhausted_total",
    "Pool exhaustion events",
    ["pool_id"],
)

multi_imsi_siblings_provisioned_total = Counter(
    "multi_imsi_siblings_provisioned_total",
    "Number of sibling IMSIs provisioned in multi-IMSI first-connection",
)

bulk_job_profiles_total = Counter(
    "bulk_job_profiles_total",
    "Bulk job profile rows",
    ["outcome"],  # processed | failed
)

bulk_job_duration = Histogram(
    "bulk_job_duration_seconds",
    "Bulk job processing duration",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)

http_requests_in_flight = Gauge(
    "http_requests_in_flight",
    "Number of HTTP requests currently being processed",
    ["method", "path"],
)

db_rollbacks_total = Counter(
    "db_rollbacks_total",
    "Database transaction rollbacks caused by application errors",
    ["reason"],
)

# Per-pool IP utilization gauges. Refreshed periodically by
# pool_metrics_refresher; see app/pool_metrics_refresher.py.
_POOL_LABELS = ["pool_id", "pool_name", "account_name"]

aaa_pool_total_ips = Gauge(
    "aaa_pool_total_ips",
    "Total IP capacity of a static pool (sum of all subnet ranges)",
    _POOL_LABELS,
)
aaa_pool_allocated_ips = Gauge(
    "aaa_pool_allocated_ips",
    "Allocated IPs of a static pool (total - available)",
    _POOL_LABELS,
)
aaa_pool_available_ips = Gauge(
    "aaa_pool_available_ips",
    "Available (free) IPs of a static pool",
    _POOL_LABELS,
)
aaa_pool_metrics_refresh_timestamp_seconds = Gauge(
    "aaa_pool_metrics_refresh_timestamp_seconds",
    "Unix timestamp of the last successful pool metrics refresh",
)


def start_metrics_server(port: int):
    """Start Prometheus HTTP server on a daemon thread."""
    def _serve():
        start_http_server(port)

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
