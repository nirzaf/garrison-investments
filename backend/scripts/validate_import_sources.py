from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.import_service import TEMPLATE_COLUMNS, ImportService


@dataclass(frozen=True)
class ValidationResult:
    template_type: str
    path: Path
    row_count: int
    errors: list[dict[str, object]]

    @property
    def valid(self) -> bool:
        return not self.errors


def default_template_sources() -> list[tuple[str, Path]]:
    root = Path(__file__).resolve().parents[2] / "docs" / "import_templates"
    return [(template, root / f"{template}.csv") for template in sorted(TEMPLATE_COLUMNS)]


def parse_source(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise ValueError("--source must use template_type=/path/to/file.csv")
    template_type, path = raw.split("=", 1)
    if template_type not in TEMPLATE_COLUMNS:
        raise ValueError(f"Unknown template type: {template_type}")
    return template_type, Path(path).expanduser()


def validate_source(template_type: str, path: Path) -> ValidationResult:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        return ValidationResult(
            template_type=template_type,
            path=resolved,
            row_count=0,
            errors=[{"row": 1, "field": "file", "message": "File not found."}],
        )
    service = ImportService.__new__(ImportService)
    rows = service._parse(template_type, resolved.read_bytes())
    errors = [error.model_dump() for error in service._validate_rows(template_type, rows)]
    return ValidationResult(
        template_type=template_type,
        path=resolved,
        row_count=len(rows),
        errors=errors,
    )


def render_markdown(results: list[ValidationResult]) -> str:
    lines = [
        "# Import Source Validation Evidence",
        "",
        f"Generated at: `{datetime.now(UTC).isoformat()}`",
        "",
        "| Template | File | Rows | Result | Errors |",
        "| --- | --- | ---: | --- | ---: |",
    ]
    for result in results:
        status = "pass" if result.valid else "fail"
        row = (
            f"| {result.template_type} | `{result.path}` | {result.row_count} | "
            f"{status} | {len(result.errors)} |"
        )
        lines.append(
            row
        )
    lines.append("")
    for result in results:
        if result.valid:
            continue
        lines.append(f"## {result.template_type} Errors")
        lines.append("")
        for error in result.errors:
            lines.append(
                f"- Row {error['row']}, `{error['field']}`: {error['message']}"
            )
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate launch import source spreadsheets.")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Template source in template_type=/path/to/file.csv or .xlsx form.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sources = (
        [parse_source(source) for source in args.source]
        if args.source
        else default_template_sources()
    )
    results = [validate_source(template_type, path) for template_type, path in sources]
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_markdown(results), encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(
                [
                    {
                        "template_type": result.template_type,
                        "path": str(result.path),
                        "row_count": result.row_count,
                        "valid": result.valid,
                        "errors": result.errors,
                    }
                    for result in results
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
    if args.check and any(not result.valid for result in results):
        raise SystemExit(1)
    if args.output:
        print(f"Wrote import validation evidence to {args.output}")


if __name__ == "__main__":
    main()
