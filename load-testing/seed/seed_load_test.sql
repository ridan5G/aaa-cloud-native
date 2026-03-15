-- ============================================================
-- AAA Load Test Seed Data
-- Inserts 10 000 test subscribers with active status and
-- imsi_apn resolution mode so every lookup returns HTTP 200.
--
-- IMSI range : 001010000001001 – 001010000011000  (MCC=001, MNC=01)
-- ICCID range: 8900000000000001001 – 8900000000000011000
-- IP range   : 100.64.0.1  – 100.64.39.94  (CGNAT 100.64.0.0/10)
-- APN        : internet  (exact match)
--
-- Idempotent — safe to run multiple times (ON CONFLICT DO NOTHING).
-- ============================================================

BEGIN;

-- Build a temporary mapping table (seq, device_id, imsi, iccid, ip)
CREATE TEMP TABLE _lt_seed AS
SELECT
  s                                                          AS seq,
  gen_random_uuid()                                          AS device_id,
  '00101' || LPAD(s::TEXT, 10, '0')                         AS imsi,
  '89' || LPAD(s::TEXT, 17, '0')                            AS iccid,
  ('100.64.' || ((s - 1) / 254) || '.' || ((s - 1) % 254 + 1))::INET AS static_ip
FROM generate_series(1, 10000) s;

-- ── device_profiles ────────────────────────────────────────────
INSERT INTO device_profiles (device_id, iccid, account_name, status, ip_resolution, metadata)
SELECT
  device_id,
  iccid,
  'LoadTestAccount',
  'active',
  'imsi_apn',
  ''
FROM _lt_seed
ON CONFLICT (device_id) DO NOTHING;

-- ── imsi2device ───────────────────────────────────────────────
INSERT INTO imsi2device (imsi, device_id, status, priority)
SELECT
  imsi,
  device_id,
  'active',
  1
FROM _lt_seed
ON CONFLICT (imsi) DO NOTHING;

-- ── imsi_apn_ips — 'internet' APN (exact match) ─────────────
INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id, pool_name)
SELECT
  imsi,
  'internet',
  static_ip,
  NULL,
  NULL
FROM _lt_seed
ON CONFLICT DO NOTHING;

-- ── imsi_apn_ips — wildcard APN (fallback for other APNs) ───
-- apn = '' is the catch-all wildcard (matches the existing data convention)
INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id, pool_name)
SELECT
  imsi,
  '',
  (static_ip::TEXT::INET + 1000),   -- distinct IP for wildcard path
  NULL,
  NULL
FROM _lt_seed
ON CONFLICT DO NOTHING;

COMMIT;

-- Quick sanity check
SELECT
  COUNT(*) FILTER (WHERE account_name = 'LoadTestAccount') AS profiles,
  COUNT(*) AS total_profiles
FROM device_profiles;

SELECT COUNT(*) AS imsis
FROM imsi2device
WHERE imsi LIKE '00101%';

SELECT COUNT(*) AS apn_ips
FROM imsi_apn_ips sa
JOIN imsi2device si ON si.imsi = sa.imsi
WHERE si.imsi LIKE '00101%';
