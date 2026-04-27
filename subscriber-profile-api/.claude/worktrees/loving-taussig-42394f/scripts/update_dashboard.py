"""
update_dashboard.py
Add lookup KPI stats, suspended panel, and complete PostgreSQL section
to aaa-platform-dashboard.json.
"""
import json

DASH_PATH = (
    r"C:\Users\rony.idan\source\public-repo\aaa-cloud-native"
    r"\charts\aaa-platform\files\aaa-platform-dashboard.json"
)

with open(DASH_PATH) as f:
    d = json.load(f)

panels = d["panels"]

# ── Step 1: shift existing panels to make room ────────────────────────────────
# Panels with original y >= 5  get +4  (room for lookup KPI stats h=4 at y=5)
# Panels with original y >= 19 get +8 more  (room for suspended panel h=6 at y=23)
for p in panels:
    y = p["gridPos"]["y"]
    shift = 0
    if y >= 5:
        shift += 4
    if y >= 19:
        shift += 8
    p["gridPos"]["y"] = y + shift

# ── Helpers ───────────────────────────────────────────────────────────────────

def stat_panel(pid, title, expr, unit, thresholds, desc, x, y, w=6, h=4):
    """Build a Grafana stat panel dict."""
    steps = []
    for i, t in enumerate(thresholds):
        steps.append({"color": t[0], "value": None if i == 0 else t[1]})
    return {
        "id": pid, "type": "stat", "title": title,
        "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "options": {
            "colorMode": "background",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {
                "calcs": ["lastNotNull"], "fields": "", "values": False
            },
            "textMode": "auto",
            "thresholdsMode": "absolute",
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": {"mode": "absolute", "steps": steps},
                "color": {"mode": "thresholds"},
            },
            "overrides": [],
        },
        "targets": [{
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "expr": expr,
            "instant": True,
            "legendFormat": "__auto",
            "refId": "A",
        }],
    }


def ts_panel(pid, title, targets, unit, desc, x, y, w=12, h=8):
    """Build a Grafana timeseries panel dict."""
    tgts = []
    for i, (expr, legend) in enumerate(targets):
        tgts.append({
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "expr": expr,
            "legendFormat": legend,
            "refId": chr(65 + i),
        })
    return {
        "id": pid, "type": "timeseries", "title": title,
        "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {"lineWidth": 2, "fillOpacity": 10},
            },
            "overrides": [],
        },
        "options": {
            "tooltip": {"mode": "multi", "sort": "desc"},
            "legend": {"displayMode": "list", "placement": "bottom"},
        },
        "targets": tgts,
    }


def row_panel(pid, title, y):
    return {
        "id": pid, "type": "row", "title": title,
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
    }


# ── Step 2: Lookup KPI stat panels at y=5 (IDs 50-53) ────────────────────────
lookup_kpis = [
    stat_panel(
        50, "Lookup Throughput",
        "sum(rate(aaa_lookup_requests_total[$__rate_interval]))",
        "reqps",
        [("blue", None)],
        "Total lookup requests per second across all outcomes (found, not_found, suspended, db_error).",
        0, 5,
    ),
    stat_panel(
        51, "Lookup DB Errors (1h)",
        "sum(increase(aaa_db_errors_total[1h]))",
        "short",
        [("green", None), ("red", 1)],
        "Total DB read-replica errors in the last hour. Any value > 0 needs immediate investigation.",
        6, 5,
    ),
    stat_panel(
        52, "Suspended Lookups (1h)",
        'sum(increase(aaa_lookup_requests_total{result="suspended"}[1h]))',
        "short",
        [("green", None), ("yellow", 1), ("red", 50)],
        "Lookups returning 403 (subscriber suspended) in the last hour. "
        "A sustained count may indicate corrupted subscriber state or a mass-suspension batch.",
        12, 5,
    ),
    stat_panel(
        53, "In-Flight Requests",
        "aaa_in_flight_requests",
        "short",
        [("green", None), ("yellow", 50), ("red", 200)],
        "Current number of concurrent RADIUS requests being processed by aaa-lookup-service. "
        "Should stay well below RADIUS_WORKERS thread count.",
        18, 5,
    ),
]

