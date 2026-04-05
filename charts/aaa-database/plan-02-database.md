# Plan 2 — Database

## Technology Decision

**PostgreSQL 15+ on AWS RDS Multi-AZ** — chosen over MongoDB and OpenSearch.

| Requirement | PostgreSQL | MongoDB |
|---|---|---|
| GET by IMSI latency | **1–5ms** (B-tree PK) | 5–15ms (multikey array index) |
| Latency predictability | **Excellent** — deterministic B-tree | GC pauses cause p99 spikes |
| IMSI add/remove | INSERT/DELETE — full ACID | $push/$pull — single-doc ACID only |
| Multi-AZ HA | RDS Multi-AZ sync standby | Replica set election |
| Bulk 300K | COPY + INSERT ON CONFLICT — transactional | bulkWrite — no cross-doc transactions |
| IP uniqueness | UNIQUE constraint | Eventual consistency only |
| Team experience | **YES** | None |

---

## Schema — 10 Tables

### Table 1: sim_profiles

One row per physical SIM card. `sim_id` is the immutable primary key.
`iccid` is optional — NULL for auto-allocated first-connection profiles.

```sql
CREATE TABLE sim_profiles (
    sim_id          UUID        NOT NULL DEFAULT gen_random_uuid(),
    iccid           TEXT        UNIQUE,                 -- 19-20 digits; NULL allowed (multiple NULLs ok)
    account_name    TEXT,                               -- e.g. "Melita"; not required to be unique
    status          TEXT        NOT NULL DEFAULT 'active',
    ip_resolution   TEXT        NOT NULL DEFAULT 'imsi',
    metadata        JSONB,                              -- imei, tags, vrf_group_id, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sim_profiles_pkey PRIMARY KEY (sim_id),
    CONSTRAINT chk_status CHECK (status IN ('active','suspended','terminated')),
    CONSTRAINT chk_ip_resolution CHECK (ip_resolution IN
        ('iccid','iccid_apn','imsi','imsi_apn','multi_imsi_sim','vrf_reuse')),
    CONSTRAINT chk_iccid_format CHECK (iccid IS NULL OR
        (iccid ~ '^\d{19,20}$'))
);

CREATE INDEX idx_sp_iccid         ON sim_profiles (iccid) WHERE iccid IS NOT NULL;
CREATE INDEX idx_sp_account_name  ON sim_profiles (account_name);
CREATE INDEX idx_sp_status        ON sim_profiles (account_name, status);
```

---

### Table 2: imsi2sim

One row per IMSI. Multiple rows may share one `sim_id` (Multi-IMSI SIM card).
`imsi` is the B-tree primary key — this is the AAA hot-path entry point.

```sql
CREATE TABLE imsi2sim (
    imsi        TEXT        NOT NULL,
    sim_id      UUID        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'active',
    priority    SMALLINT    NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT imsi2sim_pkey PRIMARY KEY (imsi),
    CONSTRAINT imsi2sim_sim_fkey
        FOREIGN KEY (sim_id) REFERENCES sim_profiles (sim_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_imsi_status   CHECK (status IN ('active','suspended')),
    CONSTRAINT chk_imsi_15       CHECK (imsi ~ '^\d{15}$')
);

CREATE INDEX idx_si_sim_id ON imsi2sim (sim_id);  -- reverse: device → all IMSIs
```

---

### Table 3: imsi_apn_ips

Per-IMSI static IP assignments. Used by `ip_resolution = "imsi"` or `"imsi_apn"`.

- `apn IS NULL`     → ip_resolution = `"imsi"` (one IP per IMSI, APN ignored)
- `apn IS NOT NULL` → ip_resolution = `"imsi_apn"` (IP per IMSI+APN pair)
- `apn = null` entry alongside specific APN entries acts as wildcard fallback

```sql
CREATE TABLE imsi_apn_ips (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    imsi        TEXT        NOT NULL,
    apn         TEXT,                       -- NULL = APN-agnostic / wildcard
    static_ip   INET        NOT NULL,
    pool_id     UUID,
    pool_name   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT imsi_apn_ips_imsi_fkey
        FOREIGN KEY (imsi) REFERENCES imsi2sim (imsi)
        ON DELETE CASCADE,
    CONSTRAINT uq_apn_ips_imsi_apn UNIQUE NULLS NOT DISTINCT (imsi, apn)
    -- UNIQUE NULLS NOT DISTINCT: only one NULL-apn row per imsi is allowed
    -- Requires PostgreSQL 15+
);

CREATE INDEX idx_sai_imsi ON imsi_apn_ips (imsi);
```

---

### Table 4: sim_apn_ips

Card-level static IP assignments. Used by `ip_resolution = "iccid"` or `"iccid_apn"`.
All IMSIs on the card share these IPs.

- `apn IS NULL`     → ip_resolution = `"iccid"` (one IP for entire card)
- `apn IS NOT NULL` → ip_resolution = `"iccid_apn"` (IP per card+APN pair)

```sql
CREATE TABLE sim_apn_ips (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sim_id      UUID        NOT NULL,
    apn         TEXT,                       -- NULL = all APNs
    static_ip   INET        NOT NULL,
    pool_id     UUID,
    pool_name   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sim_apn_ips_sim_fkey
        FOREIGN KEY (sim_id) REFERENCES sim_profiles (sim_id)
        ON DELETE CASCADE,
    CONSTRAINT uq_iccid_ips_sim_apn UNIQUE NULLS NOT DISTINCT (sim_id, apn)
);

CREATE INDEX idx_sii_sim_id ON sim_apn_ips (sim_id);
```

