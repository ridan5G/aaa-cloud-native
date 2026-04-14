# Plan 6 — Migration: MariaDB → PostgreSQL

## Purpose

This document is the sole reference for the one-time migration from the 7 regional
MariaDB/Galera AAA clusters to the new PostgreSQL subscriber profile system.
It is written for the engineer(s) executing the migration and covers everything needed
from first data analysis to final MariaDB decommission.

The new system must be fully operational — PostgreSQL schema deployed, both application
containers running, regression tests passing — before this migration begins.

---

## Source: 7 Regional MariaDB/Galera Clusters

| Region | Dump file name (example) | Notes |
|---|---|---|
| Athens | `athens_aaa_dump.sql` | Primary source; largest data set |
| Miami | `miami_aaa_dump.sql` | ~105K IMSI/IP conflicts with Telefonica (different clients — not real conflicts) |
| Singapore | `singapore_aaa_dump.sql` | |
| Telefonica | `telefonica_aaa_dump.sql` | Shares IMSIs with Miami under different client_id |
| TIS | `tis_aaa_dump.sql` | |
| _(+2 others)_ | | Confirm names before migration |

**Total data volume:** ~8M rows in `tbl_clients_ips`; ~650K with non-NULL IMSI (operational records).
The remaining ~7.4M rows are unallocated pool slots and are skipped entirely.

---

## Source Tables

| Table | Key fields | Approx rows | Disposition |
|---|---|---|---|
| `tbl_clients` | id, name | ~20–50 / dump | Build mapping file only — not loaded to PostgreSQL |
| `tbl_clients_ips` | client_id, imsi, ip, imei | ~8M total (650K non-NULL IMSI) | Core migration — sim_profiles + imsis + apn_ips |
| `tbl_ip_pools` | id, client_id, name, start_ip, subnet | ~5–20 / dump | → ip_pools + ip_pool_available |
| `tbl_imsi_range_config` | client_id, f_imsi, t_imsi | ~328 total | → imsi_range_configs |
| `tbl_snat_dnat` | iccid, internal_ip, external_ip | 0 rows (Melita POC only) | Skip; document as future work |

**Gaps in source schema — how they are handled:**

| Gap | Handling |
|---|---|
| No `iccid` column | `iccid = NULL` for all IMSIs not in `imsi_iccid_map.csv`; enriched post-cutover |
| No `apn` column | All migrated profiles use `ip_resolution = "imsi"` (APN-agnostic, matches old behaviour) |
| No `ipv6` | IPv4 only in migrated data |
| No explicit `pool_id` in `tbl_clients_ips` | Derived in transform by matching `ip` to the containing subnet in `pool_map.csv` |

---

## Pre-Migration Inputs (Operator Must Supply)

| File | Columns | Purpose |
|---|---|---|
| `imsi_iccid_map.csv` | `imsi, iccid` | Maps real ICCID from SIM inventory to IMSI. IMSIs not in this file get `iccid = NULL`. |
| All 7 MariaDB dump files | — | Source data |

**`imsi_iccid_map.csv` is the most critical input.** The quality of ICCID data post-migration
depends entirely on coverage of this file. Confirm row count and spot-check a sample before
proceeding.

---

## Target Tables (PostgreSQL)

All tables are created by the DB plan schema before migration starts.

| Target Table | Populated from |
|---|---|
| `sim_profiles` | Transform output of `tbl_clients_ips` |
| `imsi2sim` | Transform output of `tbl_clients_ips` |
| `imsi_apn_ips` | Transform output of `tbl_clients_ips` |
| `sim_apn_ips` | Empty at migration time; populated post-cutover if Profile A is adopted |
| `ip_pools` | `tbl_ip_pools` |
| `ip_pool_available` | Computed from `ip_pools` minus already-allocated IPs |
| `imsi_range_configs` | `tbl_imsi_range_config` — all rows get `iccid_range_id = NULL` (standalone/single-IMSI mode) |
| `iccid_range_configs` | **Not populated at migration time.** Multi-IMSI SIM ranges are provisioned post-cutover by operators via `POST /iccid-range-configs` when new multi-IMSI SIM batches are ordered. `pool_id` is optional — each child IMSI slot can define its own pool. `f_iccid`/`t_iccid` are nullable — omit both for IMSI-only groups with no ICCID bounds. |
| `range_config_apn_pools` | **Not populated at migration time.** Operators add APN→pool overrides post-cutover via `POST /range-configs/{id}/apn-pools` when per-APN pool routing is needed. |
| `bulk_jobs` | **Not populated at migration time.** Created on-demand by the API when bulk import/provisioning jobs are submitted. Empty at schema init. |

