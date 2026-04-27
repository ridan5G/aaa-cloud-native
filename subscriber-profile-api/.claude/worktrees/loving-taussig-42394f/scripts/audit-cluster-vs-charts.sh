#!/usr/bin/env bash
# audit-cluster-vs-charts.sh
# Compares the live Kubernetes cluster state against the Helm chart sources
# and reports any drift (on-the-fly changes not yet in charts).
#
# Usage:
#   ./scripts/audit-cluster-vs-charts.sh              # full audit
#   ./scripts/audit-cluster-vs-charts.sh --fix        # also print kubectl fix commands
#   ./scripts/audit-cluster-vs-charts.sh --section radius  # single section

set -uo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
NAMESPACE="${NAMESPACE:-aaa-platform}"
RELEASE="${RELEASE:-aaa-platform}"
CHART_DIR="${CHART_DIR:-$(cd "$(dirname "$0")/.." && pwd)/charts/aaa-platform}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

FIX_MODE=false
SECTION_FILTER=""

for arg in "$@"; do
  case "$arg" in
    --fix)        FIX_MODE=true ;;
    --section)    shift; SECTION_FILTER="$1" ;;
    --section=*)  SECTION_FILTER="${arg#--section=}" ;;
  esac
done

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

PASS=0; FAIL=0; WARN=0

pass()  { echo -e "  ${GREEN}✓${RESET} $*"; (( PASS++ )) || true; }
fail()  { echo -e "  ${RED}✗${RESET} $*"; (( FAIL++ )) || true; }
warn()  { echo -e "  ${YELLOW}⚠${RESET} $*"; (( WARN++ )) || true; }
section() {
  [[ -n "$SECTION_FILTER" && "$1" != *"$SECTION_FILTER"* ]] && return 1
  echo -e "\n${CYAN}${BOLD}══ $1 ══${RESET}"
  return 0
}
fix_cmd() { $FIX_MODE && echo -e "    ${YELLOW}FIX:${RESET} $*" || true; }

# ── kubectl helpers ───────────────────────────────────────────────────────────
kget() { kubectl get "$@" -n "$NAMESPACE" 2>/dev/null; }
kjson() { kubectl get "$@" -n "$NAMESPACE" -o json 2>/dev/null; }
kexists() { kubectl get "$@" -n "$NAMESPACE" &>/dev/null; }

# ── 1. RADIUS Deployment ──────────────────────────────────────────────────────
section "RADIUS Deployment (aaa-radius-server)" || true

if ! kexists deployment "${RELEASE}-aaa-radius-server"; then
  fail "Deployment ${RELEASE}-aaa-radius-server not found in ${NAMESPACE}"