---

### Table 5: routing_domains

Named uniqueness scopes for IP address assignment. Within one routing domain, no two
pools may have overlapping subnets. `allowed_prefixes` (optional) restricts which
subnets can be created in the domain and enables the suggest-CIDR endpoint.

```sql
CREATE TABLE routing_domains (
    id               UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    name             TEXT        NOT NULL,
    description      TEXT,
    allowed_prefixes TEXT[]      NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_routing_domain_name UNIQUE (name)
);

CREATE INDEX idx_rd_name ON routing_domains (name);

-- Auto-create the default routing domain on DB init
INSERT INTO routing_domains (name, description)
VALUES ('default', 'Default routing domain')
ON CONFLICT (name) DO NOTHING;
```

**`allowed_prefixes` semantics:**
- Empty array (`{}`) = unrestricted — any subnet may be created in this domain.
- Non-empty array = subnet of a new pool must be contained within one of the listed CIDRs.
  Example: `['10.0.0.0/8', '172.16.0.0/12']` restricts pools to RFC 1918 private ranges.
- If a new pool's subnet falls outside all prefixes, the API rejects it with `409 subnet_outside_allowed_prefixes`.
- The `suggest-cidr` endpoint (`GET /routing-domains/{id}/suggest-cidr?size=N`) uses these prefixes as the search space to find a free CIDR block.

---

### Table 6: ip_pools

IP pool definitions. One pool covers one subnet. IPs in the pool are pre-populated
into `ip_pool_available` at pool creation time.

```sql
CREATE TABLE ip_pools (
    pool_id            UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    account_name       TEXT,
    pool_name          TEXT        NOT NULL,
    routing_domain_id  UUID        NOT NULL REFERENCES routing_domains (id),
    subnet             CIDR        NOT NULL,
    start_ip           INET        NOT NULL,
    end_ip             INET        NOT NULL,
    status             TEXT        NOT NULL DEFAULT 'active',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_pool_status CHECK (status IN ('active', 'suspended'))
);

-- Overlap detection: before INSERT, app layer runs:
--   SELECT pool_id, pool_name, subnet FROM ip_pools
--   WHERE routing_domain_id = $routing_domain_id AND subnet && $new_subnet::cidr
-- PostgreSQL && operator on CIDR checks for network overlap (shared addresses).
-- If any row is returned → reject with 409 pool_overlap.

CREATE INDEX idx_pools_account           ON ip_pools (account_name);
CREATE INDEX idx_pools_routing_domain_id ON ip_pools (routing_domain_id);
```

**Pool creation backward compatibility:**
- `POST /pools` still accepts `routing_domain` (name string) for backward compatibility.
  If the named domain doesn't exist it is auto-created with empty `allowed_prefixes`.
- `routing_domain_id` (UUID) takes priority if both are supplied.

---

### Table 7: ip_pool_available

Work-queue of unallocated IPs. Pre-populated at pool creation.
`SELECT FOR UPDATE SKIP LOCKED` prevents race conditions during concurrent allocation.

```sql
CREATE TABLE ip_pool_available (
    pool_id     UUID    NOT NULL REFERENCES ip_pools (pool_id) ON DELETE CASCADE,
    ip          INET    NOT NULL,
    PRIMARY KEY (pool_id, ip)
);
```

**Pre-population (runs once at pool creation time):**
```sql
INSERT INTO ip_pool_available (pool_id, ip)
SELECT $pool_id, (p.start_ip + n)::INET
FROM   ip_pools p,
       generate_series(1, p.end_ip - p.start_ip - 1) AS n
WHERE  p.pool_id = $pool_id;
-- n=0 = network address (skipped by starting at 1)
-- n=max = broadcast (skipped by ending at end_ip - start_ip - 1)
```

---

### Table 8: iccid_range_configs

Parent table for Multi-IMSI SIM provisioning. Each row defines a range of ICCIDs
(physical SIM cards) that carry multiple IMSIs. The associated IMSI ranges are
child rows in `imsi_range_configs` linked via `iccid_range_id`.

Single-IMSI ranges have no entry here — they use standalone `imsi_range_configs`
rows with `iccid_range_id = NULL` (backward-compatible, no schema change needed
for existing data).

**`ip_resolution` authority rules:**

| Situation | Authoritative source |
|---|---|
| Standalone IMSI range (`iccid_range_id IS NULL`) | `imsi_range_configs.ip_resolution` |
| Multi-IMSI SIM group (`iccid_range_id IS NOT NULL`) | `iccid_range_configs.ip_resolution` — child `imsi_range_configs` rows **must have `ip_resolution` set to the same value** (enforced at API layer); the parent value is what the first-connection transaction uses |

This prevents inconsistency where different IMSI slots on the same physical card declare
conflicting resolution modes. The API rejects any child slot addition or update whose
`ip_resolution` differs from its parent `iccid_range_configs` row.