---

## Pre-Migration Checklist

Complete every item before starting Step 1.

- [ ] PostgreSQL 15+ deployed, schema applied (all 11 tables, indexes, triggers, constraints)
- [ ] Both application containers (`subscriber-profile-api`, `aaa-lookup-service`) deployed and `/health` returning 200
- [ ] Regression test suite passing against the empty PostgreSQL instance
- [ ] All 7 MariaDB dump files available and MD5-checksummed
- [ ] `imsi_iccid_map.csv` received from operator, row count confirmed, sample spot-checked
- [ ] Migration script checked out and tested against a small fixture dump (Athens 1K-row subset)
- [ ] `client_id_map.csv` consistency confirmed: same `client_id` maps to same `account_name` across all dumps
- [ ] Staging server has sufficient disk space (source dumps + 4 output CSVs + PostgreSQL data)
- [ ] aaa-radius-server two-stage rlm_rest config prepared and tested in staging (Stage 1 → `aaa-lookup-service`, Stage 2 → `subscriber-profile-api /first-connection`)
- [ ] Rollback procedure reviewed and understood by all engineers on-call for cutover
- [ ] Maintenance window booked (Step 5 cutover): minimum 2-hour window, off-peak

---

## Step 1 — Extract

**Who runs it:** Migration engineer
**When:** Before dual-write period; can be run multiple times without side effects

Run the extractor against all 7 MariaDB dumps. The existing `make_xlsx.pl` script can be
reused or replaced with a dedicated Python extractor.

**For each dump, extract:**

```sql
-- tbl_clients → client_id_map.csv
SELECT  id    AS old_client_id,
        name  AS account_name
FROM    tbl_clients;
-- Confirm: same client_id=42 has same name across all dumps
```

```sql
-- tbl_ip_pools → staging_pools.csv
SELECT  id          AS old_pool_id,
        client_id   AS old_client_id,
        name        AS pool_name,
        start_ip,
        subnet,
        INET_ATON(start_ip) + POW(2, 32 - SUBSTRING_INDEX(subnet,'/',-1)) - 1
                    AS end_ip_int
FROM    tbl_ip_pools;
```

```sql
-- tbl_clients_ips → core extract (NON-NULL IMSI only)
SELECT  'dump_filename'  AS source_file,
        client_id,
        imsi,
        ip,
        imei
FROM    tbl_clients_ips
WHERE   imsi IS NOT NULL;
-- Expected: ~650K rows across all 7 dumps
```

```sql
-- tbl_imsi_range_config → staging_ranges.csv
SELECT  id          AS old_id,
        client_id   AS old_client_id,
        f_imsi,
        t_imsi,
        description
FROM    tbl_imsi_range_config;
-- Expected: ~328 rows total
```

**Output files after Step 1:**
- `client_id_map.csv` — merged, deduplicated across all dumps
- `staging_pools.csv` — one row per pool per dump
- `core_extract.csv` — all non-NULL IMSI rows, tagged with source_file
- `staging_ranges.csv` — all range config rows

**Go / No-Go gate:**
- [ ] `core_extract.csv` row count ~650K (confirm against prior analysis)
- [ ] No client_id with conflicting account_name across dumps
- [ ] No IMSI in `core_extract.csv` that is less or more than 15 digits

---

## Step 2 — Transform

**Who runs it:** Migration engineer (script)
**When:** After Step 1 completes; before Step 3

The transform script groups all source rows by physical SIM card, resolves ICCIDs,
deduplicates IPs, and emits 4 CSV files ready for PostgreSQL bulk load.

### Grouping Key

The transform groups rows by **physical SIM card**, not by IMSI, using the ICCID as
the grouping key where known:

