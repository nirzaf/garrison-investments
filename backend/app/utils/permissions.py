from typing import Final

from app.models.user import User
from app.utils.exceptions import AppException, PermissionDeniedException

ROLE_ADMIN: Final = "admin"
ROLE_GENERAL_MANAGER: Final = "general_manager"
ROLE_OPERATION_MANAGER: Final = "operation_manager"
ROLE_PROJECT_MANAGER: Final = "project_manager"
ROLE_CIVIL_ENGINEER: Final = "civil_engineer"
ROLE_CIVIL_SUPERVISOR: Final = "civil_supervisor"
ROLE_STORE_KEEPER: Final = "store_keeper"
ROLE_ACCOUNTS: Final = "accounts"

VALID_ROLES: Final[set[str]] = {
    ROLE_ADMIN,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
    ROLE_PROJECT_MANAGER,
    ROLE_CIVIL_ENGINEER,
    ROLE_CIVIL_SUPERVISOR,
    ROLE_STORE_KEEPER,
    ROLE_ACCOUNTS,
}

PERMISSION_USERS_MANAGE: Final = "users:manage"
PERMISSION_USERS_READ: Final = "users:read"
PERMISSION_PROJECTS_MANAGE: Final = "projects:manage"
PERMISSION_PROJECTS_READ: Final = "projects:read"
PERMISSION_AUDIT_VIEW: Final = "audit:view"
PERMISSION_DASHBOARD_COMPANY: Final = "dashboard:company"
PERMISSION_DASHBOARD_SCOPED: Final = "dashboard:scoped"
PERMISSION_REPORTS_VIEW: Final = "reports:view"
PERMISSION_REPORTS_SUBMIT: Final = "reports:submit"
PERMISSION_REPORTS_APPROVE: Final = "reports:approve"
PERMISSION_INVENTORY_VIEW: Final = "inventory:view"
PERMISSION_INVENTORY_MANAGE: Final = "inventory:manage"
PERMISSION_DOCUMENTS_MANAGE: Final = "documents:manage"
PERMISSION_FINANCIAL_VIEW: Final = "financial:view"

ALL_PERMISSIONS: Final[set[str]] = {
    PERMISSION_USERS_MANAGE,
    PERMISSION_USERS_READ,
    PERMISSION_PROJECTS_MANAGE,
    PERMISSION_PROJECTS_READ,
    PERMISSION_AUDIT_VIEW,
    PERMISSION_DASHBOARD_COMPANY,
    PERMISSION_DASHBOARD_SCOPED,
    PERMISSION_REPORTS_VIEW,
    PERMISSION_REPORTS_SUBMIT,
    PERMISSION_REPORTS_APPROVE,
    PERMISSION_INVENTORY_VIEW,
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_DOCUMENTS_MANAGE,
    PERMISSION_FINANCIAL_VIEW,
}

ROLE_PERMISSIONS: Final[dict[str, set[str]]] = {
    ROLE_ADMIN: ALL_PERMISSIONS,
    ROLE_GENERAL_MANAGER: {
        PERMISSION_USERS_READ,
        PERMISSION_PROJECTS_READ,
        PERMISSION_PROJECTS_MANAGE,
        PERMISSION_DASHBOARD_COMPANY,
        PERMISSION_REPORTS_VIEW,
        PERMISSION_REPORTS_APPROVE,
        PERMISSION_INVENTORY_VIEW,
        PERMISSION_DOCUMENTS_MANAGE,
        PERMISSION_FINANCIAL_VIEW,
    },
    ROLE_OPERATION_MANAGER: {
        PERMISSION_USERS_READ,
        PERMISSION_PROJECTS_READ,
        PERMISSION_PROJECTS_MANAGE,
        PERMISSION_DASHBOARD_COMPANY,
        PERMISSION_REPORTS_VIEW,
        PERMISSION_REPORTS_APPROVE,
        PERMISSION_INVENTORY_VIEW,
        PERMISSION_DOCUMENTS_MANAGE,
        PERMISSION_FINANCIAL_VIEW,
    },
    ROLE_PROJECT_MANAGER: {
        PERMISSION_DASHBOARD_SCOPED,
        PERMISSION_PROJECTS_READ,
        PERMISSION_REPORTS_VIEW,
        PERMISSION_REPORTS_APPROVE,
        PERMISSION_INVENTORY_VIEW,
        PERMISSION_DOCUMENTS_MANAGE,
        PERMISSION_FINANCIAL_VIEW,
    },
    ROLE_CIVIL_ENGINEER: {
        PERMISSION_DASHBOARD_SCOPED,
        PERMISSION_PROJECTS_READ,
        PERMISSION_REPORTS_VIEW,
        PERMISSION_REPORTS_SUBMIT,
        PERMISSION_INVENTORY_VIEW,
        PERMISSION_DOCUMENTS_MANAGE,
    },
    ROLE_CIVIL_SUPERVISOR: {
        PERMISSION_DASHBOARD_SCOPED,
        PERMISSION_PROJECTS_READ,
        PERMISSION_REPORTS_VIEW,
        PERMISSION_REPORTS_SUBMIT,
    },
    ROLE_STORE_KEEPER: {
        PERMISSION_DASHBOARD_SCOPED,
        PERMISSION_INVENTORY_VIEW,
        PERMISSION_INVENTORY_MANAGE,
    },
    ROLE_ACCOUNTS: {
        PERMISSION_DASHBOARD_SCOPED,
        PERMISSION_PROJECTS_READ,
        PERMISSION_REPORTS_VIEW,
        PERMISSION_DOCUMENTS_MANAGE,
        PERMISSION_FINANCIAL_VIEW,
    },
}


def has_permission(user: User, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(user.role, set())


def permissions_for_role(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, set()))


def ensure_permission(user: User, permission: str) -> None:
    if not has_permission(user, permission):
        raise PermissionDeniedException(permission)


def validate_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized not in VALID_ROLES:
        raise AppException(
            "Invalid role.",
            status_code=422,
            error_code="INVALID_ROLE",
        )
    return normalized
