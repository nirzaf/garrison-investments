import json
from pathlib import Path

import pytest

from app.models.user import User
from app.utils.exceptions import AppException, PermissionDeniedException
from app.utils.permissions import (
    ALL_PERMISSIONS,
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    ROLE_CIVIL_ENGINEER,
    ROLE_CIVIL_SUPERVISOR,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
    ROLE_PERMISSIONS,
    ROLE_PROJECT_MANAGER,
    ROLE_STORE_KEEPER,
    VALID_ROLES,
    ensure_permission,
    has_permission,
    permissions_for_role,
    validate_role,
)


def test_accounts_permissions_match_finance_scope() -> None:
    permissions = set(permissions_for_role("accounts"))

    assert {
        "dashboard:scoped",
        "projects:read",
        "reports:view",
        "documents:view",
        "documents:manage",
        "financial:view",
    }.issubset(permissions)
    assert "dashboard:company" not in permissions
    assert "inventory:view" not in permissions
    assert "inventory:manage" not in permissions
    assert "suppliers:manage" not in permissions


def test_permission_matrix_covers_every_valid_role() -> None:
    missing_roles = VALID_ROLES.difference(ROLE_PERMISSIONS)

    assert not missing_roles, f"Every valid role must have a permission entry: {missing_roles}"


def test_frontend_permission_matrix_matches_backend() -> None:
    fixture = Path(__file__).resolve().parents[2] / "frontend/src/pages/roles/rolePermissions.json"
    matrix = json.loads(fixture.read_text())
    assert len(matrix["permissions"]) == len(ALL_PERMISSIONS)
    assert set(matrix["permissions"]) == ALL_PERMISSIONS
    assert {role: set(grants) for role, grants in matrix["roles"].items()} == ROLE_PERMISSIONS


def test_permission_matrix_does_not_grant_unknown_permissions() -> None:
    unexpected_by_role = {
        role: sorted(permissions.difference(ALL_PERMISSIONS))
        for role, permissions in ROLE_PERMISSIONS.items()
        if permissions.difference(ALL_PERMISSIONS)
    }

    assert not unexpected_by_role, (
        "Role permission sets must only contain declared permissions; "
        f"unexpected values: {unexpected_by_role}"
    )


@pytest.mark.parametrize(
    ("role", "expected_permissions", "forbidden_permissions"),
    [
        (ROLE_ADMIN, ALL_PERMISSIONS, set()),
        (
            ROLE_GENERAL_MANAGER,
            {
                "dashboard:company",
                "documents:manage",
                "financial:view",
                "inventory:view",
                "projects:manage",
                "reports:approve",
                "suppliers:manage",
                "users:read",
            },
            {"audit:view", "inventory:manage", "users:manage"},
        ),
        (
            ROLE_OPERATION_MANAGER,
            {
                "dashboard:company",
                "documents:manage",
                "financial:view",
                "inventory:view",
                "projects:manage",
                "reports:approve",
                "suppliers:manage",
                "users:read",
            },
            {"audit:view", "inventory:manage", "users:manage"},
        ),
        (
            ROLE_PROJECT_MANAGER,
            {
                "dashboard:scoped",
                "documents:manage",
                "financial:view",
                "inventory:view",
                "projects:read",
                "reports:approve",
            },
            {"dashboard:company", "projects:manage", "suppliers:manage", "users:read"},
        ),
        (
            ROLE_CIVIL_ENGINEER,
            {
                "dashboard:scoped",
                "documents:manage",
                "inventory:view",
                "projects:read",
                "reports:submit",
                "reports:view",
            },
            {"financial:view", "reports:approve", "users:read"},
        ),
        (
            ROLE_CIVIL_SUPERVISOR,
            {"dashboard:scoped", "documents:view", "projects:read", "reports:submit"},
            {"documents:manage", "financial:view", "inventory:view", "reports:approve"},
        ),
        (
            ROLE_STORE_KEEPER,
            {"dashboard:scoped", "inventory:manage", "inventory:view", "suppliers:manage"},
            {"documents:view", "financial:view", "reports:view", "users:read"},
        ),
        (
            ROLE_ACCOUNTS,
            {"dashboard:scoped", "documents:manage", "financial:view", "projects:read"},
            {"dashboard:company", "inventory:view", "suppliers:manage", "users:read"},
        ),
    ],
)
def test_role_permission_boundaries(
    role: str,
    expected_permissions: set[str],
    forbidden_permissions: set[str],
) -> None:
    permissions = set(permissions_for_role(role))

    assert expected_permissions.issubset(permissions), (
        f"{role} is missing expected permissions: {sorted(expected_permissions - permissions)}"
    )
    assert forbidden_permissions.isdisjoint(permissions), (
        f"{role} unexpectedly grants restricted permissions: "
        f"{sorted(forbidden_permissions & permissions)}"
    )


def test_unknown_role_gets_no_permissions() -> None:
    assert permissions_for_role("unknown") == [], "Unknown roles must not inherit permissions"


def test_validate_role_normalizes_whitespace_and_case() -> None:
    assert validate_role("  PROJECT_MANAGER  ") == ROLE_PROJECT_MANAGER


def test_validate_role_rejects_unknown_role_with_actionable_error() -> None:
    with pytest.raises(AppException) as exc_info:
        validate_role("owner")

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "INVALID_ROLE"


def test_ensure_permission_raises_for_missing_permission() -> None:
    user = User(role=ROLE_CIVIL_SUPERVISOR)

    with pytest.raises(PermissionDeniedException) as exc_info:
        ensure_permission(user, "financial:view")

    assert exc_info.value.status_code == 403
    assert exc_info.value.error_code == "PERMISSION_DENIED"


def test_has_permission_returns_false_for_unknown_role() -> None:
    assert has_permission(User(role="unknown"), "users:manage") is False
