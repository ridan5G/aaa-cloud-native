#!/usr/bin/env python3
"""Push charts/aaa-platform/files/aaa-platform-dashboard.json to the live Grafana ConfigMap."""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "charts", "aaa-platform", "files", "aaa-platform-dashboard.json")
NAMESPACE = os.environ.get("NAMESPACE", "aaa-platform")
CM_NAME   = "aaa-platform-grafana-aaa-dashboard"

with open(DASH, encoding="utf-8") as f:
    content = f.read()

ver = json.loads(content).get("version", "?")
print(f"Pushing dashboard v{ver} → ConfigMap {CM_NAME} in {NAMESPACE}")

manifest = {
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": CM_NAME,
        "namespace": NAMESPACE,
        "labels": {"grafana_dashboard": "1"},
        "annotations": {"grafana_folder": "AAA Platform"},
    },
    "data": {"aaa-platform-dashboard.json": content},
}

with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tf:
    json.dump(manifest, tf, ensure_ascii=False)
    tmp_path = tf.name

try:
    result = subprocess.run(["kubectl", "apply", "-f", tmp_path], capture_output=True, text=True)
    print(result.stdout.strip() or result.stderr.strip())
    sys.exit(result.returncode)
finally:
    os.unlink(tmp_path)
