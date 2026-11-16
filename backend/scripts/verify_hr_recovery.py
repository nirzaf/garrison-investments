"""Verify protected HR records through an isolated, running restored application."""

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.hr_crypto import MAX_HR_DOCUMENT_SIZE
from scripts.garrisonctl_common import CLIError, read_private_bytes

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RecoveryReadbackError(Exception):
    """Readback diagnostics omit credentials, paths, and record values."""


class DocumentVersionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    sha256: Sha256


class PolicyCheck(DocumentVersionCheck):
    policy_id: UUID
    edition: str = Field(min_length=1, max_length=20)
    is_current: bool


class RecoveryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    identifier_sha256: Sha256
    personnel_document_id: UUID
    personnel_versions: list[DocumentVersionCheck] = Field(min_length=2, max_length=20)
    policies: list[PolicyCheck] = Field(min_length=2, max_length=20)
    application_id: UUID
    correspondence_id: UUID
    correspondence_digest: Sha256

    @model_validator(mode="after")
    def validate_coverage(self) -> "RecoveryPlan":
        if len({item.version for item in self.personnel_versions}) != len(self.personnel_versions):
            raise ValueError("Check distinct personnel document versions.")
        if (
            len({item.policy_id for item in self.policies}) != len(self.policies)
            or len({item.is_current for item in self.policies}) != 2
        ):
            raise ValueError("Check distinct current and previous policy editions.")
        return self


def _loopback_origin(url: str, *, origin_only: bool) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(url)
        default_port = 443 if parsed.scheme == "https" else 80
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or (origin_only and (parsed.path not in {"", "/"} or parsed.query))
        ):
            raise ValueError
        return parsed.scheme, parsed.hostname, parsed.port or default_port
    except ValueError as exc:
        raise RecoveryReadbackError(
            "Recovery readback requires explicit loopback origins."
        ) from exc


def _get(client: httpx.Client, path: str, token: str) -> httpx.Response:
    return client.get(f"/api/v1{path}", headers={"Authorization": f"Bearer {token}"})


def _json(response: httpx.Response, check: str) -> dict | list:
    if response.status_code != 200:
        raise RecoveryReadbackError(f"{check} failed with HTTP {response.status_code}.")
    value = response.json()
    if not isinstance(value, dict | list):
        raise RecoveryReadbackError(f"{check} returned an invalid response.")
    return value


def _denied(client: httpx.Client, path: str, token: str, check: str) -> None:
    if _get(client, path, token).status_code not in {403, 404}:
        raise RecoveryReadbackError(f"{check} did not return a record denial.")


def _file_check(
    api: httpx.Client,
    storage: httpx.Client,
    object_origin: tuple[str, str, int],
    token: str,
    route: str,
    expected: DocumentVersionCheck,
) -> None:
    record = _json(_get(api, route, token), "Protected document link")
    if not isinstance(record, dict) or record.get("version_number") != expected.version:
        raise RecoveryReadbackError("The protected download returned the wrong version.")
    url = record.get("download_url")
    if not isinstance(url, str) or _loopback_origin(url, origin_only=False) != object_origin:
        raise RecoveryReadbackError("The signed download points outside the restore object origin.")
    digest = hashlib.sha256()
    size = 0
    with storage.stream("GET", url) as response:
        if response.status_code != 200:
            raise RecoveryReadbackError("The restored object could not be downloaded.")
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_HR_DOCUMENT_SIZE:
                raise RecoveryReadbackError("The restored object exceeds the HR document limit.")
            digest.update(chunk)
    if not hmac.compare_digest(digest.hexdigest(), expected.sha256):
        raise RecoveryReadbackError("The restored object checksum differs from the recovery plan.")