```
If imsi is in imsi_iccid_map.csv:
    card_key = (client_id, iccid)        ← physical card
Else:
    card_key = (client_id, "IMSI:" + imsi)  ← treat as own device until enriched
```

This correctly models Multi-IMSI SIM cards: two IMSIs sharing the same ICCID under the
same client become one `sim_profiles` row with two rows in `imsi2sim`.

### Transform Pseudocode

```
# Load reference files
load client_id_map.csv    → hash: old_client_id   → account_name string
load pool_map.csv         → hash: (client_id, ip) → {pool_id, pool_name}
load imsi_iccid_map.csv   → hash: imsi             → real_iccid
build reverse_iccid_map   → hash: (client_id, iccid) → [imsi, ...]

# Sort dumps alphabetically → deterministic pgw label assignment
# Athens → pgw1, Miami → pgw2, Singapore → pgw3, Telefonica → pgw4, TIS → pgw5, ...

# Group all rows from core_extract.csv
for each dump in sorted(dump_files):
    for each row where imsi IS NOT NULL:
        iccid = imsi_iccid_map[row.imsi] or None

        if iccid is not None:
            card_key = (row.client_id, iccid)
        else:
            card_key = (row.client_id, "IMSI:" + row.imsi)

        group[card_key][row.imsi] += { ip: row.ip, source: dump_name }

# Emit one sim_profiles row per card_key
for each (card_key, imsi_groups) in groups:
    client_id, iccid_or_sentinel = card_key
    iccid        = iccid_or_sentinel if not starts_with("IMSI:") else None
    sim_id    = generate_uuid()
    account_name = client_id_map[client_id]   # may be None

    any_multi_ip = any(len(deduplicate(entries)) > 1
                       for entries in imsi_groups.values())
    ip_resolution = "imsi_apn" if any_multi_ip else "imsi"

    emit → out_sim_profiles.csv

    for each imsi, entries in imsi_groups.items():
        emit → out_imsi2sim.csv

        unique_ips = deduplicate(entries)   # {source → ip}
        if len(unique_ips) == 1:
            emit (imsi, apn=NULL, static_ip=unique_ip) → out_imsi_apn_ips.csv
        else:
            for n, (source, ip) in enumerate(unique_ips, start=1):
                emit (imsi, apn="pgw"+n, static_ip=ip) → out_imsi_apn_ips.csv
```

### Deduplication Cases

| Case | ip_resolution | apn values | Action |
|---|---|---|---|
| 1 dump, 1 IP, ICCID known | `imsi` | NULL | All IMSIs on same card → one `sim_id` |
| 1 dump, 1 IP, ICCID unknown | `imsi` | NULL | Each IMSI gets its own `sim_id` |
| N dumps, same IP, same client_id | `imsi` | NULL | Deduplicate to 1 `apn_ips` row |
| N dumps, different IPs, same client_id | `imsi_apn` | pgw1, pgw2, … | N `apn_ips` rows per IMSI |
| Same IMSI, different client_id | `imsi` | NULL | Both valid — insert independently |
| Multiple IMSIs, same ICCID, same client_id | `imsi` | NULL | Grouped onto one `sim_id` |

### Known Conflict Counts

| Case | Count | Resolution |
|---|---|---|
| Same IMSI, same IP, same client_id, multiple dumps | Common | Deduplicate → 1 row |
| Same IMSI, **different IPs**, same client_id | ~3 known | `imsi_apn` with pgw labels |
| Same IMSI, different client_id | ~105K (Miami/Telefonica) | Not a conflict — different tenants |
| Multiple IMSIs, same ICCID | Known Multi-IMSI SIMs | Grouped onto one `sim_id` |
| IMSI in range_config but not in `tbl_clients_ips` | Range-only | Skip; record in audit log |
| IMSI not in `imsi_iccid_map.csv` | Some | `iccid = NULL`; enriched in Step 6 |

### Output Files

| File | Description |
|---|---|
| `out_sim_profiles.csv` | One row per physical SIM card |
| `out_imsi2sim.csv` | One row per IMSI |
| `out_imsi_apn_ips.csv` | One row per IMSI+APN IP entry |
| `out_sim_apn_ips.csv` | Empty — populated post-cutover if Profile A adopted |
| `out_ip_pools.csv` | Transformed pool definitions |
| `out_pool_map.csv` | old_pool_id → new UUID mapping (used in Step 3 and post-cutover) |
| `out_imsi_range_configs.csv` | Range configs with resolved pool_ids |
| `migration_audit.log` | Per-row decisions: deduplication, pgw label assignments, skips |

