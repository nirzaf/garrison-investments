import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl


def test_performance_action_confirms_current_actor_intent_and_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", "synthetic-token")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    manager, employee, review_id, event_id = (str(uuid4()) for _ in range(4))
    path = f"/api/v1/hr/performance/reviews/{review_id}"
    private_note = "Synthetic confidential manager assessment"
    filename = tmp_path / "review.json"
    action = {"action": "submit_manager_review", "notes": private_note, "rating": "Meets goals"}
    filename.write_text(json.dumps(action))
    filename.chmod(0o600)
    actor = manager
    revision = 2
    events = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal revision
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": actor, "permissions": []})
        if request.method == "POST":
            assert request.url.path == f"{path}/actions" and actor == manager
            payload = json.loads(request.content)
            assert payload == {
                **action,
                "event_id": event_id,
                "expected_revision": revision,
                "replacement_reviewer_id": None,
            }
            revision += 1
            events.append({
                **action,
                "id": event_id,
                "actor_id": actor,
                "revision": revision,
                "occurred_at": "2026-11-17T00:00:00Z",
                "replacement_reviewer_id": None,
            })
            return httpx.Response(200, json={"id": review_id})
        assert request.method == "GET" and request.url.path == path
        return httpx.Response(200, json={
            "id": review_id,
            "revision": revision,
            "events": events if actor == manager else [],
            "allowed_actions": ["submit_manager_review"] if not events and actor == manager else [],
            "rating_scale": [action["rating"]],
        })

    def invoke(*options: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = garrisonctl.run(
            [
                "hr", "performance", "act", "--review-id", review_id, "--event-id", event_id,
                "--file", str(filename), *options, "--json",
            ],
            transport=httpx.MockTransport(handler),
            stdout=stdout,
            stderr=stderr,
        )
        assert private_note not in stdout.getvalue() + stderr.getvalue()
        assert action["rating"] not in stdout.getvalue() + stderr.getvalue()
        return code, json.loads(stdout.getvalue())

    filename.chmod(0o644)
    assert invoke("--dry-run")[0] != 0
    filename.chmod(0o600)
    code, preview = invoke("--dry-run")
    assert code == 0 and not events
    checksum = preview["data"]["plan_sha256"]
    actor = employee
    assert invoke("--apply", "--expect", checksum)[0] != 0
    actor = manager
    revision += 1
    assert invoke("--apply", "--expect", checksum)[0] == 4 and not events

    code, preview = invoke("--dry-run")
    assert code == 0
    checksum = preview["data"]["plan_sha256"]
    code, result = invoke("--apply", "--expect", checksum)
    assert code == 0 and result["changed"]
    assert result["data"] == {
        "review_id": review_id,
        "id": event_id,
        "revision": revision,
        "action": action["action"],
        "occurred_at": "2026-11-17T00:00:00Z",
    }

    code, replay = invoke("--apply", "--expect", checksum)
    assert code == 0 and not replay["changed"] and replay["data"] == result["data"]
    filename.write_text(json.dumps({**action, "notes": "A different assessment"}))
    assert invoke("--apply", "--expect", checksum)[0] == 4
    assert len(events) == 1