```sql
CREATE TABLE iccid_range_configs (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_name    TEXT,
    f_iccid         TEXT        NOT NULL,   -- from ICCID (inclusive, 19-20 digits)
    t_iccid         TEXT        NOT NULL,   -- to ICCID (inclusive, 19-20 digits)
    pool_id         UUID        REFERENCES ip_pools (pool_id),  -- nullable: each slot may define its own pool
    ip_resolution   TEXT        NOT NULL DEFAULT 'imsi',
    imsi_count      SMALLINT    NOT NULL DEFAULT 1,  -- number of IMSIs per card (1–10)
    description     TEXT,
    status          TEXT        NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_iccid_range_status CHECK (status IN ('active', 'suspended')),
    CONSTRAINT chk_iccid_range_ip_res CHECK (ip_resolution IN ('imsi','imsi_apn','iccid','iccid_apn')),
    CONSTRAINT chk_f_iccid_format CHECK (f_iccid ~ '^\d{19,20}$'),
    CONSTRAINT chk_t_iccid_format CHECK (t_iccid ~ '^\d{19,20}$'),
    CONSTRAINT chk_iccid_range_order CHECK (f_iccid <= t_iccid),
    CONSTRAINT chk_imsi_count CHECK (imsi_count BETWEEN 1 AND 10)
);

CREATE INDEX idx_iccid_rc_account   ON iccid_range_configs (account_name);
CREATE INDEX idx_iccid_rc_range     ON iccid_range_configs (f_iccid, t_iccid);
```

---

### Table 9: imsi_range_configs

IMSI range authorization table. Each row defines one IMSI range eligible for dynamic
first-connection allocation.

**Two usage modes:**

- `iccid_range_id IS NULL` — standalone single-IMSI range (legacy / simple case).
  Behaviour is identical to the original design. All migrated rows from MariaDB use this mode.

- `iccid_range_id IS NOT NULL` — child of a Multi-IMSI SIM ICCID range.
  `imsi_slot` identifies which position this IMSI occupies on the card (1 = primary,
  2 = secondary, …, up to 10). All child ranges for the same `iccid_range_id` **must
  have identical cardinality** (same number of IMSIs: `t_imsi - f_imsi` must be equal
  across all slots). This is enforced at the API layer on create/update.

```sql
CREATE TABLE imsi_range_configs (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_name    TEXT,
    f_imsi          TEXT        NOT NULL,   -- from IMSI (inclusive, 15 digits)
    t_imsi          TEXT        NOT NULL,   -- to IMSI (inclusive, 15 digits)
    pool_id         UUID        REFERENCES ip_pools (pool_id),  -- nullable: slot uses APN-pool routing when NULL; overrides parent iccid_range_configs.pool_id
    ip_resolution   TEXT        NOT NULL DEFAULT 'imsi',
    iccid_range_id  BIGINT      REFERENCES iccid_range_configs (id) ON DELETE CASCADE,
    imsi_slot       SMALLINT    NOT NULL DEFAULT 1,  -- 1=primary … 10=tenth IMSI on card
    description     TEXT,
    status          TEXT        NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_range_status CHECK (status IN ('active', 'suspended')),
    CONSTRAINT chk_range_ip_resolution CHECK (ip_resolution IN ('imsi','imsi_apn','iccid','iccid_apn')),
    CONSTRAINT chk_f_imsi_15 CHECK (f_imsi ~ '^\d{15}$'),
    CONSTRAINT chk_t_imsi_15 CHECK (t_imsi ~ '^\d{15}$'),
    CONSTRAINT chk_range_order CHECK (f_imsi <= t_imsi),
    CONSTRAINT chk_imsi_slot CHECK (imsi_slot BETWEEN 1 AND 10),
    -- Within a multi-IMSI group, each slot number must be unique
    CONSTRAINT uq_iccid_range_slot UNIQUE (iccid_range_id, imsi_slot)
);

CREATE INDEX idx_irc_account       ON imsi_range_configs (account_name);
CREATE INDEX idx_irc_imsi_range    ON imsi_range_configs (f_imsi, t_imsi);
CREATE INDEX idx_irc_iccid_range   ON imsi_range_configs (iccid_range_id);
-- Note: TEXT comparison is valid because all IMSIs are exactly 15 digits —
-- enforced by chk_f_imsi_15 / chk_t_imsi_15, no zero-padding ambiguity.
```

**Example — one ICCID range with 2 IMSI slots per card:**

```sql
-- Parent: 1,000,000 SIM cards, each carrying 2 IMSIs
INSERT INTO iccid_range_configs
    (account_name, f_iccid, t_iccid, pool_id, ip_resolution, imsi_count, description)
VALUES
    ('Melita', '8944501010000000000', '8944501010999999999',
     'pool-uuid-abc', 'imsi', 2, 'Melita dual-IMSI IoT batch 2026');
-- Returns id = 1

-- Slot 1 — primary IMSI range (1,000,000 IMSIs, matches ICCID cardinality)
INSERT INTO imsi_range_configs
    (account_name, f_imsi, t_imsi, pool_id, ip_resolution, iccid_range_id, imsi_slot)
VALUES
    ('Melita', '278770000000000', '278770000999999', 'pool-uuid-abc', 'imsi', 1, 1);

-- Slot 2 — secondary IMSI range (same cardinality: 1,000,000 IMSIs)
INSERT INTO imsi_range_configs
    (account_name, f_imsi, t_imsi, pool_id, ip_resolution, iccid_range_id, imsi_slot)
VALUES
    ('Melita', '278771000000000', '278771000999999', 'pool-uuid-abc', 'imsi', 1, 2);

-- The offset within each range maps to the same physical card:
-- ICCID offset 0 (8944501010000000000) → IMSI slot-1 offset 0 (278770000000000)
--                                       + IMSI slot-2 offset 0 (278771000000000)
-- ICCID offset 1 (8944501010000000001) → IMSI slot-1 offset 1 (278770000000001)
--                                       + IMSI slot-2 offset 1 (278771000000001)
```

---

### Table 10: range_config_apn_pools

