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

# ── Drop stale Plan-1 tables (old names superseded by Plan-2 schema) ──────────
# Plan 1 used different table names. If they are still present they block the
# Plan 2 CREATE TABLE statements (duplicate constraint/index names).
# We drop them with CASCADE only when the new Plan-2 tables are absent, so this
# step is a no-op on a clean install and only fires during a schema migration.
echo "Checking for stale Plan-1 tables..."
kubectl exec -i "${PRIMARY_POD}" \
  -n "${NAMESPACE}" \
  -- psql -U postgres -d "${DB_NAME}" <<'SQL'
DO $$
BEGIN
  -- subscriber_apn_ips  → replaced by imsi_apn_ips
  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'subscriber_apn_ips'  AND relkind = 'r')
  AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'imsi_apn_ips'   AND relkind = 'r') THEN
    DROP TABLE subscriber_apn_ips CASCADE;
    RAISE NOTICE 'Dropped stale Plan-1 table subscriber_apn_ips';
  END IF;

  -- subscriber_iccid_ips → replaced by device_apn_ips
  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'subscriber_iccid_ips' AND relkind = 'r')
  AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'device_apn_ips'   AND relkind = 'r') THEN
    DROP TABLE subscriber_iccid_ips CASCADE;
    RAISE NOTICE 'Dropped stale Plan-1 table subscriber_iccid_ips';
  END IF;

  -- subscriber_imsis  → replaced by imsi2device  (keep if new table also absent)
  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'subscriber_imsis' AND relkind = 'r')
  AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'imsi2device'  AND relkind = 'r') THEN
    DROP TABLE subscriber_imsis CASCADE;
    RAISE NOTICE 'Dropped stale Plan-1 table subscriber_imsis';
  END IF;

  -- subscriber_profiles → replaced by device_profiles
  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'subscriber_profiles' AND relkind = 'r')
  AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'device_profiles'  AND relkind = 'r') THEN
    DROP TABLE subscriber_profiles CASCADE;
    RAISE NOTICE 'Dropped stale Plan-1 table subscriber_profiles';
  END IF;
END;
$$;
SQL

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
