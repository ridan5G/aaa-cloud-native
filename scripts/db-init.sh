#!/usr/bin/env bash
# db-init.sh — Apply the AAA schema + grants to the CloudNativePG primary.
#
# WHEN TO RUN:
#   Automatically called by `make setup` and `make bootstrap`.
#   Run manually if you deployed the chart against a pre-existing CNPG cluster
#   that predates the initdb ConfigMap (i.e., postInitApplicationSQLRefs never ran).
#
# IDEMPOTENT: Uses CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
#   Safe to re-run at any time — existing objects are left untouched.
#
# Usage:
#   bash scripts/db-init.sh
#   NAMESPACE=my-ns CONFIGMAP=my-cm bash scripts/db-init.sh

set -euo pipefail

NAMESPACE="${NAMESPACE:-aaa-platform}"
CONFIGMAP="${CONFIGMAP:-aaa-postgres-initdb-sql}"
DB_NAME="${DB_NAME:-aaa}"

echo "══════════════════════════════════════════════════════"
echo " AAA DB Init — schema + grants"
echo " Namespace : ${NAMESPACE}"
echo " ConfigMap : ${CONFIGMAP}"
echo " Database  : ${DB_NAME}"
echo "══════════════════════════════════════════════════════"

# ── Find the CNPG primary pod (retry up to 2 min) ─────────────────────────────
echo -n "Looking for CNPG primary pod"
PRIMARY_POD=""
for i in $(seq 1 24); do
  PRIMARY_POD=$(kubectl get pod \
    -n "${NAMESPACE}" \
    -l cnpg.io/instanceRole=primary \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  [ -n "${PRIMARY_POD}" ] && break
  echo -n "."
  sleep 5
done
echo ""

if [ -z "${PRIMARY_POD}" ]; then
  echo ""
  echo "ERROR: No CNPG primary pod found in namespace '${NAMESPACE}'."
  echo "  • Make sure 'make deploy' completed successfully."
  echo "  • Check: kubectl get pods -n ${NAMESPACE} -l cnpg.io/instanceRole=primary"
  exit 1
fi

echo "Primary pod: ${PRIMARY_POD}"

# ── Wait for the pod to be Ready ──────────────────────────────────────────────
echo -n "Waiting for pod to be Ready..."
kubectl wait pod "${PRIMARY_POD}" \
  -n "${NAMESPACE}" \
  --for=condition=Ready \
  --timeout=120s
echo " ready."

# ── Verify the ConfigMap exists ───────────────────────────────────────────────
if ! kubectl get configmap "${CONFIGMAP}" -n "${NAMESPACE}" &>/dev/null; then
  echo ""
  echo "ERROR: ConfigMap '${CONFIGMAP}' not found in namespace '${NAMESPACE}'."
  echo "  • Make sure 'make deploy' applied the Helm chart successfully."
  exit 1
fi

# ── Drop stale tables from superseded schema generations ──────────────────────
# Each rename cycle is represented as a condition: drop the old name CASCADE
# only when the new name does not yet exist.  CASCADE on the root table
# (sim_profiles / device_profiles) automatically removes child tables, so
# individual child conditions below are safety-nets for partial states.
#
# Generation map (old → current):
#   Plan-1  subscriber_profiles → device_profiles → sim_profiles
#           subscriber_imsis    → imsi2device      → imsi2sim
#           subscriber_apn_ips  → imsi_apn_ips     (FK target changed; drop+recreate)
#           subscriber_iccid_ips→ device_apn_ips   → sim_apn_ips
echo "Checking for stale tables from previous schema generations..."
kubectl exec -i "${PRIMARY_POD}" \
  -n "${NAMESPACE}" \
  -- psql -U postgres -d "${DB_NAME}" <<'SQL'
DO $$
BEGIN
  -- ── Plan-2a (device_*) → Plan-2b (sim_*) ──────────────────────────────────
  -- Dropping device_profiles CASCADE removes imsi2device, imsi_apn_ips,
  -- and device_apn_ips in one shot (FK cascade chain).
  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'device_profiles' AND relkind = 'r')
  AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'sim_profiles' AND relkind = 'r') THEN
    DROP TABLE device_profiles CASCADE;
    RAISE NOTICE 'Dropped stale Plan-2a table device_profiles (cascades to imsi2device, imsi_apn_ips, device_apn_ips)';
  END IF;

  -- imsi_apn_ips: FK target changed imsi2device→imsi2sim; drop so it is
  -- recreated with the correct FK when the schema SQL runs.
  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'imsi_apn_ips' AND relkind = 'r')
  AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'imsi2sim' AND relkind = 'r') THEN
    DROP TABLE imsi_apn_ips CASCADE;
    RAISE NOTICE 'Dropped stale imsi_apn_ips (FK target changed to imsi2sim)';
  END IF;

  -- ── Plan-1 (subscriber_*) → current (sim_*) ───────────────────────────────
  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'subscriber_profiles' AND relkind = 'r')
  AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'sim_profiles'    AND relkind = 'r') THEN
    DROP TABLE subscriber_profiles CASCADE;
    RAISE NOTICE 'Dropped stale Plan-1 table subscriber_profiles';
  END IF;

  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'subscriber_imsis' AND relkind = 'r')
  AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'imsi2sim'     AND relkind = 'r') THEN
    DROP TABLE subscriber_imsis CASCADE;
    RAISE NOTICE 'Dropped stale Plan-1 table subscriber_imsis';
  END IF;

  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'subscriber_apn_ips' AND relkind = 'r')
  AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'imsi_apn_ips'  AND relkind = 'r') THEN
    DROP TABLE subscriber_apn_ips CASCADE;
    RAISE NOTICE 'Dropped stale Plan-1 table subscriber_apn_ips';
  END IF;

  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'subscriber_iccid_ips' AND relkind = 'r')
  AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'sim_apn_ips'      AND relkind = 'r') THEN
    DROP TABLE subscriber_iccid_ips CASCADE;
    RAISE NOTICE 'Dropped stale Plan-1 table subscriber_iccid_ips';
  END IF;
