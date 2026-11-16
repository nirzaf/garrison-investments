import hashlib
import io
import json
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


def test_cv_cli_reviews_exact_version_and_checks_download_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    maker, reviewer, candidate, document = (str(uuid4()) for _ in range(4))
    actor = maker
    content = b"%PDF-1.4\nSynthetic CV\n%%EOF"
    digest = hashlib.sha256(content).hexdigest()
    corrupt = False
    redirect = False
    hits: list[tuple[str | None, str | None]] = []

    class Storage(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append((self.headers.get("Authorization"), self.headers.get("Cookie")))
            if redirect:
                self.send_response(302)
                self.send_header("Location", "/do-not-follow")
                self.end_headers()
                return
            body = b"X" * len(content) if corrupt else content
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    storage = ThreadingHTTPServer(("127.0.0.1", 0), Storage)
    thread = threading.Thread(target=storage.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{storage.server_port}"
    root = "/api/v1/hr/documents"
    path = f"{root}/{document}"
    writes: list[str] = []
    versions: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        route = request.url.path
        if route == "/api/v1/auth/me":
            return httpx.Response(
                200,
                json={
                    "id": actor,
                    "permissions": ["hr:documents:manage", "hr:employees:sensitive"],
                },
            )
        record = {
            "id": document,
            "candidate_id": candidate,
            "category": "confidential",
            "document_type": "candidate_cv",
            "status": "active" if any(v["status"] == "active" for v in versions) else "pending",
            "current_version": next(
                (v["version_number"] for v in versions if v["status"] == "active"), 0
            ),
            "versions": versions,
        }
        if route == f"{path}/download":
            assert request.url.params["version_number"] == "1"
            return httpx.Response(
                200,
                json={
                    "document_id": document,
                    "version_number": 1,
                    "download_url": f"{origin}/cv?secret=synthetic",
                },
            )
        if request.method == "GET":
            if route == root:
                assert request.url.params["candidate_id"] == candidate
                return httpx.Response(200, json={"items": [record], "total": 1})
            assert route == path
            return httpx.Response(200, json=record)
        writes.append(route)
        if route.endswith("/decision"):
            assert actor == reviewer and json.loads(request.content) == {
                "decision": "approve",
                "notes": None,
            }
            versions[0]["status"] = "active"
        else:
            assert content in request.content
            if not versions:
                assert candidate.encode() in request.content
            else:
                assert b'expected_latest_version"' in request.content
            versions.insert(
                0,
                {
                    "id": str(uuid4()),
                    "version_number": len(versions) + 1,
                    "status": "pending",
                    "sha256_checksum": digest,
                    "file_size": len(content),
                    "uploaded_by_id": actor,
                    "file_name": "Private filename.pdf",
                },
            )
        return httpx.Response(200, json=record)

    def invoke(command: str, *args: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            ["hr", "documents", command, *args, "--json"],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert not stderr.getvalue()
        assert (
            "secret=synthetic" not in stdout.getvalue()
            and "Private filename" not in stdout.getvalue()
        )
        return code, json.loads(stdout.getvalue())

    def review(command: str, *args: str) -> list[str]:
        code, preview = invoke(command, *args, "--dry-run")
        assert code == 0
        return ["--apply", "--expect", preview["data"]["plan_sha256"]]

    try:
        file = tmp_path / "source.pdf"
        file.write_bytes(content)
        args = [
            "--file",
            str(file),
            "--candidate-id",
            candidate,
            "--category",
            "confidential",
            "--document-type",
            "candidate_cv",
            "--title",
            "CV",
        ]
        assert invoke("upload", *args, *review("upload", *args))[0] == 0
        assert invoke("list", "--candidate-id", candidate)[1]["data"]["total"] == 1
        version = ["--document-id", document, "--version", "1"]
        decision = [*version, "--sha256", digest, "--decision", "approve"]
        assert invoke("decide", *decision, "--dry-run")[0] == 3
        actor = reviewer
        output = tmp_path / "copy.pdf"
        download = [*version, "--output", str(output)]
        assert (
            invoke("download", *download, "--object-origin", "https://wrong.example.invalid")[0]
            != 0
        )
        assert hits == [] and not output.exists()
        corrupt = True
        assert invoke("download", *download, "--object-origin", origin)[0] == 4
        assert not output.exists()
        corrupt = False
        redirect = True
        assert invoke("download", *download, "--object-origin", origin)[0] != 0
        assert len(hits) == 2 and not output.exists()
        redirect = False
        assert (
            invoke("download", *download, "--object-origin", origin)[1]["data"]["sha256"] == digest
        )
        assert output.read_bytes() == content and stat.S_IMODE(output.stat().st_mode) == 0o600
        assert hits == [(None, None)] * 3
        assert invoke("decide", *decision, *review("decide", *decision))[0] == 0
        actor = maker
        replacement = ["--document-id", document, "--file", str(file)]
        assert (
            invoke("upload-version", *replacement, *review("upload-version", *replacement))[0] == 0
        )
        assert (
            invoke("status", "--document-id", document)[1]["data"]["versions"][0]["version_number"]
            == 2
        )
        assert writes == [root, f"{path}/versions/1/decision", f"{path}/versions"]
    finally:
        storage.shutdown()
        storage.server_close()
        thread.join()
