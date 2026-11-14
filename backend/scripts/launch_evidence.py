from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__:
    from .release_contract import VERSION, ContractError, Validation
else:
    from release_contract import VERSION, ContractError, Validation  # type: ignore[no-redef]


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
    approver = args.approver
    # A workflow actor may have triggered collection without performing the
    # production operation. Keep the operator independent from the approver
    # and require the caller to identify the person who actually executed it.
    raw_operator = getattr(args, "operator", None)
    operator = raw_operator.strip() if isinstance(raw_operator, str) else None
    if target == "production" and not operator:
        raise ValueError("Production evidence collection requires an explicit operator identity.")

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
        "commit": args.commit or env.get("GITHUB_SHA"),
        "run_url": args.run_url or build_run_url(env),
        "approver": approver,
        "operator": operator,
        "status": "collected_incomplete",
        "accepted_scope_complete": False,
        "ready_for_authorized_deployment": False,
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
        "Status: collected / incomplete",
        "",
        f"Generated at: `{evidence['generated_at']}`",
        f"Target: `{evidence['target']}`",
        f"Commit: `{evidence.get('commit') or 'not recorded'}`",
        f"Run URL: `{evidence.get('run_url') or 'not recorded'}`",
        f"Operator: `{evidence.get('operator') or 'not recorded'}`",
        f"Reported approver: `{evidence.get('approver') or 'not recorded'}`",
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
            lines.append(f"| {check['label']} | `{check['url']}` | {check['status']} | {result} |")
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
            lines.append(row)
    else:
        lines.append("| not supplied | not supplied | not supplied | 0 |")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture deployment and launch evidence.")
    parser.add_argument("--target", choices=["production", "test"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--health-url")
    parser.add_argument("--readiness-url")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--approver")
    parser.add_argument("--operator")
    parser.add_argument("--run-url")
    parser.add_argument("--commit")
    parser.add_argument("--backup-object")
    parser.add_argument("--restore-log")
    parser.add_argument("--uat-signoff")
    parser.add_argument("--template-signoff")
    parser.add_argument("--migration-source", action="append", default=[])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--trust-registry", type=Path)
    parser.add_argument("--phase", choices=["predeploy", "final"])
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if any(
        (args.manifest, args.evidence_root, args.trust_registry, args.phase, args.validate_only)
    ):
        if not all(
            (
                args.manifest,
                args.evidence_root,
                args.trust_registry,
                args.phase,
                args.validate_only,
                args.commit,
            )
        ):
            parser.error(
                "Strict validation requires --manifest, --evidence-root, --trust-registry, "
                "--phase, --validate-only and --commit."
            )
        root = args.evidence_root.resolve()
        verdicts = root / "verdicts"
        inputs = {args.manifest.resolve(), args.trust_registry.resolve()}
        for output in (args.output, args.json_output):
            if output is None:
                continue
            location = output.resolve()
            if location in inputs or (
                location.is_relative_to(root) and not location.is_relative_to(verdicts)
            ):
                parser.error(
                    "Verdicts belong outside the input evidence or under its verdicts directory."
                )
    elif args.target == "test":
        parser.error("The test target is reserved for strict fixture validation.")
    if args.json_output and args.json_output.resolve() == args.output.resolve():
        parser.error("Markdown and JSON outputs must be distinct.")
    return args


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".verdict-", delete=False
        ) as file:
            pending = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        pending.replace(path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def strict_verdict(args: argparse.Namespace, env: dict[str, str]) -> tuple[dict[str, Any], int]:
    try:
        if env.get("GITHUB_SHA") and env["GITHUB_SHA"] != args.commit:
            raise ContractError(3, "The explicit source SHA differs from the GitHub environment.")
        verifier = Validation(
            args.evidence_root,
            args.trust_registry,
            phase=args.phase,
            sha=args.commit,
            target=args.target,
            token=env.get("GH_TOKEN") or env.get("GITHUB_TOKEN"),
            actor=args.operator or env.get("GITHUB_TRIGGERING_ACTOR") or env.get("GITHUB_ACTOR"),
        )
        return verifier.run(args.manifest), 0
    except (ContractError, OSError, TypeError, ValueError, KeyError) as error:
        reason = str(error) if isinstance(error, ContractError) else "Invalid evidence input."
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "phase": args.phase,
            "status": "blocked",
            "accepted_scope_complete": False,
            "ready_for_authorized_deployment": False,
            "source_sha": args.commit,
            "target_environment": args.target,
            "validator_version": VERSION,
            "blockers": [reason],
        }, error.code if isinstance(error, ContractError) else 2


def render_verdict(verdict: dict[str, Any]) -> str:
    lines = [
        "# Release evidence verdict",
        "",
        f"Phase `{verdict['phase']}` returned `{verdict['status']}`.",
        f"Source `{verdict['source_sha']}` targets `{verdict['target_environment']}`.",
        f"Accepted scope complete is `{str(verdict['accepted_scope_complete']).lower()}`.",
    ]
    if verdict["blockers"]:
        lines.extend(["", *(f"- {reason}" for reason in verdict["blockers"])])
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    env = dict(os.environ)
    if args.phase:
        evidence, status = strict_verdict(args, env)
        markdown = render_verdict(evidence)
    else:
        evidence, status = collect_evidence(args, env), 0
        markdown = render_markdown(evidence)
    atomic_write(args.output, markdown)
    if args.json_output:
        atomic_write(args.json_output, json.dumps(evidence, indent=2) + "\n")
    print(f"Wrote launch evidence to {args.output}")
    if status:
        raise SystemExit(status)


if __name__ == "__main__":
    main()