# ── Step 3: Suspended subscribers time-series at y=23 (ID 54) ─────────────────
#  After shift: panels 6,7 now start at y=9 (h=8 → end y=17),
#               panels 8,9,10 now start at y=17 (h=6 → end y=23).
#  We insert this panel immediately after panel 10, at y=23 (h=6).
lookup_suspended = ts_panel(
    54,
    "Suspended vs Not-Found Lookup Rate",
    [
        (
            'sum(rate(aaa_lookup_requests_total{result="suspended"}[$__rate_interval]))',
            "suspended/s",
        ),
        (
            'sum(rate(aaa_lookup_requests_total{result="not_found"}[$__rate_interval]))',
            "not_found/s",
        ),
        (
            'sum(rate(aaa_lookup_requests_total{result="db_error"}[$__rate_interval]))',
            "db_error/s",
        ),
    ],
    "reqps",
    "Rate of suspended-subscriber rejections (403), not-found lookups (404), and DB errors per second. "
    "A rising suspended rate indicates mass-suspension or corrupted state; "
    "a rising not_found rate indicates new SIMs without matching range config.",
    0, 23, w=24, h=6,
)

# ── Step 4: PostgreSQL / PgBouncer section ─────────────────────────────────────
# After both shifts, the last existing panel (UI panel 46) lands at:
#   was y=84 → +12 shift = y=96, h=8 → ends at y=104.
# After panel 10, we insert suspended (h=6), and panels that were y>=19 shift by +12.
# Subscriber row was y=19 → y=31; last UI panel (46) was y=84 → y=96.
# UI panel 46 ends at y=96+8=104.  PostgreSQL section starts at y=104.
PG_Y = 104

