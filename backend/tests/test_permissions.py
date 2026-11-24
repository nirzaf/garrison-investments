import json
from pathlib import Path

import pytest

from app.main import app
from app.models.user import User
from app.utils.exceptions import AppException, PermissionDeniedException
from app.utils.permissions import (
    ALL_PERMISSIONS,
    BUSINESS_ROLES,
    HR_PERMISSIONS,
    PERMISSION_HR_CASES_RESTRICTED,
    PERMISSION_HR_EMPLOYEES_READ,
    PERMISSION_HR_EMPLOYEES_SENSITIVE,
    PERMISSION_HR_PAYROLL_APPROVE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    PERMISSION_HR_REQUESTS_PROCESS,
    PERMISSION_PLATFORM_ACCESS,
    PERMISSION_PLATFORM_OVERVIEW_READ,
    PERMISSION_USERS_READ,
    ROLE_HR_EXECUTIVE,
    ROLE_HR_MANAGER,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    ROLE_SUPER_ADMIN,
    TECHNICAL_PERMISSIONS,
    VALID_ROLES,
    ensure_permission,
    has_permission,
    permissions_for_role,
    validate_role,
)
from app.utils.portal_navigation import (
    NAVIGATION_POLICY,
    NAVIGATION_POLICY_PATH,
    navigation_visibility,
)

FIXTURE_PATH = Path(__file__).with_name("business_role_matrix.json")
FRONTEND_MATRIX_PATH = (
    Path(__file__).resolve().parents[2] / "frontend/src/pages/roles/rolePermissions.json"
)
MATRIX = json.loads(FIXTURE_PATH.read_text())


def test_portal_navigation_policies_match() -> None:
    frontend_policy = (
        FRONTEND_MATRIX_PATH.parents[2] / "components/layout/portalNavigation.json"
    )
    assert frontend_policy.read_bytes() == NAVIGATION_POLICY_PATH.read_bytes()
    for rule in NAVIGATION_POLICY.values():
        assert set(rule["any_permissions"]) <= ALL_PERMISSIONS | HR_PERMISSIONS
        assert set(rule["excluded_roles"]) <= BUSINESS_ROLES


@pytest.mark.parametrize("role", sorted(BUSINESS_ROLES))
def test_navigation_preserves_report_and_supervisor_links(role: str) -> None:
    permissions = set(permissions_for_role(role))
    visibility = navigation_visibility(role)
    assert visibility["reports"] is bool(permissions & {"reports:view", "reports:submit"})
    assert visibility["supervisor-updates"] is (
        role not in {"senior_site_supervisor", "site_supervisor"}
        and "reports:view" in permissions
    )


PERMISSIONS = MATRIX["permissions"]
EXPECTED_GRANTS = {
    role: {
        permission
        for permission, granted in zip(PERMISSIONS, metadata["decisions"], strict=True)
        if granted
    }
    for role, metadata in MATRIX["roles"].items()
}


HR_MANAGER_CORE_GRANTS = {
    "hr:employees:read",
    "hr:employees:manage",
    "hr:recruitment:manage",
    "hr:onboarding:manage",
    "hr:attendance:record",
    "hr:leave:manage",
    "hr:documents:manage",
    "hr:compliance:manage",
    "hr:requests:process",
    "hr:reports:view",
}
HR_MANAGER_GRANTS = HR_MANAGER_CORE_GRANTS | {
    "hr:employees:sensitive",
    "hr:attendance:approve",
    "hr:leave:approve",
    "hr:offboarding:manage",
    "hr:policy:manage",
    "hr:training:manage",
    "hr:performance:manage",
}
EFFECTIVE_GRANTS = {
    **{role: grants for role, grants in EXPECTED_GRANTS.items() if role != "hr_executive"},
    "hr_executive_reader": EXPECTED_GRANTS["hr_executive"] - {"reports:view"},
    "group_project_manager": EXPECTED_GRANTS["group_project_manager"] | {"financial:view"},
    "hr_manager": (
        EXPECTED_GRANTS["hr_manager"]
        - {"users:manage", "audit:view", "documents:view", "reports:view", "reports:approve"}
    )
    | HR_MANAGER_GRANTS,
}


def test_exact_role_and_permission_catalogues_match_independent_matrix() -> None:
    assert BUSINESS_ROLES == set(EFFECTIVE_GRANTS)
    assert set(VALID_ROLES) == BUSINESS_ROLES | {ROLE_SUPER_ADMIN}
    assert set(ROLE_PERMISSIONS) == set(ROLE_LABELS) == VALID_ROLES
    assert ALL_PERMISSIONS == set(PERMISSIONS)
    assert len(BUSINESS_ROLES) == 10
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
    assert {role: ROLE_PERMISSIONS[role] for role in BUSINESS_ROLES} == EFFECTIVE_GRANTS


def test_frontend_matrix_matches_source_and_backend() -> None:
    frontend = json.loads(FRONTEND_MATRIX_PATH.read_text())
    assert frontend["permissions"] == PERMISSIONS + sorted(HR_PERMISSIONS)
    assert set(frontend["roles"]) == BUSINESS_ROLES
    assert {role: set(grants) for role, grants in frontend["roles"].items()} == EFFECTIVE_GRANTS