END;
$$;
SQL

# ── Column migrations (idempotent — safe to re-run on existing clusters) ──────
# New columns added after initial cluster bootstrap must be applied here because
# postInitApplicationSQLRefs only runs once (at cluster creation time).
#
# Migration map (three historical schema generations):
#   Gen-1  ip_pools has NO routing column at all      → add routing_domain_id FK
#   Gen-2  ip_pools has routing_domain TEXT           → replace with routing_domain_id FK
#   Gen-3  ip_pools has routing_domain_id UUID FK     → already current, skip
#   Fresh  ip_pools does not exist yet                → schema SQL creates it correctly, skip
echo "Applying column migrations..."
kubectl exec -i "${PRIMARY_POD}" \
  -n "${NAMESPACE}" \
  -- psql -U postgres -d "${DB_NAME}" <<'SQL'
DO $$
DECLARE
  v_ip_pools_exists   BOOL;
  v_has_rd_text       BOOL;
  v_has_rd_id         BOOL;
  v_default_rd_id     UUID;
BEGIN
  SELECT EXISTS (
    SELECT 1 FROM pg_class WHERE relname = 'ip_pools' AND relkind = 'r'
  ) INTO v_ip_pools_exists;

  IF NOT v_ip_pools_exists THEN
    RAISE NOTICE 'Migration skipped: ip_pools not yet created (will be initialised by schema SQL)';
    RETURN;
  END IF;

  SELECT EXISTS (
    SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
    WHERE c.relname = 'ip_pools' AND a.attname = 'routing_domain'
      AND a.attnum > 0 AND NOT a.attisdropped
  ) INTO v_has_rd_text;

  SELECT EXISTS (
    SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
    WHERE c.relname = 'ip_pools' AND a.attname = 'routing_domain_id'
      AND a.attnum > 0 AND NOT a.attisdropped
  ) INTO v_has_rd_id;

  -- ── Case B: already on current schema ──────────────────────────────────────
  IF v_has_rd_id THEN
    RAISE NOTICE 'Migration skipped: ip_pools.routing_domain_id already exists';
    RETURN;
  END IF;

  -- ── Shared setup for Case A and Gen-1 ──────────────────────────────────────
  -- Ensure routing_domains table exists before we reference it
  CREATE TABLE IF NOT EXISTS routing_domains (
      id               UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
      name             TEXT        NOT NULL,
      description      TEXT,
      allowed_prefixes TEXT[]      NOT NULL DEFAULT '{}',
      created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT uq_routing_domain_name UNIQUE (name)
  );

  INSERT INTO routing_domains (name, description)
  VALUES ('default', 'Default routing domain')
  ON CONFLICT (name) DO NOTHING;

  -- ── Case A (Gen-2): routing_domain TEXT → routing_domain_id UUID FK ─────────
  IF v_has_rd_text THEN
    RAISE NOTICE 'Migration (Gen-2): ip_pools.routing_domain TEXT → routing_domain_id UUID FK';

    -- Seed a routing_domains row for every distinct name currently in ip_pools
    INSERT INTO routing_domains (name)
    SELECT DISTINCT routing_domain FROM ip_pools
    ON CONFLICT (name) DO NOTHING;

    ALTER TABLE ip_pools ADD COLUMN routing_domain_id UUID;

    UPDATE ip_pools p
    SET routing_domain_id = rd.id
    FROM routing_domains rd
    WHERE rd.name = p.routing_domain;

    ALTER TABLE ip_pools ALTER COLUMN routing_domain_id SET NOT NULL;
    ALTER TABLE ip_pools ADD CONSTRAINT ip_pools_routing_domain_id_fkey
        FOREIGN KEY (routing_domain_id) REFERENCES routing_domains (id);
    CREATE INDEX IF NOT EXISTS idx_pools_routing_domain_id ON ip_pools (routing_domain_id);

    ALTER TABLE ip_pools DROP COLUMN routing_domain;
    DROP INDEX IF EXISTS idx_pools_routing_domain;

    RAISE NOTICE 'Migration (Gen-2) complete';

  -- ── Case C (Gen-1): neither column — add routing_domain_id directly ─────────
  ELSE
    RAISE NOTICE 'Migration (Gen-1): ip_pools has no routing column — adding routing_domain_id FK';

    SELECT id INTO v_default_rd_id FROM routing_domains WHERE name = 'default';

    ALTER TABLE ip_pools ADD COLUMN routing_domain_id UUID;

    -- All existing pools belong to the default domain
    UPDATE ip_pools SET routing_domain_id = v_default_rd_id;

    ALTER TABLE ip_pools ALTER COLUMN routing_domain_id SET NOT NULL;
    ALTER TABLE ip_pools ADD CONSTRAINT ip_pools_routing_domain_id_fkey
        FOREIGN KEY (routing_domain_id) REFERENCES routing_domains (id);
    CREATE INDEX IF NOT EXISTS idx_pools_routing_domain_id ON ip_pools (routing_domain_id);

    RAISE NOTICE 'Migration (Gen-1) complete';
  END IF;