**Go / No-Go gate:**
- [ ] `out_sim_profiles.csv` row count matches expected card count (not IMSI count)
- [ ] `out_imsi2sim.csv` row count ≈ 650K
- [ ] No duplicate `sim_id` in `out_sim_profiles.csv`
- [ ] No duplicate `imsi` in `out_imsi2sim.csv`
- [ ] All `static_ip` values in `out_imsi_apn_ips.csv` resolve to a `pool_id` in `out_ip_pools.csv`
- [ ] `migration_audit.log` reviewed; unexpected deduplication counts investigated

---

## Step 3 — Load

**Who runs it:** Migration engineer (SQL)
**When:** After Step 2 passes Go/No-Go gate
**Risk:** Low — loads into a PostgreSQL instance that is not yet serving live traffic

### 3A — Load IP Pools

```sql
CREATE TEMP TABLE staging_ip_pools (
    old_pool_id     TEXT,
    old_client_id   TEXT,
    account_name    TEXT,
    pool_name       TEXT,
    pool_name_new   TEXT,
    subnet          TEXT,
    start_ip        TEXT,
    end_ip          TEXT
);
\COPY staging_ip_pools FROM 'out_ip_pools.csv' WITH (FORMAT csv, HEADER true);

INSERT INTO ip_pools (pool_id, account_name, pool_name, subnet, start_ip, end_ip, status)
SELECT  gen_random_uuid(),
        account_name,
        pool_name,
        subnet::CIDR,
        start_ip::INET,
        end_ip::INET,
        'active'
FROM    staging_ip_pools
ON CONFLICT DO NOTHING;

-- Pre-populate ip_pool_available
-- Exclude IPs already assigned (imsi_apn_ips loaded in 3C)
-- Run AFTER 3C completes.
-- (See 3D below)
```

### 3B — Load IMSI Range Configs

All rows migrated from `tbl_imsi_range_config` are standalone single-IMSI ranges.
`iccid_range_id` is explicitly set to NULL — Multi-IMSI SIM ranges are not present
in the old schema and will be provisioned post-cutover via the API.

```sql
CREATE TEMP TABLE staging_ranges (
    old_id          TEXT,
    account_name    TEXT,
    f_imsi          TEXT,
    t_imsi          TEXT,
    pool_id         UUID,
    description     TEXT
);
\COPY staging_ranges FROM 'out_imsi_range_configs.csv' WITH (FORMAT csv, HEADER true);

INSERT INTO imsi_range_configs
    (account_name, f_imsi, t_imsi, pool_id, ip_resolution,
     iccid_range_id, imsi_slot, description, status, provisioning_mode)
SELECT  account_name, f_imsi, t_imsi, pool_id, 'imsi',
        NULL,             -- iccid_range_id: standalone mode (no multi-IMSI SIM parent)
        1,                -- imsi_slot: default primary slot; irrelevant when iccid_range_id IS NULL
        description, 'active',
        'first_connect'   -- all migrated ranges use first-connection dynamic allocation
FROM    staging_ranges
ON CONFLICT DO NOTHING;
```

### 3C — Load Subscriber Profiles, IMSIs, APN IPs

