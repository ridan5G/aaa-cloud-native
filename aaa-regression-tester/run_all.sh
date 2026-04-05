#!/usr/bin/env bash
# run_all.sh — execute the full regression suite and push metrics.
# Designed to run as a Kubernetes Job entrypoint.
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

# ── Count deselected tests per marker (informational, runs fast) ──────────────
collect_count() {
  # --override-ini clears addopts so pytest.ini's "-m not slow..." doesn't cancel our filter
  # Output format: "7/149 tests collected ..." — extract the first number before the slash
  python -m pytest --collect-only -q --no-header --override-ini="addopts=" -m "$1" 2>/dev/null \
    | awk '/tests collected/{split($1,a,"/"); print a[1]}' | head -1
}
N_SLOW=$(collect_count "slow")
N_MIGRATION=$(collect_count "migration")
N_NOAUTH=$(collect_count "noauth")

# ── Run the suite ─────────────────────────────────────────────────────────────
EXIT_CODE=0
python -m pytest \
  --junitxml="${JUNIT_XML}" \
  -v \
  "$@" \
  || EXIT_CODE=$?

echo " Deselected : ${N_SLOW:-0} performance (slow)  |  ${N_MIGRATION:-0} migration  |  ${N_NOAUTH:-0} keycloak-auth (noauth)"

# ── Push metrics to Prometheus Pushgateway ────────────────────────────────────
if [ -n "${PUSHGATEWAY_URL:-}" ]; then
  echo "Pushing metrics to ${PUSHGATEWAY_URL}..."
  python push_metrics.py \
    --junit-xml "${JUNIT_XML}" \
    --pushgateway "${PUSHGATEWAY_URL}" \
    --timing-csv "${TIMING_CSV}" \
    || echo "WARNING: metrics push failed (non-fatal)"
fi

# ── Check pod logs for exceptions ─────────────────────────────────────────────
check_pod_exceptions() {
  local namespace="${NAMESPACE:-aaa-platform}"
  local -a prefixes=(
    "aaa-platform-aaa-lookup-service"
    "aaa-platform-aaa-radius-server"
    "aaa-platform-subscriber-profile-api"
  )
  local exception_pods=0

  echo "══════════════════════════════════════════════════════"
  echo " Checking pod logs for exceptions (namespace: ${namespace})"
  echo "══════════════════════════════════════════════════════"

  for prefix in "${prefixes[@]}"; do
    local pods
    pods=$(kubectl get pods -n "${namespace}" --no-headers 2>/dev/null \
           | awk '{print $1}' | grep "^${prefix}" || true)

    if [ -z "${pods}" ]; then
      echo "  WARNING: no pods found with prefix '${prefix}'"
      continue
    fi

    for pod in ${pods}; do
      echo -n "  ${pod}: "
      local hits
      hits=$(kubectl logs -n "${namespace}" "${pod}" 2>/dev/null \
             | grep -i "exception" || true)
      if [ -n "${hits}" ]; then
        echo "EXCEPTIONS FOUND:"
        echo "${hits}" | head -100 | sed 's/^/    /'
        exception_pods=$((exception_pods + 1))
      else
        echo "ok (no exceptions)"
      fi
    done
  done

  echo "──────────────────────────────────────────────────────"
  if [ "${exception_pods}" -gt 0 ]; then
    echo " WARNING: exceptions detected in ${exception_pods} pod(s) — review logs above"
  else
    echo " No exceptions found in any pod"
  fi
}

if kubectl version --client >/dev/null 2>&1; then
  check_pod_exceptions
else
  echo "WARNING: kubectl not available — skipping pod log exception check"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo "══════════════════════════════════════════════════════"
echo " Results written to: ${JUNIT_XML}"
[ -f "${TIMING_CSV}" ] && echo " Timing CSV:  ${TIMING_CSV}"
echo " Exit code: ${EXIT_CODE}"
echo "══════════════════════════════════════════════════════"

exit ${EXIT_CODE}
