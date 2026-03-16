#!/usr/bin/env bash
# run_all.sh — execute the full regression suite and push metrics.
# Designed to run as a Kubernetes Job entrypoint or locally via docker compose.
set -euo pipefail

RESULTS_DIR="${RESULTS_DIR:-/app/results}"
mkdir -p "${RESULTS_DIR}"

JUNIT_XML="${RESULTS_DIR}/results.xml"
TIMING_CSV="${RESULTS_DIR}/timing.csv"

echo "══════════════════════════════════════════════════════"
echo " AAA Regression Suite"
echo " PROVISION_URL : ${PROVISION_URL:-http://localhost:8080/v1}"
echo " LOOKUP_URL    : ${LOOKUP_URL:-http://localhost:8081/v1}"
echo "══════════════════════════════════════════════════════"

# ── Wait for both services to be healthy ──────────────────────────────────────
wait_healthy() {
  local url="$1"
  local label="$2"
  local retries=30
  echo -n "Waiting for ${label}..."
  for i in $(seq 1 $retries); do
    if python - <<EOF 2>/dev/null
import httpx, sys
try:
    r = httpx.get("${url}/health", timeout=2)
    sys.exit(0 if r.status_code == 200 else 1)
except Exception:
    sys.exit(1)
EOF
    then
      echo " ready."
      return 0
    fi
    sleep 2
    echo -n "."
  done
  echo " TIMED OUT after $((retries * 2))s"
  exit 1
}

wait_healthy "${PROVISION_URL%/v1}" "subscriber-profile-api"
wait_healthy "${LOOKUP_URL%/v1}"    "aaa-lookup-service"

# ── Run the suite ─────────────────────────────────────────────────────────────
EXIT_CODE=0
python -m pytest \
  --junitxml="${JUNIT_XML}" \
  -v \
  "$@" \
  || EXIT_CODE=$?

# ── Push metrics to Prometheus Pushgateway ────────────────────────────────────
if [ -n "${PUSHGATEWAY_URL:-}" ]; then
  echo "Pushing metrics to ${PUSHGATEWAY_URL}..."
  python push_metrics.py \
    --junit-xml "${JUNIT_XML}" \
    --pushgateway "${PUSHGATEWAY_URL}" \
    --timing-csv "${TIMING_CSV}" \
    || echo "WARNING: metrics push failed (non-fatal)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo "══════════════════════════════════════════════════════"
echo " Results written to: ${JUNIT_XML}"
[ -f "${TIMING_CSV}" ] && echo " Timing CSV:  ${TIMING_CSV}"
echo " Exit code: ${EXIT_CODE}"
echo "══════════════════════════════════════════════════════"

exit ${EXIT_CODE}
