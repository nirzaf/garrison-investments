from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class FileEvidence:
    label: str
    path: Path
    sha256: str
    size_bytes: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_run_url(env: dict[str, str]) -> str | None:
    server = env.get("GITHUB_SERVER_URL")
    repository = env.get("GITHUB_REPOSITORY")
    run_id = env.get("GITHUB_RUN_ID")
    if not server or not repository or not run_id:
        return None
    return f"{server.rstrip('/')}/{repository}/actions/runs/{run_id}"


def file_evidence(label: str, raw_path: str | None) -> FileEvidence | None:
    if not raw_path:
        return None
    path = Path(raw_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{label} file not found: {path}")
    return FileEvidence(
        label=label,
        path=path,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
    )


def check_url(url: str, timeout: int) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "garrison-launch-evidence/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(800).decode("utf-8", errors="replace")
            return {
                "url": url,
                "ok": 200 <= response.status < 300,
                "status": response.status,
                "body_preview": body,
            }
    except HTTPError as exc:
        return {
            "url": url,
            "ok": False,
            "status": exc.code,
            "body_preview": exc.read(800).decode("utf-8", errors="replace"),
        }
    except URLError as exc:
        return {"url": url, "ok": False, "status": None, "body_preview": str(exc.reason)}


def collect_evidence(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    generated_at = datetime.now(UTC).isoformat()
    target = args.target
    approver = args.approver or env.get("GITHUB_TRIGGERING_ACTOR") or env.get("GITHUB_ACTOR")
    if target == "production" and not approver:
        raise ValueError("Production evidence requires --approver or a GitHub actor environment.")

    checks = []
    for label, url in (("health", args.health_url), ("readiness", args.readiness_url)):
        if url:
            result = check_url(url, args.timeout)
            result["label"] = label
            checks.append(result)
            if not result["ok"]:
                raise RuntimeError(f"{label} check failed for {url}")

    evidence_files = [
        item
        for item in [
            file_evidence("restore_log", args.restore_log),
            file_evidence("uat_signoff", args.uat_signoff),
            file_evidence("template_signoff", args.template_signoff),
            *(file_evidence("migration_source", path) for path in args.migration_source),
        ]
        if item is not None
    ]

    return {
        "generated_at": generated_at,
        "target": target,
        "commit": env.get("GITHUB_SHA") or args.commit,
        "run_url": args.run_url or build_run_url(env),
        "approver": approver,
        "backup_object": args.backup_object,
        "checks": checks,
        "files": [
            {
                "label": item.label,
                "path": str(item.path),
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in evidence_files
        ],
    }


def render_markdown(evidence: dict[str, Any]) -> str:
    lines = [
        "# Launch Evidence Record",
        "",
        f"Generated at: `{evidence['generated_at']}`",
        f"Target: `{evidence['target']}`",
        f"Commit: `{evidence.get('commit') or 'not recorded'}`",
        f"Run URL: `{evidence.get('run_url') or 'not recorded'}`",
        f"Approver/operator: `{evidence.get('approver') or 'not recorded'}`",
        f"Backup object: `{evidence.get('backup_object') or 'not recorded'}`",
        "",
        "## Runtime Checks",
        "",
        "| Check | URL | Status | Result |",
        "| --- | --- | ---: | --- |",
    ]
    checks = evidence.get("checks") or []
    if checks:
        for check in checks:
            result = "pass" if check["ok"] else "fail"
            lines.append(
                f"| {check['label']} | `{check['url']}` | {check['status']} | {result} |"
            )
    else:
        lines.append("| not supplied | not supplied |  | not checked |")

    lines.extend(
        [
            "",
            "## Attached Evidence Files",
            "",
            "| Label | Path | SHA-256 | Size |",
            "| --- | --- | --- | ---: |",
        ]
    )
    files = evidence.get("files") or []
    if files:
        for item in files:
            row = (
                f"| {item['label']} | `{item['path']}` | "
                f"`{item['sha256']}` | {item['size_bytes']} |"
            )
            lines.append(
                row
            )
    else:
        lines.append("| not supplied | not supplied | not supplied | 0 |")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture deployment and launch evidence.")
    parser.add_argument("--target", choices=["staging", "production"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--health-url")
    parser.add_argument("--readiness-url")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--approver")
    parser.add_argument("--run-url")
    parser.add_argument("--commit")
    parser.add_argument("--backup-object")
    parser.add_argument("--restore-log")
    parser.add_argument("--uat-signoff")
    parser.add_argument("--template-signoff")
    parser.add_argument("--migration-source", action="append", default=[])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    evidence = collect_evidence(args, dict(os.environ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(evidence), encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"Wrote launch evidence to {args.output}")


if __name__ == "__main__":
    main()