else
  DEPLOY_JSON=$(kjson deployment "${RELEASE}-aaa-radius-server")

  # env: METRICS_PORT=9090
  METRICS_PORT_VAL=$(echo "$DEPLOY_JSON" | python3 -c "
import json,sys
c=json.load(sys.stdin)['spec']['template']['spec']['containers'][0]
envs={e['name']:e.get('value','<from-secret>') for e in c.get('env',[])}
print(envs.get('METRICS_PORT','MISSING'))
" 2>/dev/null)
  if [[ "$METRICS_PORT_VAL" == "9090" ]]; then
    pass "METRICS_PORT=9090 env var present"
  else
    fail "METRICS_PORT env var: expected 9090, got '${METRICS_PORT_VAL}'"
    fix_cmd "kubectl set env deployment/${RELEASE}-aaa-radius-server METRICS_PORT=9090 -n $NAMESPACE"
  fi

  # container port: metrics/9090/TCP
  METRICS_PORT_DEFINED=$(echo "$DEPLOY_JSON" | python3 -c "
import json,sys
ports=json.load(sys.stdin)['spec']['template']['spec']['containers'][0].get('ports',[])
names=[p.get('name') for p in ports if p.get('containerPort')==9090 and p.get('protocol','TCP')=='TCP']
print(names[0] if names else 'MISSING')
" 2>/dev/null)
  if [[ "$METRICS_PORT_DEFINED" == "metrics" ]]; then
    pass "Container port metrics/9090/TCP declared"
  else
    fail "Container port metrics/9090/TCP not declared (got: ${METRICS_PORT_DEFINED})"
  fi

  # pod annotations: prometheus.io/scrape, port, path
  for KEY in "prometheus.io/scrape" "prometheus.io/port" "prometheus.io/path"; do
    VAL=$(echo "$DEPLOY_JSON" | python3 -c "
import json,sys
a=json.load(sys.stdin)['spec']['template']['metadata'].get('annotations',{})
print(a.get('${KEY}','MISSING'))
" 2>/dev/null)
    if [[ "$VAL" != "MISSING" ]]; then
      pass "Pod annotation ${KEY}=${VAL}"
    else
      fail "Pod annotation ${KEY} missing"
    fi
  done
fi

# ── 2. RADIUS Service ─────────────────────────────────────────────────────────
section "RADIUS Service" || true

if ! kexists service "${RELEASE}-aaa-radius-server"; then
  fail "Service ${RELEASE}-aaa-radius-server not found"
else
  SVC_JSON=$(kjson service "${RELEASE}-aaa-radius-server")
  METRICS_SVC=$(echo "$SVC_JSON" | python3 -c "
import json,sys
ports=json.load(sys.stdin)['spec']['ports']
match=[p for p in ports if p.get('name')=='metrics' and p.get('port')==9090]
print('OK' if match else 'MISSING')
" 2>/dev/null)
  if [[ "$METRICS_SVC" == "OK" ]]; then
    pass "Service port metrics/9090/TCP present"
  else
    fail "Service port metrics/9090/TCP missing"
    fix_cmd "kubectl patch service/${RELEASE}-aaa-radius-server -n $NAMESPACE --type=json \\
      -p '[{\"op\":\"add\",\"path\":\"/spec/ports/-\",\"value\":{\"name\":\"metrics\",\"port\":9090,\"protocol\":\"TCP\",\"targetPort\":9090}}]'"
  fi
fi

# ── 3. RADIUS ServiceMonitor ──────────────────────────────────────────────────
section "RADIUS ServiceMonitor" || true

if ! kexists servicemonitor "${RELEASE}-aaa-radius-server"; then
  fail "ServiceMonitor ${RELEASE}-aaa-radius-server not found"
  fix_cmd "kubectl apply -f - <<'EOF'
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: ${RELEASE}-aaa-radius-server
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: aaa-radius-server
    app.kubernetes.io/instance: ${RELEASE}
    release: ${RELEASE}
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: aaa-radius-server
      app.kubernetes.io/instance: ${RELEASE}
  endpoints:
    - port: metrics
      interval: 15s
      path: /metrics
EOF"
else
  SM_JSON=$(kjson servicemonitor "${RELEASE}-aaa-radius-server")

  # release label (required for Prometheus Operator discovery)
  RELEASE_LABEL=$(echo "$SM_JSON" | python3 -c "
import json,sys
labels=json.load(sys.stdin)['metadata'].get('labels',{})
print(labels.get('release','MISSING'))
" 2>/dev/null)
  if [[ "$RELEASE_LABEL" == "$RELEASE" ]]; then
    pass "ServiceMonitor label release=${RELEASE} present (Prometheus can discover)"
  else
    fail "ServiceMonitor missing label release=${RELEASE} (Prometheus won't discover it)"
    fix_cmd "kubectl label servicemonitor/${RELEASE}-aaa-radius-server -n $NAMESPACE release=${RELEASE} --overwrite"
  fi

  # endpoint port
  SM_PORT=$(echo "$SM_JSON" | python3 -c "
import json,sys
eps=json.load(sys.stdin)['spec'].get('endpoints',[])
ports=[e.get('port') for e in eps]
print(ports[0] if ports else 'MISSING')
" 2>/dev/null)
  if [[ "$SM_PORT" == "metrics" ]]; then
    pass "ServiceMonitor endpoint port=metrics"
  else
    fail "ServiceMonitor endpoint port: expected 'metrics', got '${SM_PORT}'"
  fi

  # managed by Helm or kubectl
  MANAGED_BY=$(echo "$SM_JSON" | python3 -c "
import json,sys
a=json.load(sys.stdin)['metadata']
labels=a.get('labels',{})
annots=a.get('annotations',{})
if 'meta.helm.sh/release-name' in annots:
    print('helm')
elif 'kubectl.kubernetes.io/last-applied-configuration' in annots:
    print('kubectl')
else:
    print('unknown')
" 2>/dev/null)
  if [[ "$MANAGED_BY" == "helm" ]]; then
    pass "ServiceMonitor managed by Helm"
  else
    warn "ServiceMonitor managed by ${MANAGED_BY} (not Helm — will be adopted on next deploy)"
  fi
fi

# ── 4. Management UI ConfigMap ────────────────────────────────────────────────
section "Management UI AppConfig (pushgatewayUrl)" || true

CM_NAME="${RELEASE}-aaa-management-ui-appconfig"
if ! kexists configmap "$CM_NAME"; then
  fail "ConfigMap ${CM_NAME} not found"
else
  CONFIG_JS=$(kubectl get configmap "$CM_NAME" -n "$NAMESPACE" \
    -o jsonpath='{.data.config\.js}' 2>/dev/null)
  if echo "$CONFIG_JS" | grep -q "pushgatewayUrl"; then
    PGW_VAL=$(echo "$CONFIG_JS" | grep "pushgatewayUrl" | sed 's/.*: *//;s/[",]//g' | xargs)
    pass "config.js contains pushgatewayUrl: ${PGW_VAL}"
  else
    fail "config.js missing pushgatewayUrl"
    fix_cmd "kubectl patch configmap/${CM_NAME} -n ${NAMESPACE} --type=merge \\
  -p '{\"data\":{\"config.js\":\"window.APP_CONFIG = {\\n  apiBaseUrl: \\\"/v1\\\",\\n  oidcAuthority: \\\"http://auth.aaa.localhost/realms/aaa\\\",\\n  oidcClientId: \\\"aaa-management-ui\\\",\\n  pushgatewayUrl: \\\"http://pushgateway.aaa.localhost\\\"\\n};\\n\"}}'"
    fix_cmd "kubectl rollout restart deployment/${RELEASE}-aaa-management-ui -n ${NAMESPACE}"
  fi
fi

# ── 5. Pushgateway Ingress ────────────────────────────────────────────────────
section "Pushgateway Ingress" || true

if ! kexists ingress "${RELEASE}-prometheus-pushgateway"; then
  fail "Ingress ${RELEASE}-prometheus-pushgateway not found"
  fix_cmd "# Redeploy with: make deploy   (values-dev.yaml has prometheus-pushgateway.ingress.enabled: true)"
else
  ING_JSON=$(kjson ingress "${RELEASE}-prometheus-pushgateway")
  ING_CLASS=$(echo "$ING_JSON" | python3 -c "
import json,sys; print(json.load(sys.stdin)['spec'].get('ingressClassName','<not set>'))
" 2>/dev/null)
  ING_HOST=$(echo "$ING_JSON" | python3 -c "
import json,sys
rules=json.load(sys.stdin)['spec'].get('rules',[])
print(rules[0]['host'] if rules else 'MISSING')
" 2>/dev/null)

  if [[ "$ING_HOST" == "pushgateway.aaa.localhost" ]]; then
    pass "Ingress host pushgateway.aaa.localhost"
  else
    fail "Ingress host: expected pushgateway.aaa.localhost, got '${ING_HOST}'"
  fi

  if [[ "$ING_CLASS" == "nginx" ]]; then
    pass "Ingress ingressClassName=nginx"
  else
    warn "Ingress ingressClassName='${ING_CLASS}' (will be set to nginx on next make deploy)"
  fi
fi

# ── 6. Subchart tgz freshness ─────────────────────────────────────────────────
section "Subchart tgz freshness" || true

LOCAL_CHARTS=("aaa-radius-server" "aaa-management-ui" "subscriber-profile-api" "aaa-lookup-service" "aaa-database")

for chart in "${LOCAL_CHARTS[@]}"; do
  TGZ=$(ls "${CHART_DIR}/charts/${chart}-"*.tgz 2>/dev/null | head -1)
  SRC="${ROOT_DIR}/charts/${chart}"

  if [[ -z "$TGZ" ]]; then
    fail "${chart}: tgz not found in ${CHART_DIR}/charts/"
    continue
  fi

  if [[ ! -d "$SRC" ]]; then
    warn "${chart}: source dir ${SRC} not found (external chart?)"
    continue
  fi

  TGZ_TIME=$(stat -c %Y "$TGZ" 2>/dev/null || stat -f %m "$TGZ" 2>/dev/null)
  # find newest file in source dir
  NEWEST_SRC=$(find "$SRC" -type f ! -path '*/.git/*' -printf '%T@ %p\n' 2>/dev/null \
    | sort -rn | head -1 | awk '{print $1}' | cut -d. -f1)

  if [[ -z "$NEWEST_SRC" ]]; then
    warn "${chart}: could not determine source mtime"
    continue
  fi

  if (( NEWEST_SRC > TGZ_TIME )); then
    NEWER_FILE=$(find "$SRC" -type f ! -path '*/.git/*' -newer "$TGZ" | head -3 | tr '\n' ' ')
    fail "${chart}: tgz is STALE (source newer by $(( NEWEST_SRC - TGZ_TIME ))s) — newer files: ${NEWER_FILE}"
    fix_cmd "# Repack with Python (helm not required):"
    fix_cmd "python3 scripts/repack-charts.py ${chart}"
  else
    pass "${chart}: tgz is up-to-date"
  fi
done

# ── 7. Grafana Dashboard ConfigMap version ────────────────────────────────────
section "Grafana Dashboard ConfigMap" || true

DASH_CM="aaa-platform-grafana-aaa-dashboard"
DASH_FILE="${CHART_DIR}/files/aaa-platform-dashboard.json"

if [[ ! -f "$DASH_FILE" ]]; then
  warn "Dashboard source file not found: ${DASH_FILE}"
else
  # Use cat|stdin so Python doesn't need to resolve the Git Bash POSIX path itself
  FILE_VER=$(cat "$DASH_FILE" \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null)
  CM_VER=$(kubectl get configmap "$DASH_CM" -n "$NAMESPACE" \
    -o jsonpath='{.data.aaa-platform-dashboard\.json}' 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null)

  if [[ "$FILE_VER" == "$CM_VER" ]]; then
    pass "Dashboard ConfigMap version matches source (v${FILE_VER})"
  else
    fail "Dashboard version mismatch: source=v${FILE_VER}, ConfigMap=v${CM_VER}"
    fix_cmd "# Push updated dashboard to ConfigMap (from repo root):"
    fix_cmd "python3 scripts/push-dashboard-cm.py"
  fi

  # Also check first row to catch section-reorder drift
  FILE_FIRST_ROW=$(cat "$DASH_FILE" | python3 -c "
import json,sys
d=json.load(sys.stdin)
rows=[p for p in d['panels'] if p.get('type')=='row']
print(rows[0].get('title','?')[:40] if rows else '?')
" 2>/dev/null)
  CM_FIRST_ROW=$(kubectl get configmap "$DASH_CM" -n "$NAMESPACE" \
    -o jsonpath='{.data.aaa-platform-dashboard\.json}' 2>/dev/null \
    | python3 -c "
import json,sys
d=json.load(sys.stdin)
rows=[p for p in d['panels'] if p.get('type')=='row']
print(rows[0].get('title','?')[:40] if rows else '?')
" 2>/dev/null)

  if [[ "$FILE_FIRST_ROW" == "$CM_FIRST_ROW" ]]; then
    pass "Dashboard section order matches (first row: ${FILE_FIRST_ROW:0:40})"
  else
    fail "Dashboard section order mismatch: source='${FILE_FIRST_ROW:0:40}', ConfigMap='${CM_FIRST_ROW:0:40}'"
    fix_cmd "python3 scripts/push-dashboard-cm.py"
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}══ Summary ══${RESET}"
echo -e "  ${GREEN}PASS: ${PASS}${RESET}  ${RED}FAIL: ${FAIL}${RESET}  ${YELLOW}WARN: ${WARN}${RESET}"

if (( FAIL > 0 )); then
  echo -e "\n  ${RED}Drift detected.${RESET} Run with --fix to see remediation commands."
  echo -e "  Or run ${BOLD}make deploy${RESET} to reconcile via Helm."
  exit 1
elif (( WARN > 0 )); then
  echo -e "\n  ${YELLOW}Minor drift (warnings only). Run ${BOLD}make deploy${RESET} to fully reconcile.${RESET}"
  exit 0
else
  echo -e "\n  ${GREEN}All checks passed. Cluster matches chart sources.${RESET}"
  exit 0
fi
