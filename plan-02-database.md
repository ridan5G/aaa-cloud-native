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

## Schema — 8 Tables

### Table 1: subscriber_profiles

One row per physical SIM card. `device_id` is the immutable primary key.
`iccid` is optional — NULL for auto-allocated first-connection profiles.

```sql
CREATE TABLE subscriber_profiles (
    device_id       UUID        NOT NULL DEFAULT gen_random_uuid(),
    iccid           TEXT        UNIQUE,                 -- 19-20 digits; NULL allowed (multiple NULLs ok)
    account_name    TEXT,                               -- e.g. "Melita"; not required to be unique
    status          TEXT        NOT NULL DEFAULT 'active',
    ip_resolution   TEXT        NOT NULL DEFAULT 'imsi',
    metadata        JSONB,                              -- imei, tags, vrf_group_id, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT subscriber_profiles_pkey PRIMARY KEY (device_id),
    CONSTRAINT chk_status CHECK (status IN ('active','suspended','terminated')),
    CONSTRAINT chk_ip_resolution CHECK (ip_resolution IN
        ('iccid','iccid_apn','imsi','imsi_apn','multi_imsi_sim','vrf_reuse')),
    CONSTRAINT chk_iccid_format CHECK (iccid IS NULL OR
        (iccid ~ '^\d{19,20}$'))
);

CREATE INDEX idx_sp_iccid         ON subscriber_profiles (iccid) WHERE iccid IS NOT NULL;
CREATE INDEX idx_sp_account_name  ON subscriber_profiles (account_name);
CREATE INDEX idx_sp_status        ON subscriber_profiles (account_name, status);
```

---

### Table 2: subscriber_imsis

One row per IMSI. Multiple rows may share one `device_id` (Multi-IMSI SIM card).
`imsi` is the B-tree primary key — this is the AAA hot-path entry point.

```sql
CREATE TABLE subscriber_imsis (
    imsi        TEXT        NOT NULL,
    device_id   UUID        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'active',
    priority    SMALLINT    NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT subscriber_imsis_pkey PRIMARY KEY (imsi),
    CONSTRAINT subscriber_imsis_device_fkey
        FOREIGN KEY (device_id) REFERENCES subscriber_profiles (device_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_imsi_status   CHECK (status IN ('active','suspended')),
    CONSTRAINT chk_imsi_15       CHECK (imsi ~ '^\d{15}$')
);

CREATE INDEX idx_si_device_id ON subscriber_imsis (device_id);  -- reverse: device → all IMSIs
```

---

### Table 3: subscriber_apn_ips

Per-IMSI static IP assignments. Used by `ip_resolution = "imsi"` or `"imsi_apn"`.

- `apn IS NULL`     → ip_resolution = `"imsi"` (one IP per IMSI, APN ignored)
- `apn IS NOT NULL` → ip_resolution = `"imsi_apn"` (IP per IMSI+APN pair)
- `apn = null` entry alongside specific APN entries acts as wildcard fallback

```sql
CREATE TABLE subscriber_apn_ips (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    imsi        TEXT        NOT NULL,
    apn         TEXT,                       -- NULL = APN-agnostic / wildcard
    static_ip   INET        NOT NULL,
    pool_id     UUID,
    pool_name   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT subscriber_apn_ips_imsi_fkey
        FOREIGN KEY (imsi) REFERENCES subscriber_imsis (imsi)
        ON DELETE CASCADE,
    CONSTRAINT uq_apn_ips_imsi_apn UNIQUE NULLS NOT DISTINCT (imsi, apn)
    -- UNIQUE NULLS NOT DISTINCT: only one NULL-apn row per imsi is allowed
    -- Requires PostgreSQL 15+
);

CREATE INDEX idx_sai_imsi ON subscriber_apn_ips (imsi);
```

---

### Table 4: subscriber_iccid_ips

Card-level static IP assignments. Used by `ip_resolution = "iccid"` or `"iccid_apn"`.
All IMSIs on the card share these IPs.

- `apn IS NULL`     → ip_resolution = `"iccid"` (one IP for entire card)
- `apn IS NOT NULL` → ip_resolution = `"iccid_apn"` (IP per card+APN pair)

```sql
CREATE TABLE subscriber_iccid_ips (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id   UUID        NOT NULL,
    apn         TEXT,                       -- NULL = all APNs
    static_ip   INET        NOT NULL,
    pool_id     UUID,
    pool_name   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT subscriber_iccid_ips_device_fkey
        FOREIGN KEY (device_id) REFERENCES subscriber_profiles (device_id)
        ON DELETE CASCADE,
    CONSTRAINT uq_iccid_ips_device_apn UNIQUE NULLS NOT DISTINCT (device_id, apn)
);

CREATE INDEX idx_sii_device_id ON subscriber_iccid_ips (device_id);
```