def verify_hr_readback(
    api: httpx.Client,
    storage: httpx.Client,
    object_url: str,
    plan: RecoveryPlan,
    *,
    hr_token: str,
    employee_token: str,
    outsider_token: str,
) -> dict[str, int]:
    _loopback_origin(str(api.base_url), origin_only=True)
    objects = _loopback_origin(object_url, origin_only=True)
    identities = set()
    for token in (hr_token, employee_token, outsider_token):
        who = _json(_get(api, "/auth/me", token), "Actor identity")
        if not isinstance(who, dict):
            raise RecoveryReadbackError("Actor identity was unavailable.")
        identities.add(UUID(who["id"]))
    if len(identities) != 3:
        raise RecoveryReadbackError("Verify three distinct restored accounts.")

    profile_path = f"/hr/employees/{plan.employee_id}/private?reveal_sensitive=true"
    profile = _json(_get(api, profile_path, hr_token), "HR key readback")
    identifier = profile.get("national_id_plain") if isinstance(profile, dict) else None
    if not isinstance(identifier, str) or not hmac.compare_digest(
        hashlib.sha256(identifier.encode()).hexdigest(), plan.identifier_sha256
    ):
        raise RecoveryReadbackError(
            "The restored HR identity value differs from the recovery plan."
        )
    _denied(api, profile_path, outsider_token, "Private HR profile protection")

    for version in plan.personnel_versions:
        path = (
            f"/hr/documents/{plan.personnel_document_id}/download?version_number={version.version}"
        )
        _denied(api, path, outsider_token, "Personnel document protection")
        _file_check(api, storage, objects, hr_token, path, version)

    listing = _json(_get(api, "/hr/me/policies", employee_token), "Employee policy list")
    if not isinstance(listing, dict) or not isinstance(listing.get("items"), list):
        raise RecoveryReadbackError("The policy listing was unavailable.")
    by_id = {item["id"]: item for item in listing["items"]}
    for policy in plan.policies:
        item = by_id.get(str(policy.policy_id))
        if (
            not item
            or (item.get("version"), item.get("is_current"), item.get("document_version_number"))
            != (policy.edition, policy.is_current, policy.version)
            or not item.get("acknowledged_at")
        ):
            raise RecoveryReadbackError(
                "The restored policy edition or receipt differs from the plan."
            )
        download = f"/hr/me/policies/{policy.policy_id}/download"
        _file_check(api, storage, objects, employee_token, download, policy)
        if not policy.is_current:
            _denied(api, download, outsider_token, "Previous policy receipt protection")

    path = f"/hr/applications/{plan.application_id}/correspondence/{plan.correspondence_id}"
    record = _json(_get(api, path, hr_token), "Candidate correspondence readback")
    if (
        not isinstance(record, dict)
        or record.get("status") != "approved"
        or not hmac.compare_digest(str(record.get("digest", "")), plan.correspondence_digest)
    ):
        raise RecoveryReadbackError("The restored candidate correspondence differs from the plan.")
    _denied(api, path, outsider_token, "Candidate correspondence protection")
    return {
        "identity_values_verified": 1,
        "personnel_file_versions_verified": len(plan.personnel_versions),
        "policy_receipts_and_files_verified": len(plan.policies),
        "approved_correspondence_verified": 1,
        "independent_accounts_verified": len(identities),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="Restored application's loopback origin.")
    parser.add_argument("--objects", required=True, help="Restore storage's loopback origin.")
    parser.add_argument("--plan", required=True, type=Path, help="Private expected readback JSON.")
    args = parser.parse_args()
    try:
        plan = RecoveryPlan.model_validate_json(read_private_bytes(args.plan, max_bytes=64 * 1024))
        _loopback_origin(args.api, origin_only=True)
        with (
            httpx.Client(
                base_url=args.api, trust_env=False, follow_redirects=False, timeout=30
            ) as api,
            httpx.Client(trust_env=False, follow_redirects=False, timeout=30) as storage,
        ):
            checks = verify_hr_readback(
                api,
                storage,
                args.objects,
                plan,
                hr_token=os.environ["HR_RECOVERY_HR_TOKEN"],
                employee_token=os.environ["HR_RECOVERY_EMPLOYEE_TOKEN"],
                outsider_token=os.environ["HR_RECOVERY_OUTSIDER_TOKEN"],
            )
    except RecoveryReadbackError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except (CLIError, ValidationError, httpx.HTTPError, KeyError, TypeError, ValueError):
        print(
            "Recovery readback failed with invalid inputs or an unavailable response.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(json.dumps(checks, sort_keys=True))


if __name__ == "__main__":
    main()