END;
$$;
SQL
echo "Column migrations done."

# ── Apply schema SQL from ConfigMap ───────────────────────────────────────────
echo "Applying schema SQL from ConfigMap '${CONFIGMAP}'..."
kubectl get configmap "${CONFIGMAP}" \
  -n "${NAMESPACE}" \
  -o jsonpath='{.data.schema\.sql}' \
  | kubectl exec -i "${PRIMARY_POD}" \
      -n "${NAMESPACE}" \
      -- psql -U postgres -d "${DB_NAME}"

echo "Schema SQL applied."

# ── Ensure future objects are accessible to aaa_app ───────────────────────────
# ALTER DEFAULT PRIVILEGES covers tables/sequences created AFTER this point
# (e.g. bulk_jobs created by subscriber-profile-api on first startup when
#  it connects as aaa_app, so it already owns those — but this is a safety net
#  for any future schema changes applied via psql as postgres).
echo "Setting ALTER DEFAULT PRIVILEGES for aaa_app..."
kubectl exec -i "${PRIMARY_POD}" \
  -n "${NAMESPACE}" \
  -- psql -U postgres -d "${DB_NAME}" \
     -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aaa_app;" \
     -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO aaa_app;"

echo "Default privileges set."
echo ""
echo "══════════════════════════════════════════════════════"
echo " DB init complete!"
echo " Run 'make status' to verify all pods are healthy,"
echo " then 'make test' to run the regression suite."
echo "══════════════════════════════════════════════════════"
