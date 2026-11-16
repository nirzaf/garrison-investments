import hashlib
from uuid import uuid4

import httpx
import pytest

from scripts.verify_hr_recovery import RecoveryPlan, RecoveryReadbackError, verify_hr_readback


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    ("fault", "error"),
    [
        ("", ""),
        ("wrong-key", "HR key readback failed with HTTP 503"),
        ("opened-private", "Private HR profile protection did not return a record denial"),
        ("different-bytes", "checksum differs"),
        ("other-origin", "outside the restore object origin"),
        ("missing-receipt", "policy edition or receipt differs"),
        ("same-account", "three distinct restored accounts"),
    ],
)
def test_recovery_readback(fault: str, error: str) -> None:
    identities = {token: str(uuid4()) for token in ("hr", "employee", "outsider")}
    if fault == "same-account":
        identities["outsider"] = identities["employee"]
    personnel_id, employee_id, application_id, correspondence_id = (uuid4() for _ in range(4))
    editions = [
        {
            "policy_id": uuid4(),
            "edition": str(version),
            "is_current": version == 2,
            "version": version,
            "sha256": _sha(f"policy-{version}".encode()),
        }
        for version in (1, 2)
    ]
    plan = RecoveryPlan.model_validate(
        {
            "employee_id": employee_id,
            "identifier_sha256": _sha(b"synthetic identifier"),
            "personnel_document_id": personnel_id,
            "personnel_versions": [
                {"version": v, "sha256": _sha(f"personnel-{v}".encode())} for v in (1, 2)
            ],
            "policies": editions,
            "application_id": application_id,
            "correspondence_id": correspondence_id,
            "correspondence_digest": _sha(b"synthetic correspondence"),
        }
    )
    downloads: list[str] = []
    object_origin = "http://127.0.0.1:9000"

    def link(kind: str, version: int) -> httpx.Response:
        origin = "http://127.0.0.1:9001" if fault == "other-origin" else object_origin
        return httpx.Response(
            200,
            json={
                "version_number": version,
                "download_url": f"{origin}/{kind}-{version}?signature=synthetic",
            },
        )

    def serve_api(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        token = request.headers["Authorization"].removeprefix("Bearer ")
        path = request.url.path.removeprefix("/api/v1")
        if path == "/auth/me":
            return httpx.Response(200, json={"id": identities[token]})
        if path == f"/hr/employees/{employee_id}/private":
            assert request.url.params["reveal_sensitive"] == "true"
            if token == "outsider" and fault != "opened-private":
                return httpx.Response(403)
            if fault == "wrong-key":
                return httpx.Response(503)
            return httpx.Response(200, json={"national_id_plain": "synthetic identifier"})
        if path == f"/hr/documents/{personnel_id}/download":
            if token == "outsider":
                return httpx.Response(404)
            assert token == "hr"
            return link("personnel", int(request.url.params["version_number"]))
        if path == "/hr/me/policies":
            assert token == "employee"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": str(policy.policy_id),
                            "version": policy.edition,
                            "is_current": policy.is_current,
                            "document_version_number": policy.version,
                            "acknowledged_at": None if fault == "missing-receipt" else "2026-01-01",
                        }
                        for policy in plan.policies
                    ]
                },
            )
        for policy in plan.policies:
            if path == f"/hr/me/policies/{policy.policy_id}/download":
                if token == "outsider":
                    assert not policy.is_current
                    return httpx.Response(404)
                assert token == "employee"
                return link("policy", policy.version)
        assert path == f"/hr/applications/{application_id}/correspondence/{correspondence_id}"
        if token == "outsider":
            return httpx.Response(403)
        assert token == "hr"
        return httpx.Response(
            200, json={"status": "approved", "digest": plan.correspondence_digest}
        )

    def serve_storage(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "Authorization" not in request.headers
        assert request.url.port == 9000
        key = request.url.path.lstrip("/")
        downloads.append(key)
        return httpx.Response(
            200, content=b"changed" if fault == "different-bytes" else key.encode()
        )

    with (
        httpx.Client(
            base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(serve_api)
        ) as api,
        httpx.Client(transport=httpx.MockTransport(serve_storage)) as storage,
    ):
        tokens = {"hr_token": "hr", "employee_token": "employee", "outsider_token": "outsider"}
        if error:
            with pytest.raises(RecoveryReadbackError, match=error):
                verify_hr_readback(api, storage, object_origin, plan, **tokens)
        else:
            assert verify_hr_readback(api, storage, object_origin, plan, **tokens) == {
                "identity_values_verified": 1,
                "personnel_file_versions_verified": 2,
                "policy_receipts_and_files_verified": 2,
                "approved_correspondence_verified": 1,
                "independent_accounts_verified": 3,
            }
            assert downloads == ["personnel-1", "personnel-2", "policy-1", "policy-2"]
    if fault == "other-origin":
        assert downloads == []
