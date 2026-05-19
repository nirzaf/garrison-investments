from app.utils.permissions import permissions_for_role


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
