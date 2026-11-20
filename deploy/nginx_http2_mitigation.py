#!/usr/bin/env python3
"""Prepare an isolated, reversible HTTP/2-off Nginx Compose overlay.

This helper only copies three reviewed production virtual-host files and writes
an override for the Nginx service. It never edits a source config, starts a
container, changes the image, or touches the forward097 incident records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys


CONFIGS = {
    "portal": ("portal.conf", "/etc/nginx/conf.d/default.conf"),
    "grafana": ("grafana.conf.template", "/etc/nginx/templates/grafana.conf.template"),
    "support": ("support.conf", "/etc/nginx/conf.d/support.conf"),
}
PATCHED_IMAGE = (
    "nginx:1.30.7-alpine@sha256:"
    "caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3"
)
OLD_HTTP2_LISTEN = re.compile(r"^(?P<indent>[ \t]*)listen\s+443\s+ssl\s+http2;[ \t]*$", re.MULTILINE)
TLS_LISTEN = re.compile(r"^[ \t]*listen\s+443\s+ssl;[ \t]*$", re.MULTILINE)
HTTP2_ON = re.compile(r"^[ \t]*http2\s+on;[ \t]*$", re.MULTILINE)


def disable_http2(text: str, *, name: str) -> str:
    """Disable HTTP/2 for one TLS server without changing other config lines."""
    old_listeners = list(OLD_HTTP2_LISTEN.finditer(text))
    tls_listeners = list(TLS_LISTEN.finditer(text))
    http2_directives = list(HTTP2_ON.finditer(text))

    if len(old_listeners) == 1 and not tls_listeners and not http2_directives:
        result = OLD_HTTP2_LISTEN.sub(r"\g<indent>listen 443 ssl;", text, count=1)
    elif len(old_listeners) == 0 and len(tls_listeners) == 1 and len(http2_directives) == 1:
        result = HTTP2_ON.sub("", text, count=1)
    else:
        raise ValueError(f"{name} must contain exactly one recognized HTTP/2 TLS listener.")

    if OLD_HTTP2_LISTEN.search(result) or HTTP2_ON.search(result):
        raise ValueError(f"{name} still enables HTTP/2 after transformation.")
    if len(TLS_LISTEN.findall(result)) != 1:
        raise ValueError(f"{name} must retain exactly one HTTPS listener.")
    if name == "support" and (
        "include /etc/nginx/ssl/support-allowlist.conf;" not in result
        or not re.search(r"^[ \t]*deny all;[ \t]*$", result, re.MULTILINE)
    ):
        raise ValueError("The Super Admin virtual host must retain its source allowlist and deny-all rule.")
    return result


def _read_source(path: Path, *, name: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{name} source must be a regular file, not a symlink.")
    return path.read_text(encoding="utf-8")


def _compose_overlay(output_dir: Path) -> str:
    lines = ["services:", "  nginx:", "    volumes:"]
    for key, (filename, target) in CONFIGS.items():
        source = json.dumps(str(output_dir / filename), ensure_ascii=False)
        destination = json.dumps(target)
        lines.extend(
            (
                "      - type: bind",
                f"        source: {source}",
                f"        target: {destination}",
                "        read_only: true",
            )
        )
    return "\n".join(lines) + "\n"


def _patched_image_overlay() -> str:
    return (
        "services:\n"
        "  nginx:\n"
        f"    image: {json.dumps(PATCHED_IMAGE)}\n"
        "    pull_policy: never\n"
    )


def prepare_overlay(sources: dict[str, Path], output_dir: Path) -> dict[str, str]:
    """Write transformed configs and a Compose override into a new directory."""
    if set(sources) != set(CONFIGS):
        raise ValueError("Portal, Grafana, and Super Admin config sources are all required.")
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("Output directory must be new; existing evidence is never overwritten.")
    output_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.mkdir(mode=0o700)
    os.chmod(output_dir, 0o700)

    digests: dict[str, str] = {}
    try:
        for key, (filename, _target) in CONFIGS.items():
            content = disable_http2(_read_source(sources[key], name=key), name=key)
            payload = content.encode("utf-8")
            destination = output_dir / filename
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            digests[filename] = hashlib.sha256(payload).hexdigest()

        override = output_dir / "compose.no-http2.yml"
        payload = _compose_overlay(output_dir).encode("utf-8")
        descriptor = os.open(override, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        digests[override.name] = hashlib.sha256(payload).hexdigest()
        image_override = output_dir / "compose.patched-image.yml"
        payload = _patched_image_overlay().encode("utf-8")
        descriptor = os.open(
            image_override, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        digests[image_override.name] = hashlib.sha256(payload).hexdigest()
        directory_fd = os.open(output_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        # Remove only this invocation's new files; never follow a symlink.
        for child in output_dir.iterdir():
            if child.is_file() and not child.is_symlink():
                child.unlink()
        output_dir.rmdir()
        raise
    return digests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portal-config", type=Path, required=True)
    parser.add_argument("--grafana-config", type=Path, required=True)
    parser.add_argument("--support-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--require-root", action="store_true")
    args = parser.parse_args(argv)
    if args.require_root and os.geteuid() != 0:
        parser.error("production mitigation preparation must run as root")
    try:
        digests = prepare_overlay(
            {
                "portal": args.portal_config,
                "grafana": args.grafana_config,
                "support": args.support_config,
            },
            args.output_dir,
        )
    except (OSError, ValueError) as exc:
        print(f"Refusing to prepare HTTP/2 mitigation: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output_dir": str(args.output_dir), "sha256": digests}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
