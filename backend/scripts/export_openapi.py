"""Export the FastAPI OpenAPI schema to ``docs/openapi.json``.

Import-only: building the schema never opens a database, Redis, or object-storage
connection, so this runs in CI without any service containers.

Usage::

    python scripts/export_openapi.py          # rewrite docs/openapi.json
    python scripts/export_openapi.py --check  # exit 1 when the committed file is stale

``docs/openapi.json`` is the source for ``frontend/src/api/schema.d.ts``; after
rewriting it run ``npm run api:types`` in ``frontend/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "openapi.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def render_schema() -> str:
    """Return the canonical serialization of the live application schema."""
    from app.main import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or verify docs/openapi.json.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against the committed file and exit 1 on drift instead of writing",
    )
    args = parser.parse_args(argv)

    rendered = render_schema()
    relative_path = SCHEMA_PATH.relative_to(REPO_ROOT)
    committed = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else None

    if args.check:
        if committed == rendered:
            print(f"{relative_path} is current.")
            return 0
        if committed is None:
            print(f"{relative_path} is missing.", file=sys.stderr)
        else:
            print(f"{relative_path} is stale.", file=sys.stderr)
        print(
            "Regenerate with: cd backend && python scripts/export_openapi.py "
            "&& cd ../frontend && npm run api:types",
            file=sys.stderr,
        )
        return 1

    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {relative_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())