@pytest.mark.parametrize("role", [*MATRIX["retired_roles"], "hr_executive"])
def test_retired_roles_are_rejected_and_have_no_permissions(role: str) -> None:
    assert permissions_for_role(role) == []
    assert not has_permission(User(role=role), "users:manage")
    with pytest.raises(AppException) as exc_info:
        validate_role(role)
    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "INVALID_ROLE"
    with pytest.raises(AppException):
        validate_role(f"  {role.upper()}  ")


@pytest.mark.parametrize("role", sorted(BUSINESS_ROLES))
def test_every_target_role_validates_and_has_exact_permissions(role: str) -> None:
    assert validate_role(role) == role
    assert set(permissions_for_role(role)) == EFFECTIVE_GRANTS[role]


def test_super_admin_has_only_registered_technical_permissions() -> None:
    assert validate_role(ROLE_SUPER_ADMIN) == ROLE_SUPER_ADMIN
    assert TECHNICAL_PERMISSIONS == {PERMISSION_PLATFORM_ACCESS, PERMISSION_PLATFORM_OVERVIEW_READ}
    assert set(permissions_for_role(ROLE_SUPER_ADMIN)) == TECHNICAL_PERMISSIONS
    operator = User(role=ROLE_SUPER_ADMIN)
    assert all(not has_permission(operator, key) for key in ALL_PERMISSIONS | HR_PERMISSIONS)
    assert all(
        not has_permission(User(role=role), PERMISSION_PLATFORM_ACCESS) for role in BUSINESS_ROLES
    )


def test_permission_helpers_fail_closed_for_unknown_role_and_future_permission() -> None:
    assert permissions_for_role("unknown") == []
    assert has_permission(User(role="unknown"), "users:manage") is False
    director = User(role="managing_director")
    assert has_permission(director, "future:permission") is False
    assert has_permission(director, "hr:employees:read") is False
    assert not has_permission(User(role="hr_executive"), "hr:employees:read")
    with pytest.raises(PermissionDeniedException) as exc_info:
        ensure_permission(director, "future:permission")
    assert exc_info.value.status_code == 403
    assert exc_info.value.error_code == "PERMISSION_DENIED"


def test_hr_routes_are_in_the_api_contract() -> None:
    paths = app.openapi()["paths"]
    assert {"/api/v1/hr/employees", "/api/v1/hr/me"} <= paths.keys()


def test_every_feature_permission_denial_is_explicit_for_each_role() -> None:
    for role, grants in EFFECTIVE_GRANTS.items():
        actor = User(role=role)
        for permission in ALL_PERMISSIONS | HR_PERMISSIONS:
            assert has_permission(actor, permission) is (permission in grants)


def test_production_roles_keep_policy_gated_payroll_and_hr_cases_disabled() -> None:
    gated = {
        "hr:payroll:prepare",
        "hr:payroll:approve",
        "hr:payroll:sensitive",
        "hr:cases:restricted",
    }
    for role in VALID_ROLES:
        assert gated.isdisjoint(ROLE_PERMISSIONS[role])
        assert navigation_visibility(role)["employee-relations"] is False


def test_exact_ten_person_roster_sensitive_hr_and_monetary_duty_coverage() -> None:
    roster = {
        "NANDANA": "managing_director",
        "SUDESH": "operations_director",
        "CHAMARA": "group_project_manager",
        "NISHSHANKA": "mep_project_manager",
        "MADEESHA": "quantity_surveyor",
        "DILSHAN": "senior_site_supervisor",
        "LAHIRU": "site_supervisor",
        "SAFIYA": ROLE_HR_MANAGER,
        "SHAMEERA": ROLE_HR_EXECUTIVE,
        "GAYANI": "administrative_executive",
    }
    assert len(roster) == 10
    assert set(roster.values()) == BUSINESS_ROLES

    sensitive_reviewers = {
        name
        for name, role in roster.items()
        if has_permission(User(role=role), PERMISSION_HR_EMPLOYEES_SENSITIVE)
    }
    assert sensitive_reviewers == {"SAFIYA"}
    assert {
        name
        for name, role in roster.items()
        if has_permission(User(role=role), PERMISSION_HR_REQUESTS_PROCESS)
    } == {"SAFIYA"}
    assert has_permission(User(role=roster["SHAMEERA"]), PERMISSION_USERS_READ)
    assert not has_permission(User(role=roster["SHAMEERA"]), PERMISSION_HR_EMPLOYEES_READ)
    assert not has_permission(User(role=roster["SHAMEERA"]), PERMISSION_HR_EMPLOYEES_SENSITIVE)
    assert not has_permission(User(role=roster["SHAMEERA"]), PERMISSION_HR_REQUESTS_PROCESS)

    # When SAFIYA proposes or is subject to a sensitive HR change requiring an independent
    # reviewer (reviewer != proposer and reviewer != subject), no second eligible reviewer exists.
    independent_for_safiya = {
        name for name in sensitive_reviewers if name != "SAFIYA"
    }
    assert independent_for_safiya == set()

    # Policy-gated payroll and restricted HR cases remain unassigned across the 10-person roster.
    for perm in (
        PERMISSION_HR_PAYROLL_SENSITIVE,
        PERMISSION_HR_PAYROLL_APPROVE,
        PERMISSION_HR_CASES_RESTRICTED,
    ):
        assert {
            name for name, role in roster.items() if has_permission(User(role=role), perm)
        } == set()