---

### Table 5: ip_pools

IP pool definitions. One pool covers one subnet. IPs in the pool are pre-populated
into `ip_pool_available` at pool creation time.

```sql
CREATE TABLE ip_pools (
    pool_id         UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    account_name    TEXT,
    pool_name       TEXT        NOT NULL,
    subnet          CIDR        NOT NULL,
    start_ip        INET        NOT NULL,
    end_ip          INET        NOT NULL,    -- broadcast address (last in subnet)
    status          TEXT        NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_pool_status CHECK (status IN ('active', 'suspended'))
);

CREATE INDEX idx_pools_account ON ip_pools (account_name);
```

---

### Table 6: ip_pool_available

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

### Table 7: iccid_range_configs

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
    pool_id         UUID        NOT NULL REFERENCES ip_pools (pool_id),
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

### Table 8: imsi_range_configs

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
    pool_id         UUID        NOT NULL REFERENCES ip_pools (pool_id),
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

### Auto-Update Trigger (all tables)

```sql
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;

CREATE TRIGGER trg_sp_updated_at      BEFORE UPDATE ON subscriber_profiles    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_si_updated_at      BEFORE UPDATE ON subscriber_imsis       FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_sai_updated_at     BEFORE UPDATE ON subscriber_apn_ips     FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_sii_updated_at     BEFORE UPDATE ON subscriber_iccid_ips   FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_pools_updated_at   BEFORE UPDATE ON ip_pools                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_iccid_rc_updated_at BEFORE UPDATE ON iccid_range_configs   FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_irc_updated_at     BEFORE UPDATE ON imsi_range_configs      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

---

## AAA Hot-Path Lookup Query

Executed on every RADIUS/Diameter Access-Request. Covers all three production profiles
in a single query — the application layer selects the correct row from the result set.

```sql
-- $1 = IMSI from Access-Request (always present)
-- $2 = APN  from Access-Request (always present; ignored depending on ip_resolution)
SELECT
    sp.device_id,
    sp.status           AS sim_status,
    sp.ip_resolution,
    si.status           AS imsi_status,
    sa.apn              AS imsi_apn,
    sa.static_ip        AS imsi_static_ip,
    sa.pool_id          AS imsi_pool_id,
    ci.apn              AS iccid_apn,
    ci.static_ip        AS iccid_static_ip,
    ci.pool_id          AS iccid_pool_id
FROM        subscriber_imsis       si
JOIN        subscriber_profiles    sp  ON sp.device_id = si.device_id
LEFT JOIN   subscriber_apn_ips     sa  ON sa.imsi = si.imsi
LEFT JOIN   subscriber_iccid_ips   ci  ON ci.device_id = sp.device_id
WHERE si.imsi = $1;
```

**Expected performance:** p50 1–3ms / p99 3–8ms
Index path: B-tree seek on `subscriber_imsis.imsi` (PK) → nested loop join to
`subscriber_profiles` (device_id PK) → left-join both IP tables (low cardinality per IMSI).

The entire `subscriber_imsis` index (~80MB for 1M rows) fits in PostgreSQL `shared_buffers`;
near 100% cache-hit rate at steady state.

---

## First-Connection Allocation — Write Transaction

Triggered by `subscriber-profile-api` via `POST /first-connection` when
`aaa-lookup-service` returns 404 for an unknown IMSI and FreeRADIUS falls
through to the provisioning service.  All writes go to `PRIMARY_URL`.
`aaa-lookup-service` is read-only and never touches this transaction.

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
INSERT INTO subscriber_profiles (account_name, status, ip_resolution, metadata)
VALUES ($account_name, 'active', $ip_resolution,
        jsonb_build_object('tags', '["auto-allocated"]', 'imei', $imei))
RETURNING device_id INTO $new_device_id;

INSERT INTO subscriber_imsis (imsi, device_id, status, priority)
VALUES ($imsi, $new_device_id, 'active', 1);

-- Step 4: store the IP in the correct table based on ip_resolution
IF $ip_resolution IN ('imsi', 'imsi_apn'):
    INSERT INTO subscriber_apn_ips (imsi, apn, static_ip, pool_id)
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
    -- Card-level IP: goes into subscriber_iccid_ips, not subscriber_apn_ips
    INSERT INTO subscriber_iccid_ips (device_id, apn, static_ip, pool_id)
    VALUES (
        $new_device_id,
        CASE $ip_resolution
            WHEN 'iccid'     THEN NULL         -- APN-agnostic card-level IP
            WHEN 'iccid_apn' THEN $apn         -- APN-specific card-level IP
        END,
        $allocated_ip,
        $pool_id
    );
    -- No subscriber_apn_ips row needed; aaa-lookup-service reads subscriber_iccid_ips

COMMIT;
-- Return $allocated_ip to FreeRADIUS → Access-Accept
```

