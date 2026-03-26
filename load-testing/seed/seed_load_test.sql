-- ============================================================
-- AAA Load Test Seed Data  (k6 HTTP load tests only)
--
-- Used by: load.js, stress.js, spike.js, soak.js, smoke.js
-- NOT needed for the RADIUS load test — radius_load.py creates
-- its own pools/range-configs via API and warms up subscribers
-- through RADIUS at startup.
--
-- Inserts 10 000 test subscribers with static IPs so every
-- k6 HTTP lookup request returns HTTP 200.
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

-- NOTE: The first-connect pool and IMSI range config are created automatically
-- by radius_load.py at startup via subscriber-profile-api POST /pools and
-- POST /range-configs. No manual SQL step is required for first-connect setup.

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