pg_panels = [
    # ── Row ──────────────────────────────────────────────────────────────────
    row_panel(
        60,
        "PostgreSQL / PgBouncer  (CloudNativePG + postgres-exporter + pgbouncer-exporter)",
        PG_Y,
    ),

    # ── KPI stat cards ────────────────────────────────────────────────────────
    stat_panel(
        61, "DB Primary Up",
        "min(pg_up)",
        "short",
        [("red", None), ("green", 1)],
        "pg_up = 1 when postgres_exporter can connect to the primary. 0 = primary unreachable.",
        0, PG_Y + 1,
    ),
    stat_panel(
        62, "Active DB Connections",
        'sum(pg_stat_activity_count{state="active"})',
        "short",
        [("green", None), ("yellow", 80), ("red", 150)],
        "Connections currently executing a query on the primary. "
        "High values indicate slow queries or connection pile-up.",
        6, PG_Y + 1,
    ),
    stat_panel(
        63, "Replica WAL Lag",
        "max(pg_stat_replication_pg_wal_lsn_diff)",
        "bytes",
        [("green", None), ("yellow", 10485760), ("red", 52428800)],
        "WAL bytes the standby is behind the primary. Yellow >= 10 MB, Red >= 50 MB.",
        12, PG_Y + 1,
    ),
    stat_panel(
        64, "Database Size",
        'pg_database_size_bytes{datname="aaa"}',
        "bytes",
        [("green", None), ("yellow", 5368709120), ("red", 10737418240)],
        "Total on-disk size of the aaa database. Yellow >= 5 GB, Red >= 10 GB.",
        18, PG_Y + 1,
    ),

    # ── Time-series panels ────────────────────────────────────────────────────
    ts_panel(
        65, "PgBouncer Connection Pool  (aaa database)",
        [
            ('pgbouncer_pools_sv_active{database="aaa"}', "server active"),
            ('pgbouncer_pools_sv_idle{database="aaa"}',   "server idle"),
            ('pgbouncer_pools_cl_active{database="aaa"}', "client active"),
            ('pgbouncer_pools_cl_waiting{database="aaa"}', "client waiting ⚠"),
        ],
        "short",
        "PgBouncer pool utilisation for the aaa database. "
        "client_waiting > 0 means the pool is saturated and queries are queuing behind PgBouncer.",
        0, PG_Y + 5, w=12,
    ),
    ts_panel(
        66, "Transaction Rate (commits + rollbacks)",
        [
            (
                'rate(pg_stat_database_xact_commit_total{datname="aaa"}[$__rate_interval])',
                "commits/s",
            ),
            (
                'rate(pg_stat_database_xact_rollback_total{datname="aaa"}[$__rate_interval])',
                "rollbacks/s",
            ),
        ],
        "ops",
        "Committed and rolled-back transactions per second on the aaa database. "
        "A spike in rollbacks indicates application-level conflicts or failed bulk-job rows.",
        12, PG_Y + 5, w=12,
    ),
    ts_panel(
        67, "Replication Lag Over Time",
        [
            ("pg_stat_replication_pg_wal_lsn_diff", "WAL lag (bytes)"),
        ],
        "bytes",
        "WAL replication lag trend over time. SLA threshold: 50 MB. "
        "Sustained lag means the replica is falling behind under write load.",
        0, PG_Y + 13, w=12,
    ),
    ts_panel(
        68, "DB Block Cache Hit Ratio",
        [
            (
                "rate(pg_stat_database_blks_hit_total{datname=\"aaa\"}[$__rate_interval])"
                " / ("
                "rate(pg_stat_database_blks_hit_total{datname=\"aaa\"}[$__rate_interval])"
                " + rate(pg_stat_database_blks_read_total{datname=\"aaa\"}[$__rate_interval])"
                ") * 100",
                "hit ratio %",
            ),
        ],
        "percent",
        "Percentage of block reads served from shared_buffers (no disk I/O). "
        "Values below 95% indicate the server needs more shared_buffers or RAM.",
        12, PG_Y + 13, w=12,
    ),
    ts_panel(
        69, "Lock Contention by Mode",
        [
            ('pg_locks_count{mode="ExclusiveLock"}',       "ExclusiveLock"),
            ('pg_locks_count{mode="RowExclusiveLock"}',    "RowExclusiveLock"),
            ('pg_locks_count{mode="ShareLock"}',           "ShareLock"),
            ('pg_locks_count{mode="AccessExclusiveLock"}', "AccessExclusiveLock"),
            ('pg_locks_count{mode="RowShareLock"}',        "RowShareLock"),
        ],
        "short",
        "Active lock counts grouped by lock mode. ExclusiveLock spikes indicate DDL operations "
        "or bulk writes contending with RADIUS read queries.",
        0, PG_Y + 21, w=24,
    ),
]

# ── Step 5: assemble new panel list ──────────────────────────────────────────
new_panels = []
for p in panels:
    new_panels.append(p)
    if p["id"] == 5:         # after lookup row → inject KPI stats
        new_panels.extend(lookup_kpis)
    if p["id"] == 10:        # after last lookup ts panel → inject suspended panel
        new_panels.append(lookup_suspended)

new_panels.extend(pg_panels)

d["panels"] = new_panels
d["version"] = 3
d["description"] = (
    "AAA Platform — end-to-end observability for aaa-lookup-service, "
    "subscriber-profile-api, aaa-radius-server, and PostgreSQL/PgBouncer"
)

with open(DASH_PATH, "w") as f:
    json.dump(d, f, indent=2)

print(f"Saved. Total panels: {len(new_panels)}")
for p in new_panels:
    gp = p["gridPos"]
    print(f"  id={p['id']:3d}  y={gp['y']:3d}  h={gp['h']:2d}  w={gp['w']:2d}  {p.get('title','')[:55]}")