Per-APN pool overrides for a specific `imsi_range_configs` entry. When
`ip_resolution` is `"imsi_apn"` or `"iccid_apn"`, the first-connection allocation
looks up this table before using the range config's default `pool_id`. This enables
different APNs to draw IPs from different pools for the same IMSI range.

**Example:** IMSI range with `ip_resolution = "imsi_apn"`, plus two overrides:
- `apn = "apn1"` → pool `10.0.0.0/24`
- `apn = "apn2"` → pool `11.0.0.0/24`

On first-connection, each APN gets an IP from its designated pool automatically.

Also applies per-slot: in a Multi-IMSI SIM group, each `imsi_range_configs` slot can
independently define APN→pool overrides. The sibling pre-provisioning loop resolves
the override for each sibling slot independently.

```sql
CREATE TABLE range_config_apn_pools (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    range_config_id BIGINT      NOT NULL REFERENCES imsi_range_configs (id)
                                ON DELETE CASCADE,
    apn             TEXT        NOT NULL,
    pool_id         UUID        NOT NULL REFERENCES ip_pools (pool_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_range_config_apn UNIQUE (range_config_id, apn)
);

CREATE INDEX idx_rcap_range_config ON range_config_apn_pools (range_config_id);
```

---

### Auto-Update Trigger (all tables)

```sql
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;

CREATE TRIGGER trg_sp_updated_at      BEFORE UPDATE ON sim_profiles         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_si_updated_at      BEFORE UPDATE ON imsi2sim             FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_sai_updated_at     BEFORE UPDATE ON imsi_apn_ips         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_sii_updated_at     BEFORE UPDATE ON sim_apn_ips          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_rd_updated_at      BEFORE UPDATE ON routing_domains      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_pools_updated_at   BEFORE UPDATE ON ip_pools             FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_iccid_rc_updated_at BEFORE UPDATE ON iccid_range_configs FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_irc_updated_at     BEFORE UPDATE ON imsi_range_configs   FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

---

## Schema Initialization

`db-init.sh` (`scripts/db-init.sh`) is the **sole schema initializer**. CNPG's `initdb`
only creates the database and `aaa_app` owner — it does not run any SQL.
`make setup` and `make db-init` both call `db-init.sh`, which:

1. Drops stale tables from superseded schema generations (idempotent)
2. Runs column migrations for pre-existing clusters (idempotent — skipped on fresh clusters)
3. Applies the full schema SQL from the `aaa-postgres-initdb-sql` ConfigMap
4. Sets `ALTER DEFAULT PRIVILEGES` for `aaa_app`

### Column migration history — `ip_pools`

| Generation | Cluster state | Migration action |
|---|---|---|
| Fresh | `ip_pools` not yet created | Skip — schema SQL creates it with `routing_domain_id` correctly |
| Gen-1 | `ip_pools` exists, no routing column | Add `routing_domain_id` UUID FK; assign all existing rows to the `default` domain |
| Gen-2 | `ip_pools` has `routing_domain TEXT` | Seed `routing_domains` rows from distinct values, then replace column with `routing_domain_id` UUID FK |
| Gen-3 / current | `ip_pools` has `routing_domain_id UUID` | Skip — already current |

---

## AAA Hot-Path Lookup Query

### Fast Path for IP Lookup

Every RADIUS/Diameter Access-Request follows this resolution chain:

```
IMSI (from Access-Request)
  ↓
imsi2sim          — B-tree PK lookup → yields sim_id + imsi_status
  ↓
sim_profiles      — PK join → yields ip_resolution + sim_status
  ↓
[ip_resolution]
   │
   ├── imsi / imsi_apn  →  imsi_apn_ips   (keyed by IMSI + optional APN)
   │
   └── iccid / iccid_apn → sim_apn_ips   (keyed by sim_id/ICCID + optional APN)
```

- The lookup always enters via **IMSI** — it is the sole AAA entry point.
- `imsi2sim` resolves IMSI → `sim_id`; `sim_profiles.ip_resolution` then selects which IP table to read.
- `imsi_apn_ips` is used when the profile is bound to the **IMSI** identity (`imsi` / `imsi_apn` modes): one IP row per IMSI, optionally further qualified by APN.
- `sim_apn_ips` (aliased "iccid" tables) is used when the profile is bound to the **physical card** identity (`iccid` / `iccid_apn` modes): one IP row per `sim_id`, shared by all IMSIs on that card.
- Both IP tables are left-joined in a single query so the application layer can pick the right column without a second round-trip.

Executed on every RADIUS/Diameter Access-Request. Covers all three production profiles
in a single query — the application layer selects the correct row from the result set.

```sql
-- $1 = IMSI from Access-Request (always present)
-- $2 = APN  from Access-Request (always present; ignored depending on ip_resolution)
SELECT
    sp.sim_id,
    sp.status           AS sim_status,
    sp.ip_resolution,
    si.status           AS imsi_status,
    sa.apn              AS imsi_apn,
    sa.static_ip        AS imsi_static_ip,
    sa.pool_id          AS imsi_pool_id,
    ci.apn              AS iccid_apn,
    ci.static_ip        AS iccid_static_ip,
    ci.pool_id          AS iccid_pool_id