```sql
-- Staging table (explicit columns — do NOT use LIKE INCLUDING ALL,
-- that copies GENERATED ALWAYS AS IDENTITY and breaks loading pre-generated sim_ids)
CREATE TEMP TABLE staging_profiles (
    sim_id       UUID,
    iccid           TEXT,
    account_name    TEXT,
    status          TEXT,
    ip_resolution   TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ
);
\COPY staging_profiles FROM 'out_sim_profiles.csv' WITH (FORMAT csv, HEADER true);

INSERT INTO sim_profiles
    (sim_id, iccid, account_name, status, ip_resolution, metadata)
    SELECT sim_id, iccid, account_name, status, ip_resolution, metadata
    FROM staging_profiles
    ON CONFLICT (sim_id) DO NOTHING;
-- ON CONFLICT (iccid) is handled by the UNIQUE constraint automatically;
-- duplicate real ICCIDs will be silently skipped (already logged in audit).

CREATE TEMP TABLE staging_imsis (
    imsi        TEXT,
    sim_id   UUID,
    status      TEXT,
    priority    SMALLINT
);
\COPY staging_imsis FROM 'out_imsi2sim.csv' WITH (FORMAT csv, HEADER true);

INSERT INTO imsi2sim (imsi, sim_id, status, priority)
    SELECT imsi, sim_id, status, priority
    FROM staging_imsis
    ON CONFLICT (imsi) DO NOTHING;

CREATE TEMP TABLE staging_apn_ips (
    imsi        TEXT,
    apn         TEXT,
    static_ip   INET,
    pool_id     UUID,
    pool_name   TEXT
);
\COPY staging_apn_ips FROM 'out_imsi_apn_ips.csv' WITH (FORMAT csv, HEADER true);

INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id, pool_name)
    SELECT imsi, NULLIF(apn,''), static_ip, pool_id, pool_name
    FROM staging_apn_ips
    ON CONFLICT (imsi, apn) DO NOTHING;
```

### 3D — Pre-populate ip_pool_available

Run **after 3C completes** so that already-assigned IPs are correctly excluded.

```sql
-- Populate available IPs: all IPs in subnet minus those already in imsi_apn_ips
INSERT INTO ip_pool_available (pool_id, ip)
SELECT p.pool_id, (p.start_ip + n)::INET
FROM   ip_pools p,
       generate_series(1, p.end_ip - p.start_ip - 1) AS n
WHERE  (p.start_ip + n)::INET NOT IN (
           SELECT static_ip FROM imsi_apn_ips WHERE pool_id = p.pool_id
       )
ON CONFLICT DO NOTHING;
```

**Expected timing:** ~2–3 minutes total for all 7 regional clusters combined.

**Post-load verification queries:**
```sql
-- Row counts
SELECT COUNT(*) FROM sim_profiles;    -- expect: card count from transform
SELECT COUNT(*) FROM imsi2sim;       -- expect: ~650K
SELECT COUNT(*) FROM imsi_apn_ips;     -- expect: ~650K + extra for pgw1/pgw2 profiles
SELECT COUNT(*) FROM ip_pools;
SELECT COUNT(*) FROM imsi_range_configs;     -- expect: ~328
SELECT COUNT(*) FROM iccid_range_configs;    -- expect: 0 (not populated at migration time)
SELECT COUNT(*) FROM range_config_apn_pools; -- expect: 0 (populated post-cutover by operators)
SELECT COUNT(*) FROM bulk_jobs;              -- expect: 0 (populated at runtime by API only)

-- Confirm all migrated range configs are in standalone mode
SELECT COUNT(*) FROM imsi_range_configs WHERE iccid_range_id IS NOT NULL;
-- expect: 0

-- Spot-check 10 random IMSIs from core_extract.csv
SELECT si.imsi, sp.iccid, sp.ip_resolution, sa.apn, sa.static_ip
FROM imsi2sim si
JOIN sim_profiles sp ON sp.sim_id = si.sim_id
JOIN imsi_apn_ips sa  ON sa.imsi = si.imsi
WHERE si.imsi IN ('278773000002002', ...);

-- Verify no pool IP is double-allocated
SELECT static_ip, COUNT(*) FROM imsi_apn_ips
GROUP BY static_ip HAVING COUNT(*) > 1;
-- Expected: 0 rows (each IP belongs to one IMSI+APN combination)

-- Pool utilization sanity
SELECT p.pool_name,
       (p.end_ip - p.start_ip - 1) AS total,
       COUNT(sa.static_ip)          AS allocated,
       COUNT(pa.ip)                 AS available
FROM ip_pools p
LEFT JOIN imsi_apn_ips sa ON sa.pool_id = p.pool_id
LEFT JOIN ip_pool_available   pa ON pa.pool_id = p.pool_id
GROUP BY p.pool_id, p.pool_name, p.start_ip, p.end_ip;
-- allocated + available should equal total for every pool
```

