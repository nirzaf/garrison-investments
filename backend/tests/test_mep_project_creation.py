from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.user import User
from app.schemas.projects import BoqItemCreateRequest, ProjectCreateRequest
from app.services.project_service import ProjectService
from app.utils.exceptions import PermissionDeniedException
from app.utils.permissions import COMPANY_RESOURCE_ROLES


def payload(rate="0", budget=None):
    return ProjectCreateRequest(
        name="MEP project",
        scope_of_work="Mechanical works",
        target_end_date=date(2027, 1, 1),
        budget_amount=budget,
        boq_items=[
            BoqItemCreateRequest(
                item_code="B1",
                description="Pipe works",
                unit="lot",
                planned_quantity=Decimal("1"),
                unit_rate=Decimal(rate),
            )
        ],
    )


def service():
    result = ProjectService(AsyncMock())
    result.projects = AsyncMock()
    result.audit = AsyncMock()
    result._generate_project_code = AsyncMock(return_value="MEP-001")
    result._create_milestones = AsyncMock(return_value=[])
    result._create_boq_items = AsyncMock()
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", ["mep_project_manager", "operations_director", "managing_director"]
)
async def test_creation_without_automatic_membership(role):
    svc = service()
    actor = User(id=uuid4(), role=role)
    project = await svc.create_project(payload(), actor)
    assert project.created_by == actor.id
    svc.session.commit.assert_awaited_once()
    svc.projects.add_member.assert_not_awaited()
    svc.audit.record.assert_awaited_once()
    assert "mep_project_manager" not in COMPANY_RESOURCE_ROLES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rate,budget", [("12.34", Decimal("123.45")), ("0", Decimal("0")), ("10.01", None)]
)
async def test_mep_financial_creation_preserves_validated_amounts(rate, budget):
    svc = service()
    data = payload(rate, budget)
    project = await svc.create_project(data, User(id=uuid4(), role="mep_project_manager"))
    assert project.budget_amount == budget
    assert project.status == "planning"
    assert svc._create_boq_items.await_args.args[1][0].unit_rate == Decimal(rate)
    svc.projects.add_member.assert_not_awaited()
    svc.audit.record.assert_awaited_once()
    svc.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mep_can_create_planning_project_without_boq_but_cannot_add_priced_boq():
    svc = service()
    actor = User(id=uuid4(), role="mep_project_manager")
    data = payload().model_copy(update={"boq_items": []})

    project = await svc.create_project(data, actor)

    assert project.status == "planning"
    svc._create_boq_items.assert_not_awaited()
    svc.session.commit.assert_awaited_once()
    with pytest.raises(PermissionDeniedException):
        await svc.add_boq_item(
            uuid4(),
            BoqItemCreateRequest(
                item_code="B2",
                description="Priced work",
                unit="lot",
                planned_quantity=Decimal("1"),
                unit_rate=Decimal("2.00"),
            ),
            actor,
        )
    svc.projects.get_by_id.assert_not_awaited()


@pytest.mark.parametrize(
    "rate,budget", [("-1", None), ("1.001", None), ("1", Decimal("-1")), ("1", Decimal("1.001"))]
)
async def test_financial_input_validation_preserved(rate, budget):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        payload(rate, budget)


@pytest.mark.asyncio
async def test_group_manager_still_cannot_create():
    svc = service()
    with pytest.raises(PermissionDeniedException):
        await svc.create_project(payload(), User(id=uuid4(), role="group_project_manager"))
    svc.projects.add_project.assert_not_awaited()


@pytest.mark.asyncio
async def test_director_financial_creation_preserved():
    svc = service()
    await svc.create_project(
        payload("100", Decimal("100")), User(id=uuid4(), role="managing_director")
    )
    svc.session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["active", "on_hold", "completed", "cancelled"])
async def test_mep_cannot_create_nonplanning_project(status):
    svc = service()
    data = payload().model_copy(update={"status": status})
    with pytest.raises(PermissionDeniedException):
        await svc.create_project(data, User(id=uuid4(), role="mep_project_manager"))
    svc.projects.add_project.assert_not_awaited()


@pytest.mark.asyncio
async def test_unassigned_creator_cannot_read_project():
    svc = service()
    actor = User(id=uuid4(), role="mep_project_manager")
    project = await svc.create_project(payload(), actor)
    project.id = uuid4()
    svc.projects.get_by_id.return_value = project
    svc.projects.list_members.return_value = []
    from app.utils.exceptions import NotFoundException

    with pytest.raises(NotFoundException):
        await svc._get_authorized_project(project.id, actor)