FROM        imsi2sim          si
JOIN        sim_profiles       sp  ON sp.sim_id = si.sim_id
LEFT JOIN   imsi_apn_ips      sa  ON sa.imsi = si.imsi
LEFT JOIN   sim_apn_ips       ci  ON ci.sim_id = sp.sim_id
WHERE si.imsi = $1;
```

**Expected performance:** p50 1–3ms / p99 3–8ms
Index path: B-tree seek on `imsi2sim.imsi` (PK) → nested loop join to
`sim_profiles` (sim_id PK) → left-join both IP tables (low cardinality per IMSI).

The entire `imsi2sim` index (~80MB for 1M rows) fits in PostgreSQL `shared_buffers`;
near 100% cache-hit rate at steady state.

---

## Resolution Scenarios — ICCID Dual-IMSI (16 outcomes)

The two LEFT JOINs in the hot-path query produce a Cartesian product:
`|imsi_apn_ips rows for this IMSI| × |sim_apn_ips rows for this sim_id|` result rows.
If one side has no matching rows the LEFT JOIN still emits one result row with NULLs for
that side's columns. The application layer iterates all rows and inspects only the columns
relevant to `ip_resolution`.

### DB layout for this scenario

```
sim_profiles:  sim_id = 42,  ip_resolution = <see per-mode table below>,  status = active

imsi2sim:
  IMSI-A  →  sim_id = 42
  IMSI-B  →  sim_id = 42

─── imsi_apn_ips (only populated for imsi / imsi_apn modes) ─────────────────────────────

  mode = imsi:
    IMSI-A │ apn = NULL    │ 100.65.1.10      ← single wildcard row, APN ignored
    IMSI-B │ apn = NULL    │ 100.65.2.10

  mode = imsi_apn:
    IMSI-A │ apn = apn1.net │ 100.65.1.11     ← per-APN rows, no wildcard
    IMSI-A │ apn = apn2.net │ 100.65.1.12
    IMSI-B │ apn = apn1.net │ 100.65.2.11
    IMSI-B │ apn = apn2.net │ 100.65.2.12

─── sim_apn_ips (only populated for iccid / iccid_apn modes) ────────────────────────────

  mode = iccid:
    sim_id = 42 │ apn = NULL    │ 100.65.3.10  ← single wildcard row, APN ignored

  mode = iccid_apn:
    sim_id = 42 │ apn = apn1.net │ 100.65.3.11 ← per-APN rows, no wildcard
    sim_id = 42 │ apn = apn2.net │ 100.65.3.12
```

### Query result rows returned for an IMSI-A request

**`imsi` mode** — 1 row

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
NULL      100.65.1.10     NULL       NULL
```

**`imsi_apn` mode** — 2 rows

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
apn1.net  100.65.1.11     NULL       NULL
apn2.net  100.65.1.12     NULL       NULL
```

**`iccid` mode** — 1 row

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
NULL      NULL            NULL       100.65.3.10
```

**`iccid_apn` mode** — 2 rows

```
imsi_apn  imsi_static_ip  iccid_apn  iccid_static_ip
NULL      NULL            apn1.net   100.65.3.11
NULL      NULL            apn2.net   100.65.3.12
```

### 16-outcome matrix (4 requests × 4 modes)

| Request | `imsi` | `imsi_apn` | `iccid` | `iccid_apn` |
|---|---|---|---|---|
| IMSI-A, apn1.net | 200 `100.65.1.10` (APN ignored) | 200 `100.65.1.11` (exact match) | 200 `100.65.3.10` (APN ignored) | 200 `100.65.3.11` (exact match) |
| IMSI-A, apn2.net | 200 `100.65.1.10` (APN ignored) | 200 `100.65.1.12` (exact match) | 200 `100.65.3.10` (APN ignored) | 200 `100.65.3.12` (exact match) |
| IMSI-B, apn1.net | 200 `100.65.2.10` (APN ignored) | 200 `100.65.2.11` (exact match) | 200 `100.65.3.10` (APN ignored, same card) | 200 `100.65.3.11` (exact match, same card) |
| IMSI-B, apn2.net | 200 `100.65.2.10` (APN ignored) | 200 `100.65.2.12` (exact match) | 200 `100.65.3.10` (APN ignored, same card) | 200 `100.65.3.12` (exact match, same card) |

`imsi` / `imsi_apn` modes give **different** IPs to IMSI-A and IMSI-B — each owns its own
`imsi_apn_ips` rows. `iccid` / `iccid_apn` modes give the **same** IP to both — they share
the card's `sim_apn_ips` rows. An unrecognised APN with no wildcard row returns
`404 apn_not_found` in `imsi_apn` and `iccid_apn` modes.

---

## First-Connection Allocation — Write Transaction

Triggered by `subscriber-profile-api` via `POST /first-connection` when
`aaa-lookup-service` returns 404 for an unknown IMSI and aaa-radius-server falls
through to the provisioning service.  All writes go to `PRIMARY_URL`.
`aaa-lookup-service` is read-only and never touches this transaction.

### Idempotency Pre-Check (before any allocation)

Before touching the range config or allocating an IP, the service checks whether
the IMSI is already provisioned.  This is the fast path for retries and for
subscribers whose profile was created by a sibling IMSI.

```sql
-- Single indexed read; no transaction needed.
SELECT i.sim_id::text, sp.ip_resolution
FROM   imsi2sim      i
JOIN   sim_profiles  sp ON sp.sim_id = i.sim_id
WHERE  i.imsi = $imsi;
```

If a row is returned, the correct IP table is chosen based on the profile's
**current** `ip_resolution` — not the one it was originally created with.
This is critical after a PATCH that switches a profile from `imsi` to `iccid`
mode: the old `imsi_apn_ips` row is left intact (to preserve audit history),
so naively querying `imsi_apn_ips` first would return a stale IP.

