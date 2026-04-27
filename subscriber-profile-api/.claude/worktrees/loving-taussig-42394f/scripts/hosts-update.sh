#!/usr/bin/env bash
set -euo pipefail

# Updates WSL2 /etc/hosts with AAA platform local DNS entries.
# Also prints instructions for Windows hosts file.

HOSTS=(
  "lookup.aaa.localhost"
  "provisioning.aaa.localhost"
  "ui.aaa.localhost"
  "grafana.aaa.localhost"
  "prometheus.aaa.localhost"
)

for h in "${HOSTS[@]}"; do
  if grep -q "$h" /etc/hosts; then
    echo "  already present: $h"
  else
    echo "127.0.0.1  $h" | sudo tee -a /etc/hosts
    echo "  added: $h"
  fi
done

echo ""
echo "WSL2 /etc/hosts updated."
echo ""
echo "NOTE: also add these entries to C:\\Windows\\System32\\drivers\\etc\\hosts on Windows:"
echo ""
for h in "${HOSTS[@]}"; do
  echo "  127.0.0.1  $h"
done
