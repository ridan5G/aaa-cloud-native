-- ============================================================
-- AAA Load Test Seed Data
-- Inserts 10 000 test subscribers with active status and
-- imsi_apn resolution mode so every lookup returns HTTP 200.
--
-- IMSI range : 001010000001001 – 001010000011000  (MCC=001, MNC=01)
-- ICCID range: 8900000000000001001 – 8900000000000011000
-- IP range   : 100.64.0.1  – 100.64.39.94  (CGNAT 100.64.0.0/10)
-- APNs       : internet, mms, ims  (one row each per subscriber)
--
-- Idempotent — safe to run multiple times (ON CONFLICT DO NOTHING).
-- ============================================================

BEGIN;

-- Build a temporary mapping table (seq, sim_id, imsi, iccid, ip)
CREATE TEMP TABLE _lt_seed AS
SELECT
  s                                                          AS seq,
  gen_random_uuid()                                          AS sim_id,
  '00101' || LPAD(s::TEXT, 10, '0')                         AS imsi,
  '89' || LPAD(s::TEXT, 17, '0')                            AS iccid,
  ('100.64.' || ((s - 1) / 254) || '.' || ((s - 1) % 254 + 1))::INET AS static_ip
FROM generate_series(1, 10000) s;

-- ── sim_profiles ────────────────────────────────────────────
INSERT INTO sim_profiles (sim_id, iccid, account_name, status, ip_resolution, metadata)
SELECT
  sim_id,
  iccid,
  'LoadTestAccount',
  'active',
  'imsi_apn',
  '{}'
FROM _lt_seed
ON CONFLICT DO NOTHING;

-- ── imsi2sim ───────────────────────────────────────────────
INSERT INTO imsi2sim (imsi, sim_id, status, priority)
SELECT
  imsi,
  sim_id,
  'active',
  1
FROM _lt_seed
ON CONFLICT (imsi) DO NOTHING;

-- ── imsi_apn_ips — one row per APN per subscriber ───────────
-- Explicit rows for every APN the load test uses so all requests return 200.
INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id, pool_name)
SELECT
  s.imsi,
  a.apn,
  s.static_ip,
  NULL,
  NULL
FROM _lt_seed s
CROSS JOIN (VALUES ('internet'), ('mms'), ('ims')) AS a(apn)
ON CONFLICT DO NOTHING;

-- ── First-connect pool + range config ───────────────────────────────────────
-- Provides 4 094 free IPs for the 2 RPS × 20 min = ~2 400 first-connections.
-- Uses a fixed pool_id so the insert is idempotent.
-- IMSI range 001010000011001–001010000013600 is NOT in imsi2sim, so every hit
-- triggers the full subscriber-profile-api first-connection path.

DO $$
DECLARE
  v_domain_id UUID;
  v_pool_id   UUID := '00000000-0000-0000-f001-000000000001';
BEGIN
  -- Resolve the default routing domain
  SELECT id INTO v_domain_id FROM routing_domains WHERE name = 'default' LIMIT 1;

  IF v_domain_id IS NULL THEN
    RAISE EXCEPTION 'routing_domain "default" not found — run schema migrations first';
  END IF;

  -- ip_pools: 100.65.0.0/20  →  start=network addr, end=broadcast
  -- Pre-population inserts usable hosts: 100.65.0.1 – 100.65.15.254 (4 094 IPs)
  INSERT INTO ip_pools
    (pool_id, account_name, pool_name, routing_domain_id, subnet, start_ip, end_ip)
  VALUES
    (v_pool_id, 'LoadTestAccount', 'load-test-firstconn',
     v_domain_id, '100.65.0.0/20', '100.65.0.0', '100.65.15.255')
  ON CONFLICT (pool_id) DO NOTHING;

  -- ip_pool_available: one row per usable host IP
  -- INET subtraction returns bigint, matching the schema's pre-population pattern
  INSERT INTO ip_pool_available (pool_id, ip)
  SELECT v_pool_id, (p.start_ip + n)::INET
  FROM   ip_pools p,
         generate_series(1, p.end_ip - p.start_ip - 1) AS n
  WHERE  p.pool_id = v_pool_id
  ON CONFLICT DO NOTHING;

  -- imsi_range_configs: covers 001010000011001 – 001010000013600
  -- 2 600 fresh IMSIs — enough for 2 RPS × 20 min = 2 400 first-connections
  INSERT INTO imsi_range_configs
    (account_name, f_imsi, t_imsi, pool_id, ip_resolution, status)
  SELECT 'LoadTestAccount', '001010000011001', '001010000013600',
         v_pool_id, 'imsi_apn', 'active'
  WHERE NOT EXISTS (
    SELECT 1 FROM imsi_range_configs
    WHERE f_imsi = '001010000011001' AND t_imsi = '001010000013600'
  );
END $$;

COMMIT;

-- Quick sanity check
SELECT
  COUNT(*) FILTER (WHERE account_name = 'LoadTestAccount') AS profiles,
  COUNT(*) AS total_profiles
FROM sim_profiles;

SELECT COUNT(*) AS imsis
FROM imsi2sim
WHERE imsi LIKE '00101%';

SELECT COUNT(*) AS apn_ips
FROM imsi_apn_ips sa
JOIN imsi2sim si ON si.imsi = sa.imsi
WHERE si.imsi LIKE '00101%';
