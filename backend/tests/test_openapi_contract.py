"""Guardrail: the committed OpenAPI document must match the live application.

No database is required — ``app.openapi()`` is built from route metadata only.
Regenerate with ``python scripts/export_openapi.py`` (see ``scripts/export_openapi.py``).
"""

import json
from pathlib import Path

from app.main import app

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def test_committed_openapi_matches_application() -> None:
    assert SCHEMA_PATH.exists(), f"{SCHEMA_PATH} is missing; run scripts/export_openapi.py"
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    generated = app.openapi()
    assert generated == committed, (
        "docs/openapi.json has drifted from the application. Run "
        "`cd backend && python scripts/export_openapi.py` then "
        "`cd frontend && npm run api:types`."
    )


def test_committed_openapi_is_canonically_serialized() -> None:
    """The export script's byte-for-byte ``--check`` must agree with this test."""
    committed_text = SCHEMA_PATH.read_text(encoding="utf-8")
    canonical = json.dumps(json.loads(committed_text), indent=2, sort_keys=True) + "\n"
    assert committed_text == canonical