**Go / No-Go gate:**
- [ ] Row counts match Step 2 output file row counts exactly
- [ ] 0 double-allocated IPs
- [ ] Pool utilization: `allocated + available = total` for all pools
- [ ] 10 random IMSI spot-checks return correct static_ip via SQL
- [ ] 10 random IMSI spot-checks return correct `{"static_ip":"..."}` via `GET /lookup` API

---

## Step 4 — Dual-Write Validation Period

**Duration:** Minimum 1–2 weeks (operator decision based on risk tolerance)
**When:** After Step 3 Go/No-Go passes

Configure aaa-radius-server with the two-stage `rlm_rest` config (Stage 1 → `aaa-lookup-service`,
Stage 2 → `subscriber-profile-api /first-connection`), but keep MariaDB as the authoritative
lookup in parallel:

1. On every Access-Request, call `aaa-lookup-service` **and** the existing MariaDB lookup path
2. Use the MariaDB result as authoritative for the Access-Accept (no change to live behaviour)
3. Compare the PostgreSQL result to MariaDB and log any mismatch

```
# Dual-write comparison log format
{
  "ts": "...",
  "imsi_hash": "sha256(imsi)[0:8]",
  "apn": "...",
  "mariadb_ip": "100.65.120.5",
  "postgres_ip": "100.65.120.5",
  "match": true
}
```

A mismatch (`match: false`) indicates a transform or load error and must be investigated
before proceeding to Step 5.

**Metrics to watch during dual-write:**
- Mismatch rate — target: 0%
- `aaa-lookup-service` p99 latency — target: <15ms
- `aaa-lookup-service` error rate — target: 0%
- `subscriber-profile-api /first-connection` latency — target: <100ms (rare event)

**Go / No-Go gate for Step 5:**
- [ ] Zero mismatches for a minimum of 72 consecutive hours at full traffic volume
- [ ] `aaa-lookup-service` p99 < 15ms sustained over 1 week
- [ ] `subscriber-profile-api /first-connection` returning 200 for new IMSIs in range configs
- [ ] All regression tests still passing against the loaded PostgreSQL instance
- [ ] Operators have reviewed and signed off on the mismatch log summary

---

## Step 5 — Cut-Over

**Who:** At least 2 engineers on-call + operator representative
**When:** Booked maintenance window, off-peak hours
**Duration:** ~30 minutes active, 24 hours monitoring

### Cut-Over Runbook

```
T-60 min  Confirm all engineers on call and communications channel open
T-30 min  Final Go/No-Go poll: Step 4 gate items all checked?
T-0       BEGIN MAINTENANCE WINDOW

T+0  min  Notify operations team: "Migration cut-over starting"
T+2  min  Disable new first-connection allocations in MariaDB
           (set all imsi_range_config rows to status=suspended in MariaDB)
T+5  min  Switch aaa-radius-server to two-stage PostgreSQL config:
           Stage 1 → aaa-lookup-service (read-only, hot path)
           Stage 2 → subscriber-profile-api /first-connection (new IMSI allocation)
           Remove MariaDB read path entirely.
T+10 min  Reload aaa-radius-server on all nodes
T+15 min  Confirm: live Access-Requests are flowing through aaa-lookup-service
           - Check access log: all requests returning 200
           - Check latency: p99 < 15ms
           - Check no unexpected 404/503 errors appearing
T+20 min  Disable writes to MariaDB from AAA layer entirely
T+25 min  Final checks (see below)
T+30 min  END MAINTENANCE WINDOW — system is live on PostgreSQL

T+24h     Full review of error rates, latency, mismatch log (now zero expected)
```

**T+25 min final checks:**
```sql
-- PostgreSQL: confirm no new first-connection profiles have NULL sim_id
SELECT COUNT(*) FROM sim_profiles WHERE sim_id IS NULL;  -- expect 0

-- Confirm all migrated range configs remain in standalone mode
SELECT COUNT(*) FROM imsi_range_configs WHERE iccid_range_id IS NOT NULL;  -- expect 0

-- Confirm no stale provisioning modes from migration
SELECT COUNT(*) FROM imsi_range_configs WHERE provisioning_mode != 'first_connect';  -- expect 0

-- Check aaa-lookup-service metrics
-- lookup_result_total{result="not_found"} < pre-cutover baseline
-- lookup_latency_ms p99 < 15ms

-- Check subscriber-profile-api metrics
-- first_connection_total{result="allocated"} increasing (new IMSIs being auto-allocated)
-- first_connection_total{result="pool_exhausted"} = 0
```

