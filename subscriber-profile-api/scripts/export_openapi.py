"""Export the FastAPI app's OpenAPI schema to a YAML file.

Usage:
    pip install pyyaml
    python scripts/export_openapi.py [--output PATH]

Default output: subscriber-profile-api/openapi.yaml

The script imports `app.main:app` (no DB connection, no uvicorn startup) and
serializes `app.openapi()` to YAML. Re-run after API changes to refresh the
committed spec.
"""
import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve().parent
    service_root = here.parent  # subscriber-profile-api/
    default_out = service_root / "openapi.yaml"

    parser = argparse.ArgumentParser(description="Export OpenAPI schema to YAML.")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=default_out,
        help=f"Destination YAML path (default: {default_out})",
    )
    args = parser.parse_args()

    try:
        import yaml  # type: ignore
    except ImportError:
        print(
            "error: PyYAML is not installed. Install it first:\n"
            "    pip install pyyaml",
            file=sys.stderr,
        )
        return 2

    # Make `from app.main import app` resolve regardless of cwd.
    sys.path.insert(0, str(service_root))

    # Sentinel env so module-level config doesn't fail. The script never
    # starts uvicorn, never opens a DB connection, never runs the lifespan.
    os.environ.setdefault("PRIMARY_URL", "postgresql://export:export@localhost:5432/export")
    os.environ.setdefault("JWT_SKIP_VERIFY", "true")

    from app.main import app  # noqa: E402

    schema = app.openapi()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        yaml.safe_dump(schema, f, sort_keys=False, allow_unicode=True, width=120)

    paths = schema.get("paths", {})
    operation_count = sum(
        1
        for methods in paths.values()
        for method in methods
        if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}
    )
    rel = args.output.relative_to(service_root) if args.output.is_relative_to(service_root) else args.output
    print(f"wrote {rel} ({len(paths)} paths, {operation_count} operations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