```sql
-- ip_resolution IN ('imsi', 'imsi_apn')
SELECT host(static_ip) FROM imsi_apn_ips
WHERE  imsi = $imsi AND (apn = $apn OR apn IS NULL)
ORDER BY apn NULLS LAST LIMIT 1;

-- ip_resolution IN ('iccid', 'iccid_apn')
SELECT host(static_ip) FROM sim_apn_ips
WHERE  sim_id = $sim_id AND (apn = $apn OR apn IS NULL)
ORDER BY apn NULLS LAST LIMIT 1;
```

→ Return 200 `{sim_id, static_ip}` — no write, no allocation.

### Single-IMSI SIM (standalone `imsi_range_configs` row, `iccid_range_id IS NULL`)

```sql
BEGIN;

-- Step 1: confirm IMSI is in an active range config; fetch pool AND ip_resolution
SELECT irc.pool_id, irc.ip_resolution, irc.account_name,
       irc.iccid_range_id   -- NULL for single-IMSI path
FROM   imsi_range_configs irc
WHERE  irc.f_imsi <= $imsi AND irc.t_imsi >= $imsi
  AND  irc.status = 'active'
ORDER BY irc.f_imsi LIMIT 1;
-- Not found → ROLLBACK → return 404
-- $ip_resolution now holds the operator-configured value: 'imsi','imsi_apn','iccid','iccid_apn'

-- Step 2: claim one IP (race-condition-safe)
DELETE FROM ip_pool_available
WHERE ip = (
    SELECT ip FROM ip_pool_available
    WHERE  pool_id = $pool_id
    ORDER BY ip LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING ip INTO $allocated_ip;
-- NULL returned → pool exhausted → ROLLBACK → return 503

-- Step 3: create profile using the range-configured ip_resolution
INSERT INTO sim_profiles (account_name, status, ip_resolution, metadata)
VALUES ($account_name, 'active', $ip_resolution,
        jsonb_build_object('tags', '["auto-allocated"]', 'imei', $imei))
RETURNING sim_id INTO $new_sim_id;

INSERT INTO imsi2sim (imsi, sim_id, status, priority)
VALUES ($imsi, $new_sim_id, 'active', 1);

-- Step 4: store the IP in the correct table based on ip_resolution
IF $ip_resolution IN ('imsi', 'imsi_apn'):
    INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id)
    VALUES (
        $imsi,
        CASE $ip_resolution
            WHEN 'imsi'     THEN NULL          -- APN-agnostic; any APN matches
            WHEN 'imsi_apn' THEN $apn          -- store the APN from the Access-Request
        END,
        $allocated_ip,
        $pool_id
    );

ELSIF $ip_resolution IN ('iccid', 'iccid_apn'):
    -- Card-level IP: goes into sim_apn_ips, not imsi_apn_ips
    INSERT INTO sim_apn_ips (sim_id, apn, static_ip, pool_id)
    VALUES (
        $new_sim_id,
        CASE $ip_resolution
            WHEN 'iccid'     THEN NULL         -- APN-agnostic card-level IP
            WHEN 'iccid_apn' THEN $apn         -- APN-specific card-level IP
        END,
        $allocated_ip,
        $pool_id
    );
    -- No imsi_apn_ips row needed; aaa-lookup-service reads sim_apn_ips

COMMIT;
-- Return $allocated_ip to aaa-radius-server → Access-Accept
```

**`ip_resolution` mapping for first-connection allocation:**

| Range config `ip_resolution` | Profile created with | IP stored in | `apn` value |
|---|---|---|---|
| `imsi` | `ip_resolution='imsi'` | `imsi_apn_ips` | `NULL` (wildcard) |
| `imsi_apn` | `ip_resolution='imsi_apn'` | `imsi_apn_ips` | APN from Access-Request |
| `iccid` | `ip_resolution='iccid'` | `sim_apn_ips` | `NULL` (wildcard) |
| `iccid_apn` | `ip_resolution='iccid_apn'` | `sim_apn_ips` | APN from Access-Request |

The created profile is immediately queryable by `aaa-lookup-service` using the same
hot-path SQL — no schema change to the read path is needed.

### Multi-IMSI SIM (`iccid_range_id IS NOT NULL`)

When the matched `imsi_range_configs` row has `iccid_range_id` set, the arriving
IMSI belongs to a physical SIM card that carries multiple IMSIs.  The service must:

1. Derive which physical card this IMSI belongs to (via offset arithmetic)
2. Either find the existing profile for that card, or create it with one allocated IP
3. Register this IMSI on the card (if not already there)
4. Pre-provision all sibling IMSIs for the same card in the same transaction

`ip_resolution` is taken from `iccid_range_configs` (the parent), not from the matched
child `imsi_range_configs` row. This is the single source of truth for the card's resolution
mode. All sibling IMSI rows are written with the same APN routing.