**`ip_resolution` mapping for first-connection allocation:**

| Range config `ip_resolution` | Profile created with | IP stored in | `apn` value |
|---|---|---|---|
| `imsi` | `ip_resolution='imsi'` | `subscriber_apn_ips` | `NULL` (wildcard) |
| `imsi_apn` | `ip_resolution='imsi_apn'` | `subscriber_apn_ips` | APN from Access-Request |
| `iccid` | `ip_resolution='iccid'` | `subscriber_iccid_ips` | `NULL` (wildcard) |
| `iccid_apn` | `ip_resolution='iccid_apn'` | `subscriber_iccid_ips` | APN from Access-Request |

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
SELECT device_id FROM subscriber_profiles
WHERE iccid = $derived_iccid
FOR UPDATE;   -- lock to prevent concurrent creation for same card

IF found:
    -- Card already exists (another IMSI slot connected first).
    -- Register this IMSI on the existing device; reuse the existing IP.
    INSERT INTO subscriber_imsis (imsi, device_id, status, priority)
    VALUES ($imsi, $existing_device_id, 'active', $imsi_slot)
    ON CONFLICT (imsi) DO NOTHING;

    -- Copy the existing card IP to this IMSI using the same ip_resolution routing
    IF $ip_resolution IN ('imsi', 'imsi_apn'):
        INSERT INTO subscriber_apn_ips (imsi, apn, static_ip, pool_id)
        SELECT $imsi,
               CASE $ip_resolution
                   WHEN 'imsi'     THEN NULL
                   WHEN 'imsi_apn' THEN $apn
               END,
               sa.static_ip, sa.pool_id
        FROM   subscriber_apn_ips sa
        JOIN   subscriber_imsis   si ON si.imsi = sa.imsi
        WHERE  si.device_id = $existing_device_id LIMIT 1
        ON CONFLICT DO NOTHING;

    -- iccid / iccid_apn: subscriber_iccid_ips already has one card-level row;
    -- nothing more to insert for this IMSI.

ELSE:
    -- First IMSI slot from this card: allocate one IP for the entire card.
    DELETE FROM ip_pool_available
    WHERE ip = (SELECT ip FROM ip_pool_available
                WHERE pool_id = $pool_id ORDER BY ip LIMIT 1
                FOR UPDATE SKIP LOCKED)
    RETURNING ip INTO $allocated_ip;
    -- NULL → ROLLBACK → 503

    INSERT INTO subscriber_profiles
        (account_name, status, ip_resolution, iccid, metadata)
    VALUES ($account_name, 'active', $ip_resolution, $derived_iccid,
            jsonb_build_object('tags', '["auto-allocated","multi-imsi"]', 'imei', $imei))
    RETURNING device_id INTO $new_device_id;

    -- Store IP at card or IMSI level depending on ip_resolution
    IF $ip_resolution IN ('iccid', 'iccid_apn'):
        -- One card-level row covers all IMSIs on this card
        INSERT INTO subscriber_iccid_ips (device_id, apn, static_ip, pool_id)
        VALUES (
            $new_device_id,
            CASE $ip_resolution WHEN 'iccid' THEN NULL WHEN 'iccid_apn' THEN $apn END,
            $allocated_ip, $pool_id
        );

    -- Pre-provision ALL sibling IMSI slots for this card in the same transaction
    FOR each sibling_range IN (
        SELECT f_imsi, imsi_slot FROM imsi_range_configs
        WHERE  iccid_range_id = $iccid_range_id AND status = 'active'
    ) LOOP
        sibling_imsi = lpad((numeric(sibling_range.f_imsi) + offset)::text, 15, '0');

        INSERT INTO subscriber_imsis (imsi, device_id, status, priority)
        VALUES (sibling_imsi, $new_device_id, 'active', sibling_range.imsi_slot)
        ON CONFLICT (imsi) DO NOTHING;

        IF $ip_resolution IN ('imsi', 'imsi_apn'):
            -- Each sibling IMSI needs its own apn_ips row (they all share one IP)
            INSERT INTO subscriber_apn_ips (imsi, apn, static_ip, pool_id)
            VALUES (
                sibling_imsi,
                CASE $ip_resolution WHEN 'imsi' THEN NULL WHEN 'imsi_apn' THEN $apn END,
                $allocated_ip, $pool_id
            )
            ON CONFLICT DO NOTHING;
        -- iccid / iccid_apn: the single subscriber_iccid_ips row already covers all IMSIs

    END LOOP;

