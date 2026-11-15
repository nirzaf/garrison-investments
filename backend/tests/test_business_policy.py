from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.business_policy import MAX_MONEY, BusinessPolicy
from app.config import Settings
from app.models.user import User
from app.schemas.approvals import ApprovalCreateRequest
from app.services.approval_service import ApprovalService
from app.services.finance_service import FinanceService
from app.utils.exceptions import AppException


def test_business_policy_defaults_are_compatible() -> None:
    policy = BusinessPolicy()
    assert policy.model_dump(mode="json") == {
        "business_currency": "USD",
        "business_timezone": "Asia/Qatar",
        "material_approval_threshold": "1000.00",
    }


@pytest.mark.parametrize("value", ["0", "999999999999.99"])
def test_threshold_accepts_storage_bounds(value: str) -> None:
    assert BusinessPolicy.model_validate(
        {"material_approval_threshold": value}
    ).material_approval_threshold == Decimal(value)


@pytest.mark.parametrize(
    "data",
    [
        {"business_currency": "usd"},
        {"business_currency": "ZZZ"},
        {"business_timezone": "Invalid/Zone"},
        {"business_timezone": "localtime"},
        {"material_approval_threshold": "-0.01"},
        {"material_approval_threshold": "1.001"},
        {"material_approval_threshold": "1000000000000"},
        {"material_approval_threshold": "NaN"},
        {"material_approval_threshold": 0.1},
        {"material_approval_threshold": True},
    ],
)
def test_invalid_business_policy_is_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BusinessPolicy.model_validate(data)


@pytest.mark.parametrize("environment", ["production", "prod", "staging", " Production "])
def test_deployed_settings_require_currency_migration(
    environment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUSINESS_CURRENCY", "LKR")
    with pytest.raises(ValidationError, match="historical currency reconciliation"):
        Settings(app_env=environment)
    assert Settings(app_env="test").business_currency == "LKR"


@pytest.mark.parametrize(
    ("threshold", "amount", "actor_role", "expected"),
    [
        ("0", "0", "quantity_surveyor", "operations_director"),
        ("0", "0.01", "quantity_surveyor", "operations_director"),
        ("250.00", "249.99", "quantity_surveyor", "operations_director"),
        ("250.00", "250.00", "quantity_surveyor", "operations_director"),
        ("250.00", "250.01", "quantity_surveyor", "operations_director"),
        ("250.00", "50.00", "group_project_manager", "operations_director"),
        ("999999999999.99", "999999999999.99", "quantity_surveyor", "operations_director"),
    ],
)
async def test_material_routing_keeps_strict_boundary_and_project_manager_rule(
    threshold: str, amount: str, actor_role: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.approval_service.get_settings",
        lambda: SimpleNamespace(material_approval_threshold=Decimal(threshold)),
    )
    operations_director = User(id=uuid4(), role="operations_director")
    service = ApprovalService(Mock(scalar=AsyncMock(return_value=operations_director)))
    monkeypatch.setattr(
        service, "_first_active_role_user", AsyncMock(return_value=operations_director)
    )
    approval = ApprovalCreateRequest(
        request_type="material_request",
        request_id=uuid4(),
        project_id=uuid4(),
        title="Materials",
        amount=Decimal(amount),
    )
    approver = await service._resolve_approver(approval, User(id=uuid4(), role=actor_role))
    assert approver.role == expected


def test_invoice_total_preserves_explicit_tax_and_decimal_maximum() -> None:
    assert FinanceService._invoice_total(Decimal("100.25"), Decimal("4.75")) == Decimal("105.00")
    assert FinanceService._invoice_total(MAX_MONEY - Decimal("0.01"), Decimal("0.01")) == MAX_MONEY
    with pytest.raises(AppException, match="Invoice total exceeds"):
        FinanceService._invoice_total(MAX_MONEY, Decimal("0.01"))