```sql
BEGIN;

-- Step 1: get the matched child range + its parent iccid_range_configs row
--         ip_resolution comes from the PARENT (ir.*), not the child (irc.*)
SELECT irc.id            AS range_id,
       irc.f_imsi,
       irc.iccid_range_id,
       irc.imsi_slot,
       ir.pool_id,
       ir.ip_resolution,   -- ← authoritative for this card group
       ir.account_name,
       ir.f_iccid,
       ir.imsi_count
FROM   imsi_range_configs   irc
JOIN   iccid_range_configs  ir  ON ir.id = irc.iccid_range_id
WHERE  irc.f_imsi <= $imsi AND irc.t_imsi >= $imsi
  AND  irc.status = 'active'
ORDER BY irc.f_imsi LIMIT 1;

-- Step 2: compute card offset and derive ICCID
-- offset = numeric($imsi) - numeric(irc.f_imsi)
-- derived_iccid = lpad((numeric(ir.f_iccid) + offset)::text, length(ir.f_iccid), '0')

-- Step 3: check if a profile already exists for this derived ICCID
SELECT sim_id FROM sim_profiles
WHERE iccid = $derived_iccid
FOR UPDATE;   -- lock to prevent concurrent creation for same card

IF found:
    -- Card already exists (another IMSI slot connected first).
    -- Register this IMSI on the existing device; reuse the existing IP.
    INSERT INTO imsi2sim (imsi, sim_id, status, priority)
    VALUES ($imsi, $existing_sim_id, 'active', $imsi_slot)
    ON CONFLICT (imsi) DO NOTHING;

    -- Copy the existing card IP to this IMSI using the same ip_resolution routing
    IF $ip_resolution IN ('imsi', 'imsi_apn'):
        INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id)
        SELECT $imsi,
               CASE $ip_resolution
                   WHEN 'imsi'     THEN NULL
                   WHEN 'imsi_apn' THEN $apn
               END,
               sa.static_ip, sa.pool_id
        FROM   imsi_apn_ips sa
        JOIN   imsi2sim      si ON si.imsi = sa.imsi
        WHERE  si.sim_id = $existing_sim_id LIMIT 1
        ON CONFLICT DO NOTHING;

    -- iccid / iccid_apn: sim_apn_ips already has one card-level row;
    -- nothing more to insert for this IMSI.

ELSE:
    -- First IMSI slot from this card: allocate one IP for the entire card.
    DELETE FROM ip_pool_available
    WHERE ip = (SELECT ip FROM ip_pool_available
                WHERE pool_id = $pool_id ORDER BY ip LIMIT 1
                FOR UPDATE SKIP LOCKED)
    RETURNING ip INTO $allocated_ip;
    -- NULL → ROLLBACK → 503

    INSERT INTO sim_profiles
        (account_name, status, ip_resolution, iccid, metadata)
    VALUES ($account_name, 'active', $ip_resolution, $derived_iccid,
            jsonb_build_object('tags', '["auto-allocated","multi-imsi"]', 'imei', $imei))
    RETURNING sim_id INTO $new_sim_id;

    -- Store IP at card or IMSI level depending on ip_resolution
    IF $ip_resolution IN ('iccid', 'iccid_apn'):
        -- One card-level row covers all IMSIs on this card
        INSERT INTO sim_apn_ips (sim_id, apn, static_ip, pool_id)
        VALUES (
            $new_sim_id,
            CASE $ip_resolution WHEN 'iccid' THEN NULL WHEN 'iccid_apn' THEN $apn END,
            $allocated_ip, $pool_id
        );

    -- Register the connecting IMSI and store its IP first.
    INSERT INTO imsi2sim (imsi, sim_id, status, priority)
    VALUES ($imsi, $new_sim_id, 'active', $imsi_slot);

    IF $ip_resolution IN ('imsi', 'imsi_apn'):
        INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id)
        VALUES ($imsi,
                CASE $ip_resolution WHEN 'imsi' THEN NULL WHEN 'imsi_apn' THEN $apn END,
                $allocated_ip, $pool_id);

    -- Pre-provision all OTHER sibling IMSI slots for this card.
    -- Each sibling gets its own IP allocated from its own slot pool.
    -- Pool precedence: slot pool_id → parent pool_id (fallback).
    -- APN overrides (range_config_apn_pools) are checked per slot for imsi_apn/iccid_apn.
    FOR each sibling_range IN (
        SELECT id, f_imsi, imsi_slot, pool_id FROM imsi_range_configs
        WHERE  iccid_range_id = $iccid_range_id AND status = 'active'
          AND  id != $connecting_range_config_id   -- exclude the connecting slot
    ) LOOP
        sibling_imsi  = lpad((numeric(sibling_range.f_imsi) + offset)::text, 15, '0');
        sibling_pool  = COALESCE(sibling_range.pool_id, $pool_id);  -- slot pool or fallback

        -- Apply APN pool override for this sibling slot if defined
        IF $ip_resolution IN ('imsi_apn', 'iccid_apn'):
            sibling_pool = COALESCE(
                (SELECT pool_id FROM range_config_apn_pools
                 WHERE range_config_id = sibling_range.id AND apn = $apn),
                sibling_pool);

        INSERT INTO imsi2sim (imsi, sim_id, status, priority)
        VALUES (sibling_imsi, $new_sim_id, 'active', sibling_range.imsi_slot)
        ON CONFLICT (imsi) DO NOTHING;

        IF $ip_resolution IN ('imsi', 'imsi_apn'):
            -- Allocate a fresh IP for this sibling from its own pool.
            DELETE FROM ip_pool_available
            WHERE ip = (SELECT ip FROM ip_pool_available
                        WHERE pool_id = sibling_pool ORDER BY ip LIMIT 1
                        FOR UPDATE SKIP LOCKED)
            RETURNING ip INTO $sibling_ip;
            -- NULL → ROLLBACK → 503

            INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id)
            VALUES (sibling_imsi,
                    CASE $ip_resolution WHEN 'imsi' THEN NULL WHEN 'imsi_apn' THEN $apn END,
                    $sibling_ip, sibling_pool)
            ON CONFLICT DO NOTHING;
        -- iccid / iccid_apn: the single sim_apn_ips row already covers all IMSIs

    END LOOP;

COMMIT;
-- Return $allocated_ip to aaa-radius-server → Access-Accept
```

