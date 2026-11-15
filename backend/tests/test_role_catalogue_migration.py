"""Focused safety tests for the offline role-catalogue cutover command."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.models.user import User
from app.utils.permissions import ROLE_MANAGING_DIRECTOR
from scripts.migrate_role_catalogue import (
    MigrationInputError,
    parse_manifest,
    validate_current_catalogue,
    validate_snapshot,
)


def manifest_data(*, target_role: str = ROLE_MANAGING_DIRECTOR) -> dict:
    return {
        "format_version": 1,
        "operator_reference": "change-123",
        "authorization_reference": "approval-456",
        "maintenance_window_reference": "window-789",
        "users": [
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "expected_role": "admin",
                "expected_updated_at": "2026-11-14T10:00:00Z",
                "expected_access_revision": 4,
                "expected_is_active": True,
                "expected_deleted_at": None,
                "target_role": target_role,
                "identity_evidence_reference": "identity-evidence-12",
                "decision_reference": "decision-34",
            }
        ],
    }


def as_manifest(data: dict | None = None):
    return parse_manifest(json.dumps(data or manifest_data()).encode())


def test_manifest_parses_reviewed_uuid_mapping_and_hashes_exact_bytes() -> None:
    raw = json.dumps(manifest_data(), separators=(",", ":")).encode()
    parsed = parse_manifest(raw)

    assert parsed.digest
    assert len(parsed.digest) == 64
    assert parsed.mappings[0].expected_role == "admin"
    assert parsed.mappings[0].target_role == ROLE_MANAGING_DIRECTOR
    assert parsed.mappings[0].expected_updated_at == datetime(2026, 11, 14, 10, tzinfo=UTC)


def test_manifest_rejects_duplicate_json_fields_and_user_ids() -> None:
    with pytest.raises(MigrationInputError, match="duplicate JSON field"):
        parse_manifest(b'{"format_version":1,"format_version":1}')

    duplicated = manifest_data()
    duplicated["users"].append(dict(duplicated["users"][0]))
    with pytest.raises(MigrationInputError, match="duplicate user UUIDs"):
        as_manifest(duplicated)


def test_manifest_rejects_retired_targets_unzoned_timestamps_and_missing_evidence() -> None:
    retired_target = manifest_data(target_role="admin")
    with pytest.raises(MigrationInputError, match="not a supported target role"):
        as_manifest(retired_target)

    no_timezone = manifest_data()
    no_timezone["users"][0]["expected_updated_at"] = "2026-11-14T10:00:00"
    with pytest.raises(MigrationInputError, match="must include a timezone"):
        as_manifest(no_timezone)

    no_reference = manifest_data()
    no_reference["users"][0]["identity_evidence_reference"] = None
    with pytest.raises(MigrationInputError, match="identity_evidence_reference"):
        as_manifest(no_reference)


def test_snapshot_requires_complete_coverage_and_exact_preconditions() -> None:
    manifest = as_manifest()
    account = User(
        id=manifest.mappings[0].user_id,
        email="hidden@example.invalid",
        full_name="Synthetic account",
        role="admin",
        updated_at=datetime(2026, 11, 14, 10, tzinfo=UTC),
        access_revision=4,
        is_active=True,
        deleted_at=None,
        password_hash="synthetic-hash",
        locked_until=None,
    )

    assert validate_snapshot([account], manifest)["role_changes"] == 1
    with pytest.raises(MigrationInputError, match="coverage differs"):
        validate_snapshot([], manifest)

    account.access_revision += 1
    with pytest.raises(MigrationInputError, match="preconditions"):
        validate_snapshot([account], manifest)


def test_snapshot_requires_a_usable_director_after_mapping() -> None:
    manifest = as_manifest(manifest_data(target_role="site_supervisor"))
    account = User(
        id=manifest.mappings[0].user_id,
        email="hidden@example.invalid",
        full_name="Synthetic account",
        role="admin",
        updated_at=datetime(2026, 11, 14, 10, tzinfo=UTC),
        access_revision=4,
        is_active=True,
        deleted_at=None,
        password_hash="synthetic-hash",
        locked_until=datetime.now(UTC) + timedelta(days=1),
    )

    with pytest.raises(MigrationInputError, match="no usable MD or OD"):
        validate_snapshot([account], manifest)


def test_current_catalogue_gate_rejects_legacy_roles_and_requires_a_usable_director() -> None:
    manifest = as_manifest()
    account = User(
        id=manifest.mappings[0].user_id,
        email="hidden@example.invalid",
        full_name="Synthetic account",
        role=ROLE_MANAGING_DIRECTOR,
        updated_at=datetime(2026, 11, 14, 10, tzinfo=UTC),
        access_revision=5,
        is_active=True,
        deleted_at=None,
        password_hash="synthetic-hash",
        locked_until=None,
    )
    assert validate_current_catalogue([account]) == {
        "account_count": 1,
        "unsupported_role_count": 0,
        "usable_directors": 1,
        "outcome": "current_catalogue_valid",
    }

    account.role = "admin"
    with pytest.raises(MigrationInputError, match="unsupported stored role"):
        validate_current_catalogue([account])
    account.role = "hr_manager"
    account.locked_until = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(MigrationInputError, match="no usable MD or OD"):
        validate_current_catalogue([account])
