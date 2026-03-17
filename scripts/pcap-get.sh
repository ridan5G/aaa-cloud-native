#!/usr/bin/env bash
# scripts/pcap-get.sh — copy /captures/test.pcap from the pcap PVC to a local file.
#
# Usage:  bash scripts/pcap-get.sh <namespace> <pvc-name> [output-file]
#
# Spins up a disposable alpine pod that mounts the PVC, runs kubectl cp,
# then deletes the pod.  Works even after the test Job pod has exited.
set -euo pipefail

NAMESPACE="${1:?namespace required}"
PVC_NAME="${2:?pvc-name required}"
OUT_FILE="${3:-./test.pcap}"
HELPER_POD="pcap-reader"

# ── Verify the PVC exists ────────────────────────────────────────────────────
if ! kubectl get pvc "${PVC_NAME}" -n "${NAMESPACE}" -o name >/dev/null 2>&1; then
  echo "ERROR: PVC '${PVC_NAME}' not found in namespace '${NAMESPACE}'."
  echo "       Did you run 'make test PCAP=true'?"
  exit 1
fi

# ── Remove any leftover helper pod from a previous failed run ────────────────
kubectl delete pod "${HELPER_POD}" -n "${NAMESPACE}" --ignore-not-found --wait=true 2>/dev/null

# ── Launch a temporary pod that mounts the PVC ──────────────────────────────
echo "Launching helper pod '${HELPER_POD}' to mount PVC '${PVC_NAME}'..."
OVERRIDE=$(printf \
  '{"spec":{"volumes":[{"name":"cap","persistentVolumeClaim":{"claimName":"%s"}}],"containers":[{"name":"reader","image":"alpine","command":["sleep","infinity"],"volumeMounts":[{"name":"cap","mountPath":"/cap"}]}]}}' \
  "${PVC_NAME}")

kubectl run "${HELPER_POD}" \
  -n "${NAMESPACE}" \
  --image=alpine \
  --restart=Never \
  --overrides="${OVERRIDE}"

kubectl wait pod "${HELPER_POD}" \
  -n "${NAMESPACE}" \
  --for=condition=Ready \
  --timeout=60s

# ── Copy the file ────────────────────────────────────────────────────────────
echo "Copying /cap/test.pcap → ${OUT_FILE} ..."
kubectl cp "${NAMESPACE}/${HELPER_POD}:/cap/test.pcap" "${OUT_FILE}"

# ── Clean up ─────────────────────────────────────────────────────────────────
kubectl delete pod "${HELPER_POD}" -n "${NAMESPACE}" --ignore-not-found

FSIZE=$(du -sh "${OUT_FILE}" 2>/dev/null | cut -f1)
echo ""
echo "══════════════════════════════════════════════════════════════"
echo " Saved: ${OUT_FILE}  (${FSIZE:-?})"
echo " Open : wireshark ${OUT_FILE}"
echo "══════════════════════════════════════════════════════════════"