**Key properties of the multi-IMSI transaction:**
- `ip_resolution` sourced exclusively from the parent `iccid_range_configs` row — consistent across all slots on the same card
- Parent `iccid_range_configs.pool_id` is nullable; each child `imsi_range_configs` slot defines its own `pool_id` (fallback to parent if set)
- Pool resolution precedence: **slot pool** (`imsi_range_configs.pool_id`) → parent pool (`iccid_range_configs.pool_id`)
- For `iccid`/`iccid_apn` mode: one IP allocated from the connecting slot's pool; one `sim_apn_ips` row covers all IMSIs on the card
- For `imsi`/`imsi_apn` mode: **each slot gets its own IP allocated from its own pool** — connecting IMSI is handled first, then each sibling gets a fresh allocation from its pool in the same transaction
- APN pool overrides (`range_config_apn_pools`) are resolved per slot during sibling pre-provisioning
- All sibling IMSIs pre-provisioned in the same transaction — subsequent connections (including mass failover storms) always hit the `aaa-lookup-service` fast read path (single indexed read, no allocation)
- `FOR UPDATE` on the ICCID check prevents two concurrent connections from the same card racing to create duplicate profiles

---

## IMSI Add / Remove

```sql
-- Add IMSI to existing SIM (one transaction)
BEGIN;
INSERT INTO imsi2sim (imsi, sim_id, status, priority)
    VALUES ('278773000002005', '550e8400-e29b-41d4-a716-446655440000', 'active', 2);
INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id, pool_name)
    VALUES ('278773000002005', NULL, '100.65.120.6', 'pool-uuid-abc', 'Melita-internet-pool');
COMMIT;

-- Remove IMSI (CASCADE removes imsi_apn_ips automatically)
DELETE FROM imsi2sim WHERE imsi = '278773000002005';

-- Enrich NULL iccid with real value
UPDATE sim_profiles
SET iccid = '8944501012345678901', updated_at = now()
WHERE sim_id = '550e8400-e29b-41d4-a716-446655440000';
```

---

## Bulk Provisioning — 300K Profiles

```sql
-- Idempotent upsert via staging table (columns defined explicitly — do NOT use LIKE INCLUDING ALL
-- because that copies GENERATED ALWAYS AS IDENTITY which blocks loading pre-generated sim_ids)
CREATE TEMP TABLE staging_profiles (
    sim_id          UUID,
    iccid           TEXT,
    account_name    TEXT,
    status          TEXT,
    ip_resolution   TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ
);

\COPY staging_profiles FROM 'batch.csv' WITH (FORMAT csv, HEADER true);

INSERT INTO sim_profiles
    SELECT * FROM staging_profiles
    ON CONFLICT (sim_id) DO UPDATE
    SET status=EXCLUDED.status, ip_resolution=EXCLUDED.ip_resolution,
        metadata=EXCLUDED.metadata, updated_at=now();

-- Repeat for imsi2sim, imsi_apn_ips, sim_apn_ips
```

**Expected time:** ~3–5 minutes for 300K rows across 4 tables.

---

## HA / DR Configuration

```
Multi-AZ (single region):
  RDS Multi-AZ — synchronous streaming replication to standby in separate AZ
  Automatic DNS failover on primary failure — ~30s RTO
  subscriber-profile-api connects to cluster endpoint (auto-redirected on failover)

Multi-region (DR + read locality):
  RDS read replica per region (EU, US, APAC)
  Replication lag typically <100ms (low-write workload)
  aaa-lookup-service connects to LOCAL read replica (read-only, no primary connection):
    EU AAA → EU read replica
    US AAA → US read replica
  subscriber-profile-api connects to primary (all writes including first-connection allocation)
  All writes → primary region RDS primary
  DR failover: promote regional read replica → new primary
    (RDS "Promote Read Replica" — manual or Route 53 health-check automated)

Connection pooling:
  PgBouncer in transaction-mode as sidecar alongside each app container
  Pool size: 5–10 server connections per container replica
  (PostgreSQL handles 100–200 max_connections; PgBouncer keeps actual connections low)
```

---

## Read / Write Latency Summary

| Operation | Latency | Mechanism |
|---|---|---|
| AAA: IMSI lookup (all profiles) | 1–5ms p50, 3–8ms p99 | PK seek on `imsi2sim`, 2-table join |
| AAA: ICCID lookup (Profile A) | 1–3ms | PK seek on `sim_profiles`, left-join `sim_apn_ips` |
| Provisioning: GET full profile | 2–8ms | Same joins, all rows returned |
| Provisioning: add/remove IMSI | 3–10ms | Transactional INSERT/DELETE |
| Provisioning: update SIM status | 1–3ms | Single UPDATE on `sim_profiles` |
| First-connection allocation | 5–20ms | Write transaction in `subscriber-profile-api` on primary (rare event) |
| Bulk upsert 300K | ~3–5 min total | COPY + INSERT ON CONFLICT, 4 tables |
| Pool stats query | <200ms at 300K rows | Aggregate on `imsi_apn_ips.pool_id` |

## PostgreSQL Version Requirement

**PostgreSQL 15 minimum.** Required for `UNIQUE NULLS NOT DISTINCT` on `imsi_apn_ips`
and `sim_apn_ips`. This constraint ensures only one NULL-apn wildcard entry per
IMSI (or per SIM). Earlier PostgreSQL versions treat all NULLs as distinct in UNIQUE
indexes, which would allow duplicate wildcard rows.
