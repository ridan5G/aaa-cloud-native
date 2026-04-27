#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="aaa-dev"
REGISTRY_PORT="5111"

echo "── Creating k3d local registry ─────────────────────────────"
k3d registry create aaa-registry.localhost --port ${REGISTRY_PORT} 2>/dev/null || true

echo "── Creating k3d cluster: ${CLUSTER_NAME} ───────────────────"
k3d cluster create ${CLUSTER_NAME} \
  --api-port 6550 \
  --port "80:80@loadbalancer" \
  --port "443:443@loadbalancer" \
  --port "9090:9090@loadbalancer" \
  --port "9091:9091@loadbalancer" \
  --port "1812:1812/udp@loadbalancer" \
  --registry-use k3d-aaa-registry.localhost:${REGISTRY_PORT} \
  --agents 2 \
  --k3s-arg "--disable=traefik@server:*" \
  --k3s-arg "--disable=servicelb@server:*" \
  --wait

echo "── Merging kubeconfig ──────────────────────────────────────"
k3d kubeconfig merge ${CLUSTER_NAME} --kubeconfig-switch-context

echo "── Verifying cluster ───────────────────────────────────────"
kubectl get nodes

echo "── Installing nginx-ingress (replaces k3s Traefik) ────────"
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx --force-update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.service.type=NodePort \
  --set controller.hostPort.enabled=true \
  --set controller.hostPort.ports.http=80 \
  --set controller.hostPort.ports.https=443 \
  --wait

echo "── Installing CloudNativePG operator ──────────────────────"
helm repo add cnpg https://cloudnative-pg.github.io/charts --force-update
helm upgrade --install cnpg cnpg/cloudnative-pg \
  --namespace cnpg-system --create-namespace \
  --wait

echo "── Cluster ready! ──────────────────────────────────────────"
kubectl get pods -A
