"""Apply explicit training requirements to current HR position and site assignments."""

from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import (
    HrCertification,
    HrEmployee,
    HrPosition,
    HrTrainingCompletion,
    HrTrainingCourse,
    HrTrainingEnrollment,
    HrTrainingRequirement,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.hr import (
    TrainingRequirementCreateRequest,
    TrainingRequirementListResponse,
    TrainingRequirementResponse,
    TrainingRequirementStatus,
    TrainingRequirementStatusListResponse,
)
from app.services.audit_service import AuditService
from app.utils.exceptions import NotFoundException
from app.utils.time import business_today


def _rules_query():
    return (
        select(HrTrainingRequirement, HrTrainingCourse.title, HrPosition.title, Project.name)
        .join(HrTrainingCourse, HrTrainingCourse.id == HrTrainingRequirement.course_id)
        .outerjoin(HrPosition, HrPosition.id == HrTrainingRequirement.position_id)
        .outerjoin(Project, Project.id == HrTrainingRequirement.project_id)
    )


async def list_rules(
    session: AsyncSession, *, limit: int, offset: int
) -> TrainingRequirementListResponse:
    rows = await session.execute(
        _rules_query()
        .order_by(HrTrainingRequirement.created_at.desc(), HrTrainingRequirement.id.desc())
        .limit(limit)
        .offset(offset)
    )
    total = await session.scalar(select(func.count()).select_from(HrTrainingRequirement))
    return TrainingRequirementListResponse(
        items=[
            TrainingRequirementResponse(
                id=rule.id,
                course_id=rule.course_id,
                position_id=rule.position_id,
                project_id=rule.project_id,
                is_active=rule.is_active,
                course_title=course,
                position_title=position,
                project_name=project,
            )
            for rule, course, position, project in rows
        ],
        total=total or 0,
    )


async def save_rule(
    session: AsyncSession,
    payload: TrainingRequirementCreateRequest,
    actor: User,
) -> UUID:
    if not await session.scalar(
        select(HrTrainingCourse.id).where(
            HrTrainingCourse.id == payload.course_id, HrTrainingCourse.is_active.is_(True)
        )
    ):
        raise NotFoundException("Active training course")
    if payload.position_id is not None and not await session.scalar(
        select(HrPosition.id).where(
            HrPosition.id == payload.position_id,
            HrPosition.is_active.is_(True),
            HrPosition.deleted_at.is_(None),
        )
    ):
        raise NotFoundException("Active HR position")
    if payload.project_id is not None and not await session.scalar(
        select(Project.id).where(
            Project.id == payload.project_id,
            Project.deleted_at.is_(None),
            Project.status.not_in(("completed", "cancelled")),
        )
    ):
        raise NotFoundException("Current project site")

    rule = await session.scalar(
        insert(HrTrainingRequirement)
        .values(**payload.model_dump())
        .on_conflict_do_update(
            index_elements=["course_id", "position_id", "project_id"],
            set_={"is_active": True, "updated_at": func.now()},
            where=HrTrainingRequirement.is_active.is_(False),
        )
        .returning(HrTrainingRequirement.id)
    )
    if rule is None:
        return (
            await session.scalars(
                select(HrTrainingRequirement.id).where(
                    HrTrainingRequirement.course_id == payload.course_id,
                    HrTrainingRequirement.position_id == payload.position_id,
                    HrTrainingRequirement.project_id == payload.project_id,
                )
            )
        ).one()
    await AuditService(session).record(
        action="hr.training_requirement.activated",
        user_id=actor.id,
        entity_type="hr_training_requirements",
        entity_id=rule,
    )
    await session.commit()
    return rule


async def deactivate_rule(session: AsyncSession, rule_id: UUID, actor: User) -> None:
    rule = await session.scalar(
        select(HrTrainingRequirement).where(HrTrainingRequirement.id == rule_id).with_for_update()
    )
    if rule is None:
        raise NotFoundException("Training requirement")
    if rule.is_active:
        rule.is_active = False
        await AuditService(session).record(
            action="hr.training_requirement.deactivated",
            user_id=actor.id,
            entity_type="hr_training_requirements",
            entity_id=rule.id,
        )
        await session.commit()


async def list_employee_requirements(
    session: AsyncSession,
    employee: HrEmployee,
    *,
    limit: int,
    offset: int,
) -> TrainingRequirementStatusListResponse:
    if employee.employment_status in {"draft", "resigned", "terminated", "archived"}:
        return TrainingRequirementStatusListResponse(items=[], total=0)
    matching = (
        select(HrTrainingCourse.id, HrTrainingCourse.title)
        .join(HrTrainingRequirement, HrTrainingRequirement.course_id == HrTrainingCourse.id)
        .outerjoin(HrPosition, HrPosition.id == HrTrainingRequirement.position_id)
        .outerjoin(Project, Project.id == HrTrainingRequirement.project_id)
        .where(
            HrTrainingCourse.is_active.is_(True),
            HrTrainingRequirement.is_active.is_(True),
            or_(
                HrTrainingRequirement.position_id.is_(None),
                (
                    (HrTrainingRequirement.position_id == employee.position_id)
                    & HrPosition.is_active.is_(True)
                    & HrPosition.deleted_at.is_(None)
                ),
            ),
            or_(
                HrTrainingRequirement.project_id.is_(None),
                (
                    (HrTrainingRequirement.project_id == employee.primary_project_id)
                    & Project.deleted_at.is_(None)
                    & Project.status.not_in(("completed", "cancelled"))
                ),
            ),
        )
        .distinct()
        .subquery()
    )
    total = await session.scalar(select(func.count()).select_from(matching))
    courses = (
        await session.execute(
            select(matching.c.id, matching.c.title)
            .order_by(matching.c.title, matching.c.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    today = business_today()
    history = await session.execute(
        select(
            HrTrainingEnrollment.course_id,
            HrTrainingEnrollment.status,
            HrCertification.status,
            HrCertification.expiry_date,
        )
        .outerjoin(
            HrTrainingCompletion, HrTrainingCompletion.enrollment_id == HrTrainingEnrollment.id
        )
        .outerjoin(HrCertification, HrCertification.id == HrTrainingCompletion.certificate_id)
        .where(
            HrTrainingEnrollment.employee_id == employee.id,
            HrTrainingEnrollment.course_id.in_([course.id for course in courses]),
        )
    )
    statuses: dict[UUID, set[str]] = {}
    for course_id, enrollment, certification, expiry in history:
        values = statuses.setdefault(course_id, set())
        if certification in {"valid", "expiring"} and (expiry is None or expiry >= today):
            values.add("met")
        elif certification == "expired" or (expiry is not None and expiry < today):
            values.add("expired")
        elif enrollment in {"enrolled", "in_progress"}:
            values.add("enrolled")

    items = []
    for course in courses:
        values = statuses.get(course.id, set())
        state: Literal["met", "enrolled", "expired", "required"] = (
            "met"
            if "met" in values
            else "enrolled"
            if "enrolled" in values
            else "expired"
            if "expired" in values
            else "required"
        )
        items.append(
            TrainingRequirementStatus(course_id=course.id, course_title=course.title, status=state)
        )
    return TrainingRequirementStatusListResponse(items=items, total=total or 0)