COMMIT;
-- Return $allocated_ip to FreeRADIUS → Access-Accept
```

**Key properties of the multi-IMSI transaction:**
- `ip_resolution` sourced exclusively from the parent `iccid_range_configs` row — consistent across all slots on the same card
- One IP allocated per physical SIM card regardless of IMSI count
- For `iccid`/`iccid_apn` mode: one `subscriber_iccid_ips` row covers all sibling IMSIs — no per-IMSI IP rows needed
- For `imsi`/`imsi_apn` mode: one `subscriber_apn_ips` row per sibling IMSI, all pointing to the same allocated IP
- All sibling IMSIs pre-provisioned in the same transaction — subsequent connections always hit the `aaa-lookup-service` fast read path
- `FOR UPDATE` on the ICCID check prevents two concurrent connections from the same card racing to create duplicate profiles

---

## IMSI Add / Remove

```sql
-- Add IMSI to existing SIM (one transaction)
BEGIN;
INSERT INTO subscriber_imsis (imsi, device_id, status, priority)
    VALUES ('278773000002005', '550e8400-e29b-41d4-a716-446655440000', 'active', 2);
INSERT INTO subscriber_apn_ips (imsi, apn, static_ip, pool_id, pool_name)
    VALUES ('278773000002005', NULL, '100.65.120.6', 'pool-uuid-abc', 'Melita-internet-pool');
COMMIT;

-- Remove IMSI (CASCADE removes subscriber_apn_ips automatically)
DELETE FROM subscriber_imsis WHERE imsi = '278773000002005';

-- Enrich NULL iccid with real value
UPDATE subscriber_profiles
SET iccid = '8944501012345678901', updated_at = now()
WHERE device_id = '550e8400-e29b-41d4-a716-446655440000';
```

---

## Bulk Provisioning — 300K Profiles

```sql
-- Idempotent upsert via staging table (columns defined explicitly — do NOT use LIKE INCLUDING ALL
-- because that copies GENERATED ALWAYS AS IDENTITY which blocks loading pre-generated device_ids)
CREATE TEMP TABLE staging_profiles (
    device_id       UUID,
    iccid           TEXT,
    account_name    TEXT,
    status          TEXT,
    ip_resolution   TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ
);

\COPY staging_profiles FROM 'batch.csv' WITH (FORMAT csv, HEADER true);

INSERT INTO subscriber_profiles
    SELECT * FROM staging_profiles
    ON CONFLICT (device_id) DO UPDATE
    SET status=EXCLUDED.status, ip_resolution=EXCLUDED.ip_resolution,
        metadata=EXCLUDED.metadata, updated_at=now();

-- Repeat for subscriber_imsis, subscriber_apn_ips, subscriber_iccid_ips
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
| AAA: IMSI lookup (all profiles) | 1–5ms p50, 3–8ms p99 | PK seek on `subscriber_imsis`, 2-table join |
| AAA: ICCID lookup (Profile A) | 1–3ms | PK seek on `subscriber_profiles`, left-join `subscriber_iccid_ips` |
| Provisioning: GET full profile | 2–8ms | Same joins, all rows returned |
| Provisioning: add/remove IMSI | 3–10ms | Transactional INSERT/DELETE |
| Provisioning: update SIM status | 1–3ms | Single UPDATE on `subscriber_profiles` |
| First-connection allocation | 5–20ms | Write transaction in `subscriber-profile-api` on primary (rare event) |
| Bulk upsert 300K | ~3–5 min total | COPY + INSERT ON CONFLICT, 4 tables |
| Pool stats query | <200ms at 300K rows | Aggregate on `subscriber_apn_ips.pool_id` |

## PostgreSQL Version Requirement

**PostgreSQL 15 minimum.** Required for `UNIQUE NULLS NOT DISTINCT` on `subscriber_apn_ips`
and `subscriber_iccid_ips`. This constraint ensures only one NULL-apn wildcard entry per
IMSI (or per device). Earlier PostgreSQL versions treat all NULLs as distinct in UNIQUE
indexes, which would allow duplicate wildcard rows.