### Rollback Procedure

If any check at T+25 fails, or p99 > 50ms, or error rate > 1%:

```
1. Immediately revert aaa-radius-server config to MariaDB read path
2. Reload aaa-radius-server on all nodes
3. Re-enable MariaDB writes
4. Notify operations: "Migration rolled back — MariaDB is authoritative"
5. Investigate root cause before scheduling a new cutover window
6. New PostgreSQL load is unaffected by rollback; Step 3 data is retained
   and can be refreshed with a fresh Step 1–3 run if needed
```

The rollback target is always the pre-cutover MariaDB state. Because Step 3 was additive
(write-only to PostgreSQL) and MariaDB was never modified, rollback is instant.

---

## Step 6 — ICCID Enrichment (Post-Cutover)

**When:** After cutover is stable (within days to weeks)
**Who:** Migration engineer + operator providing updated ICCID map

This step is optional but recommended. It converts `iccid = NULL` profiles to real ICCIDs,
enabling Profile A (`ip_resolution = "iccid"`) and correct Multi-IMSI SIM grouping for
any IMSIs not covered by the original `imsi_iccid_map.csv`.

### Find Remaining NULL-ICCID Profiles

```sql
SELECT si.imsi, sp.sim_id, sp.account_name
FROM imsi2sim si
JOIN sim_profiles sp ON sp.sim_id = si.sim_id
WHERE sp.iccid IS NULL
ORDER BY sp.account_name, si.imsi;
-- Export result to send to operator for ICCID lookup
```

### Apply Real ICCIDs

Operator provides `iccid_map_supplement.csv` with columns: `imsi, real_iccid`

```sql
CREATE TEMP TABLE iccid_mapping (imsi TEXT, real_iccid TEXT);
\COPY iccid_mapping FROM 'iccid_map_supplement.csv' WITH (FORMAT csv, HEADER true);

UPDATE sim_profiles sp
SET    iccid = m.real_iccid, updated_at = now()
FROM   iccid_mapping m
JOIN   imsi2sim si ON si.imsi = m.imsi AND si.sim_id = sp.sim_id
WHERE  sp.iccid IS NULL;

-- Verify
SELECT COUNT(*) FROM sim_profiles WHERE iccid IS NULL;
-- Target: 0 (or reduced to only truly unknown ICCIDs)
```

### Post-Enrichment Options (Operator Decision)

After real ICCIDs are applied, operators may optionally:

1. **Switch single-IP SIM cards to Profile A:** Change `ip_resolution` from `"imsi"` to
   `"iccid"` via `PATCH /profiles/{sim_id}` for SIM cards where all IMSIs share one IP.
   This simplifies the lookup to card-level and eliminates per-IMSI IP rows.

2. **Rename synthetic APN labels:** For profiles with `apn="pgw1"`, `"pgw2"` (from multi-IP
   deduplication in Step 2), update to real APN values via `PATCH /profiles/{sim_id}/imsis/{imsi}`.
   Example: `pgw1` → `internet.operator.com`, `pgw2` → `ims.operator.com`.

Both operations are performed through the standard Provisioning API — no direct DB access required.

---

## Step 7 — MariaDB Decommission

**When:** Minimum 30 days after cutover with zero rollback events and zero mismatches
**Who:** Infrastructure team + operator sign-off

```
1. Take final full backup of all 7 MariaDB dumps (retain for 12 months minimum)
2. Confirm: no application is writing to or reading from any MariaDB cluster
3. Stop MariaDB/Galera processes on all nodes
4. Retain disk snapshots for 30 additional days before deletion
5. Update network security groups to block MariaDB ports (3306)
6. Archive dump files to cold storage
7. Update runbooks and architecture diagrams to remove MariaDB references
```

---

## Migration Test Scenarios (test_09_migration.py)

These are the automated checks the regression suite runs against migration output:

