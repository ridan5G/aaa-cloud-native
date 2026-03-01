"""
push_metrics.py — read JUnit XML + timing CSV and push to Prometheus Pushgateway.
Called by run_all.sh after pytest exits.
"""
import argparse
import csv
import sys
import time
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen
from urllib.error import URLError


def parse_junit(xml_path: str) -> dict:
    """Extract pass/fail/skip counts and per-module breakdowns from JUnit XML."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Handle both <testsuites> and <testsuite> as root
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    totals = {"passed": 0, "failed": 0, "skipped": 0, "duration": 0.0}
    modules: dict[str, dict] = {}

    for suite in suites:
        name = suite.get("name", "unknown")
        tests    = int(suite.get("tests",    0))
        failures = int(suite.get("failures", 0))
        errors   = int(suite.get("errors",   0))
        skipped  = int(suite.get("skipped",  0))
        duration = float(suite.get("time",   0))

        passed = tests - failures - errors - skipped
        modules[name] = {
            "passed":   passed,
            "failed":   failures + errors,
            "skipped":  skipped,
            "duration": duration,
        }
        totals["passed"]   += passed
        totals["failed"]   += failures + errors
        totals["skipped"]  += skipped
        totals["duration"] += duration

    totals["exit_code"] = 0 if totals["failed"] == 0 else 1
    return {"totals": totals, "modules": modules}


def parse_timing(csv_path: str) -> dict[str, float]:
    """Read optional timing.csv — returns {test_name: latency_ms}."""
    timings: dict[str, float] = {}
    try:
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                timings[row["test"]] = float(row["latency_ms"])
    except FileNotFoundError:
        pass
    return timings


def build_pushgateway_body(data: dict, timings: dict, suite: str = "aaa") -> str:
    """Build the Prometheus text-format body for a single Pushgateway PUT."""
    lines: list[str] = []
    now = int(time.time())

    def g(name: str, labels: str, value: float | int) -> None:
        lines.append(f"# TYPE {name} gauge")
        lines.append(f'{name}{{{labels}}} {value}')

    totals = data["totals"]
    g("regression_test_passed_total",  f'suite="{suite}"', totals["passed"])
    g("regression_test_failed_total",  f'suite="{suite}"', totals["failed"])
    g("regression_test_skipped_total", f'suite="{suite}"', totals["skipped"])
    g("regression_suite_duration_seconds", f'suite="{suite}"', totals["duration"])
    g("regression_suite_exit_code",    f'suite="{suite}"', totals["exit_code"])
    g("regression_last_run_timestamp", f'suite="{suite}"', now)

    for module, counts in data["modules"].items():
        m = module.replace('"', "'")
        g("regression_test_passed_total",   f'suite="{suite}",module="{m}"', counts["passed"])
        g("regression_test_failed_total",   f'suite="{suite}",module="{m}"', counts["failed"])
        g("regression_test_duration_seconds", f'suite="{suite}",module="{m}"', counts["duration"])

    for test_name, latency in timings.items():
        t = test_name.replace('"', "'")
        g("regression_lookup_latency_p99_ms", f'suite="{suite}",test="{t}"', latency)

    return "\n".join(lines) + "\n"


def push(gateway_url: str, job: str, body: str) -> None:
    url = f"{gateway_url.rstrip('/')}/metrics/job/{job}"
    req = Request(url, data=body.encode(), method="PUT",
                  headers={"Content-Type": "text/plain; charset=utf-8"})
    with urlopen(req, timeout=10) as resp:
        if resp.status not in (200, 202):
            raise RuntimeError(f"Pushgateway returned HTTP {resp.status}")
    print(f"Metrics pushed to {url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit-xml",    required=True)
    ap.add_argument("--pushgateway",  required=True)
    ap.add_argument("--timing-csv",   default="results/timing.csv")
    ap.add_argument("--suite",        default="aaa")
    args = ap.parse_args()

    data    = parse_junit(args.junit_xml)
    timings = parse_timing(args.timing_csv)
    body    = build_pushgateway_body(data, timings, args.suite)

    print(f"Suite totals: passed={data['totals']['passed']} "
          f"failed={data['totals']['failed']} "
          f"skipped={data['totals']['skipped']} "
          f"duration={data['totals']['duration']:.1f}s")

    try:
        push(args.pushgateway, "aaa_regression", body)
    except (URLError, RuntimeError) as ex:
        print(f"WARNING: push failed: {ex}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
