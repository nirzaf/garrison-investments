from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

SQL_MARKERS = ("CREATE TABLE", "ALTER TABLE", "COPY ", "INSERT INTO", "SET ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_sql_preview(path: Path) -> str:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as file:
        return file.read(16 * 1024)


def inspect_backup(path: Path) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"Backup file not found: {resolved}")
    preview = read_sql_preview(resolved)
    markers = [marker for marker in SQL_MARKERS if marker in preview.upper()]
    if not markers:
        raise ValueError("Backup does not look like a PostgreSQL plain SQL dump.")
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
        "markers": markers,
    }


def restore_backup(backup_path: Path, database_url: str) -> None:
    if backup_path.suffix == ".gz":
        with tempfile.NamedTemporaryFile(suffix=".sql") as temp_file:
            with gzip.open(backup_path, "rb") as source:
                temp_file.write(source.read())
            temp_file.flush()
            subprocess.run(
                [
                    "psql",
                    "--set",
                    "ON_ERROR_STOP=on",
                    "--single-transaction",
                    "--dbname",
                    database_url,
                    "--file",
                    temp_file.name,
                ],
                check=True,
            )
    else:
        subprocess.run(
            [
                "psql",
                "--set",
                "ON_ERROR_STOP=on",
                "--single-transaction",
                "--dbname",
                database_url,
                "--file",
                str(backup_path),
            ],
            check=True,
        )


def render_markdown(result: dict[str, object]) -> str:
    restore_status = "executed" if result["restore_executed"] else "validated-only"
    lines = [
        "# Backup Restore Dry-Run Evidence",
        "",
        f"Generated at: `{result['generated_at']}`",
        f"Backup file: `{result['path']}`",
        f"SHA-256: `{result['sha256']}`",
        f"Size bytes: `{result['size_bytes']}`",
        f"SQL markers: `{', '.join(result['markers'])}`",
        f"Restore status: `{restore_status}`",
        "",
    ]
    if result.get("database_url_redacted"):
        lines.append(f"Restore database: `{result['database_url_redacted']}`")
        lines.append("")
    return "\n".join(lines)


def redact_database_url(url: str) -> str:
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    host = rest.rsplit("@", 1)[1]
    return f"{scheme}://***:***@{host}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and optionally restore a backup dump.")
    parser.add_argument("--backup-file", type=Path, required=True)
    parser.add_argument("--restore-database-url", default=os.getenv("RESTORE_DATABASE_URL"))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = inspect_backup(args.backup_file)
    result["generated_at"] = datetime.now(UTC).isoformat()
    result["restore_executed"] = bool(args.restore_database_url)
    if args.restore_database_url:
        restore_backup(args.backup_file, args.restore_database_url)
        result["database_url_redacted"] = redact_database_url(args.restore_database_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(result), encoding="utf-8")
    print(f"Wrote restore dry-run evidence to {args.output}")


if __name__ == "__main__":
    main()