| # | Test | Expected |
|---|---|---|
| 9.1 | Run migration script on Athens-only sample dump | sim_profiles count = distinct ICCID-groups + unmatched IMSIs |
| 9.2 | IMSI in `imsi_iccid_map.csv` → GET /profiles?imsi={imsi} | `iccid` = real ICCID from map |
| 9.3 | IMSI not in map → GET /profiles?imsi={imsi} | `iccid` = null |
| 9.4 | IMSI in 2 dumps, different IPs, same client → GET /profiles?imsi={imsi} | ip_resolution=imsi_apn, 2 apn_ips entries: apn=pgw1, apn=pgw2 |
| 9.5 | IMSI in 2 dumps, same IP → GET /profiles?imsi={imsi} | ip_resolution=imsi, 1 apn_ips entry with apn=null |
| 9.6 | Two IMSIs sharing same ICCID, same client → GET /profiles?imsi={imsi1} and GET /profiles?imsi={imsi2} | Both return same `sim_id` (grouped onto one profile) |
| 9.7 | Range config rows → GET /range-configs?account_name={name} | count = tbl_imsi_range_config rows for that client |
| 9.8 | All migrated range-configs have iccid_range_id = NULL | SELECT COUNT(*) FROM imsi_range_configs WHERE iccid_range_id IS NOT NULL = 0 |
| 9.9 | iccid_range_configs table is empty post-migration | SELECT COUNT(*) FROM iccid_range_configs = 0 |
| 9.10 | Pool stats after load | available = total IPs − allocated; allocated + available = total |
| 9.13 | bulk_jobs table is empty post-migration | SELECT COUNT(*) FROM bulk_jobs = 0 |
| 9.14 | All migrated imsi_range_configs have provisioning_mode = 'first_connect' | SELECT COUNT(*) FROM imsi_range_configs WHERE provisioning_mode != 'first_connect' = 0 |
| 9.11 | GET /lookup?imsi={migrated_imsi}&apn=any via aaa-lookup-service | 200, correct static_ip |
| 9.12 | GET /lookup?imsi={range_config_imsi_not_in_profiles}&apn=any → 404 from aaa-lookup-service, then POST /first-connection (via aaa-radius-server two-stage) | 200, new IP allocated from pool; profile permanently created |

---

## File Inventory Summary

| File | Produced by | Consumed by |
|---|---|---|
| `imsi_iccid_map.csv` | Operator (input) | Step 2 transform |
| `client_id_map.csv` | Step 1 extract | Step 2 transform |
| `staging_pools.csv` | Step 1 extract | Step 2 transform |
| `core_extract.csv` | Step 1 extract | Step 2 transform |
| `staging_ranges.csv` | Step 1 extract | Step 2 transform |
| `pool_map.csv` | Step 2 transform | Step 3 load |
| `out_sim_profiles.csv` | Step 2 transform | Step 3 load |
| `out_imsi2sim.csv` | Step 2 transform | Step 3 load |
| `out_imsi_apn_ips.csv` | Step 2 transform | Step 3 load |
| `out_sim_apn_ips.csv` | Step 2 transform (empty) | Step 3 load (no-op) |
| `out_ip_pools.csv` | Step 2 transform | Step 3 load |
| `out_imsi_range_configs.csv` | Step 2 transform | Step 3 load |
| `migration_audit.log` | Step 2 transform | Review before Step 3 |
| `iccid_map_supplement.csv` | Operator (Step 6 input) | Step 6 enrichment |

---

## Timeline Estimate

| Step | Estimated Duration | Can Overlap Live Traffic? |
|---|---|---|
| Step 1 — Extract | 1–2 hours | Yes |
| Step 2 — Transform | 1–3 hours (script run) | Yes |
| Step 3 — Load | ~3–5 minutes | Yes (writing to PostgreSQL only) |
| Step 4 — Dual-write | 1–2 weeks | Yes (MariaDB still authoritative) |
| Step 5 — Cut-over | 30 minutes + 24h monitoring | Maintenance window |
| Step 6 — ICCID enrichment | Days to weeks (operator-paced) | Yes |
| Step 7 — Decommission | 30+ days post-cutover | Yes |

**Total elapsed time from start to decommission:** 6–10 weeks minimum.
