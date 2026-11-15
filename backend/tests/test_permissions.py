import json
from pathlib import Path

import pytest

from app.main import app
from app.models.user import User
from app.utils.exceptions import AppException, PermissionDeniedException
from app.utils.permissions import (
    ALL_PERMISSIONS,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    VALID_ROLES,
    ensure_permission,
    has_permission,
    permissions_for_role,
    validate_role,
)

FIXTURE_PATH = Path(__file__).with_name("business_role_matrix.json")
FRONTEND_MATRIX_PATH = (
    Path(__file__).resolve().parents[2] / "frontend/src/pages/roles/rolePermissions.json"
)
MATRIX = json.loads(FIXTURE_PATH.read_text())
PERMISSIONS = MATRIX["permissions"]
EXPECTED_GRANTS = {
    role: {
        permission
        for permission, granted in zip(PERMISSIONS, metadata["decisions"], strict=True)
        if granted
    }
    for role, metadata in MATRIX["roles"].items()
}


def test_exact_role_and_permission_catalogues_match_independent_matrix() -> None:
    assert set(VALID_ROLES) == set(MATRIX["roles"])
    assert set(ROLE_PERMISSIONS) == set(MATRIX["roles"])
    assert set(ROLE_LABELS) == set(MATRIX["roles"])
    assert ALL_PERMISSIONS == set(PERMISSIONS)
    assert len(VALID_ROLES) == 10
    assert len(ALL_PERMISSIONS) == 16


def test_independent_matrix_retains_source_hashes_and_coordinates() -> None:
    source = MATRIX["source"]
    coordinates = source["worksheet_coordinates"]

    assert len(source["matrix_sha256"]) == 64
    assert len(source["guide_sha256"]) == 64
    assert source["review_status"] == "Pending review"
    assert coordinates["html_header_line"] == 2
    assert coordinates["role_labels_and_named_people"] == {"first_row": 4, "last_row": 5}
    assert coordinates["grant_and_denial_decisions"] == {"first_row": 6, "last_row": 21}
    assert coordinates["review_status_row"] == 22
    assert coordinates["guide_permissions_and_review_notes"] == [
        {"first_row": 5, "last_row": 20},
        {"first_row": 22, "last_row": 22},
    ]
    assert all(role["label"] and role["person"] for role in MATRIX["roles"].values())


def test_all_160_source_decisions_and_role_totals_match() -> None:
    assert sum(len(metadata["decisions"]) for metadata in MATRIX["roles"].values()) == 160
    assert sum(sum(metadata["decisions"]) for metadata in MATRIX["roles"].values()) == 87
    assert (
        sum(len(PERMISSIONS) - sum(metadata["decisions"]) for metadata in MATRIX["roles"].values())
        == 73
    )
    role_totals = [sum(metadata["decisions"]) for metadata in MATRIX["roles"].values()]
    assert role_totals == MATRIX["expected_role_grants"]
    assert ROLE_PERMISSIONS == EXPECTED_GRANTS
    assert sum(len(grants) for grants in ROLE_PERMISSIONS.values()) == MATRIX["expected_grants"]


def test_frontend_matrix_matches_source_and_backend() -> None:
    frontend = json.loads(FRONTEND_MATRIX_PATH.read_text())
    assert frontend["permissions"] == PERMISSIONS
    assert set(frontend["roles"]) == set(ROLE_PERMISSIONS)
    assert {role: set(grants) for role, grants in frontend["roles"].items()} == ROLE_PERMISSIONS


@pytest.mark.parametrize("role", MATRIX["retired_roles"])
def test_retired_roles_are_rejected_and_have_no_permissions(role: str) -> None:
    assert permissions_for_role(role) == []
    assert not has_permission(User(role=role), "users:manage")
    with pytest.raises(AppException) as exc_info:
        validate_role(role)
    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "INVALID_ROLE"
    with pytest.raises(AppException):
        validate_role(f"  {role.upper()}  ")


@pytest.mark.parametrize("role", sorted(VALID_ROLES))
def test_every_target_role_validates_and_has_exact_permissions(role: str) -> None:
    assert validate_role(role) == role
    assert set(permissions_for_role(role)) == EXPECTED_GRANTS[role]


def test_permission_helpers_fail_closed_for_unknown_role_and_future_permission() -> None:
    assert permissions_for_role("unknown") == []
    assert has_permission(User(role="unknown"), "users:manage") is False
    director = User(role="managing_director")
    assert has_permission(director, "future:permission") is False
    assert has_permission(director, "hr:employees:read") is False
    assert all("hr:employees:read" not in permissions for permissions in ROLE_PERMISSIONS.values())
    with pytest.raises(PermissionDeniedException) as exc_info:
        ensure_permission(director, "future:permission")
    assert exc_info.value.status_code == 403
    assert exc_info.value.error_code == "PERMISSION_DENIED"


def test_role_replacement_does_not_mount_an_unapproved_hr_module() -> None:
    paths = app.openapi()["paths"]
    assert not any(path.startswith("/api/v1/hr/") for path in paths)


def test_every_feature_permission_denial_is_explicit_for_each_role() -> None:
    for role, grants in EXPECTED_GRANTS.items():
        actor = User(role=role)
        for permission in PERMISSIONS:
            assert has_permission(actor, permission) is (permission in grants)
