"""Participant-scoped, append-only performance reviews."""

from uuid import UUID

from sqlalchemy import false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import HrEmployee, HrGoal, HrPerformanceEvent, HrReview, HrReviewCycle
from app.models.user import User
from app.schemas.hr import (
    GoalResponse,
    PerformanceAction,
    PerformanceEventResponse,
    PerformanceParticipant,
    PerformanceReviewActionRequest,
    PerformanceReviewDetail,
    PerformanceReviewItem,
    PerformanceReviewQueue,
)
from app.services.audit_service import AuditService
from app.services.hr_manager_review import REVIEW_EMPLOYMENT_STATES, eligible_reviewer
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import PERMISSION_HR_PERFORMANCE_MANAGE, has_permission


async def _participant(
    session: AsyncSession,
    review: HrReview,
    employee: HrEmployee,
    actor: User,
) -> PerformanceParticipant:
    if employee.user_id == actor.id:
        if employee.employment_status in REVIEW_EMPLOYMENT_STATES:
            return "employee"
        raise NotFoundException("Performance review")
    if (
        review.reviewer_employee_id == employee.manager_employee_id
        and review.reviewer_employee_id is not None
        and await eligible_reviewer(session, employee) == actor.id
    ):
        return "manager"
    if has_permission(actor, PERMISSION_HR_PERFORMANCE_MANAGE):
        return "hr"
    raise NotFoundException("Performance review")


RATED_ACTIONS = {"submit_self_review", "submit_manager_review", "calibrate"}


def _current_manager_events(events: list[HrPerformanceEvent]) -> list[HrPerformanceEvent]:
    handoff = max((e.revision for e in events if e.action == "reassign_manager"), default=0)
    return [e for e in events if e.participant == "manager" and e.revision > handoff]


async def _replacement(
    session: AsyncSession,
    review: HrReview,
    employee: HrEmployee,
    participant: PerformanceParticipant,
    actor: User,
) -> HrEmployee | None:
    candidate_id = employee.manager_employee_id
    if (
        participant != "hr"
        or review.status
        not in {"draft", "goals_acknowledged", "self_submitted", "manager_reviewed"}
        or candidate_id is None
        or candidate_id == review.reviewer_employee_id
        or await eligible_reviewer(session, employee, actor.id) is None
    ):
        return None
    return await session.get(HrEmployee, candidate_id)


async def _can_calibrate(
    session: AsyncSession,
    review: HrReview,
    employee: HrEmployee,
    participant: PerformanceParticipant,
) -> bool:
    return (
        participant == "hr"
        and review.status == "manager_reviewed"
        and review.reviewer_employee_id == employee.manager_employee_id
        and await eligible_reviewer(session, employee) is not None
    )


def _allowed(
    review: HrReview,
    participant: PerformanceParticipant,
    events: list[HrPerformanceEvent],
    actor_id: UUID,
    *,
    can_reassign: bool,
    can_calibrate: bool,
) -> list[PerformanceAction]:
    if can_reassign:
        # Resolve the reassignment before HR can publish an assessment from the old manager.
        return ["reassign_manager"]
    if review.status == "draft" and participant != "hr":
        relevant = _current_manager_events(events) if participant == "manager" else events
        if not any(
            e.action == "acknowledge_goals" and e.participant == participant for e in relevant
        ):
            return ["acknowledge_goals"]
    if review.status == "goals_acknowledged":
        if participant == "employee":
            return ["record_progress", "submit_self_review"]
        if participant == "manager":
            return ["record_progress"]
    if review.status == "self_submitted" and participant == "manager":
        return ["submit_manager_review"]
    if can_calibrate and not any(
        e.action == "submit_manager_review" and e.actor_id == actor_id for e in events
    ):
        return ["calibrate"]
    if review.status == "calibrated" and participant == "employee":
        return ["acknowledge_final"]
    if (
        review.status == "closed"
        and participant == "hr"
        and any(e.action == "acknowledge_final" for e in events)
    ):
        return ["add_addendum"]
    return []


async def _context(
    session: AsyncSession, review_id: UUID, actor: User, *, lock: bool
) -> tuple[HrReview, HrEmployee, HrReviewCycle, PerformanceParticipant, list[HrPerformanceEvent]]:
    employee_id = await session.scalar(select(HrReview.employee_id).where(HrReview.id == review_id))
    employee_query = select(HrEmployee).where(
        HrEmployee.id == employee_id, HrEmployee.deleted_at.is_(None)
    )
    if lock:
        employee_query = employee_query.with_for_update()
    employee = await session.scalar(employee_query)
    review_query = select(HrReview).where(HrReview.id == review_id)
    if lock:
        review_query = review_query.with_for_update()
    review = await session.scalar(review_query)
    if employee is None or review is None:
        raise NotFoundException("Performance review")
    participant = await _participant(session, review, employee, actor)
    cycle = await session.get(HrReviewCycle, review.cycle_id)
    if cycle is None:
        raise NotFoundException("Review cycle")
    events = list(
        await session.scalars(
            select(HrPerformanceEvent)
            .where(HrPerformanceEvent.review_id == review.id)
            .order_by(HrPerformanceEvent.revision)
        )
    )
    return review, employee, cycle, participant, events


async def list_performance_reviews(
    session: AsyncSession,
    actor: User,
    *,
    limit: int,
    offset: int,
) -> PerformanceReviewQueue:
    # Conditions apply before pagination. The role check below assigns the view for each row.
    manager_id = await session.scalar(
        select(HrEmployee.id).where(
            HrEmployee.user_id == actor.id,
            HrEmployee.deleted_at.is_(None),
            HrEmployee.employment_status.in_(REVIEW_EMPLOYMENT_STATES),
        )
    )
    current = HrEmployee.employment_status.in_(REVIEW_EMPLOYMENT_STATES)
    manager_filter = (
        false()
        if manager_id is None
        else (
            current
            & (HrReview.reviewer_employee_id == manager_id)
            & (HrEmployee.manager_employee_id == manager_id)
            & (HrEmployee.line_manager_reviewer_id == manager_id)
        )
    )
    hr = has_permission(actor, PERMISSION_HR_PERFORMANCE_MANAGE)
    scope = or_((HrEmployee.user_id == actor.id) & current, manager_filter)
    if hr:
        scope = or_(scope, HrEmployee.user_id.is_distinct_from(actor.id))
    query = (
        select(HrReview, HrEmployee, HrReviewCycle)
        .join(HrEmployee, HrEmployee.id == HrReview.employee_id)
        .join(HrReviewCycle, HrReviewCycle.id == HrReview.cycle_id)
        .where(HrEmployee.deleted_at.is_(None), scope)
    )
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(HrReview.created_at.desc(), HrReview.id.desc()).limit(limit).offset(offset)
    )
    return PerformanceReviewQueue(
        items=[
            PerformanceReviewItem(
                id=review.id,
                cycle_name=cycle.name,
                employee_name=employee.full_name,
                status=review.status,
                participant=await _participant(session, review, employee, actor),
            )
            for review, employee, cycle in rows
        ],
        total=total or 0,
    )


async def get_performance_review(
    session: AsyncSession,
    review_id: UUID,
    actor: User,
) -> PerformanceReviewDetail:
    review, employee, cycle, participant, events = await _context(
        session,
        review_id,
        actor,
        lock=False,
    )
    goals = await session.scalars(
        select(HrGoal)
        .where(
            HrGoal.employee_id == employee.id,
            HrGoal.cycle_name == cycle.code,
        )
        .order_by(HrGoal.created_at, HrGoal.id)
    )
    published = review.status in {"calibrated", "closed"}
    replacement = await _replacement(session, review, employee, participant, actor)
    current_manager_ids = {event.id for event in _current_manager_events(events)}
    return PerformanceReviewDetail(
        id=review.id,
        cycle_name=cycle.name,
        employee_name=employee.full_name,
        status=review.status,
        participant=participant,
        revision=len(events),
        allowed_actions=_allowed(
            review,
            participant,
            events,
            actor.id,
            can_reassign=replacement is not None,
            can_calibrate=await _can_calibrate(session, review, employee, participant),
        ),
        rating_scale=cycle.rating_scale,
        replacement_reviewer_id=replacement.id if replacement is not None else None,
        replacement_reviewer_name=replacement.full_name if replacement is not None else None,
        goals=[GoalResponse.model_validate(goal) for goal in goals],
        events=[
            PerformanceEventResponse.model_validate(event)
            for event in events
            if (
                event.action != "submit_manager_review"
                or participant == "hr"
                or (event.id in current_manager_ids and (participant == "manager" or published))
            )
        ],
    )


async def record_performance_action(
    session: AsyncSession,
    review_id: UUID,
    payload: PerformanceReviewActionRequest,
    actor: User,
) -> PerformanceReviewDetail:
    review, employee, cycle, participant, events = await _context(
        session, review_id, actor, lock=True
    )
    prior = await session.get(HrPerformanceEvent, payload.event_id)
    if prior is not None:
        if (
            prior.review_id,
            prior.actor_id,
            prior.action,
            prior.notes,
            prior.revision,
            prior.rating,
            prior.replacement_reviewer_id,
        ) == (
            review.id,
            actor.id,
            payload.action,
            payload.notes,
            payload.expected_revision + 1,
            payload.rating,
            payload.replacement_reviewer_id,
        ):
            return await get_performance_review(session, review.id, actor)
        raise AppException("The performance event ID is already in use.", status_code=409)
    if payload.expected_revision != len(events):
        raise AppException("Reload the performance review before acting.", status_code=409)
    replacement = await _replacement(session, review, employee, participant, actor)
    if payload.action not in _allowed(
        review,
        participant,
        events,
        actor.id,
        can_reassign=replacement is not None,
        can_calibrate=await _can_calibrate(session, review, employee, participant),
    ):
        raise PermissionDeniedException("perform this review action at its current stage")
    if payload.action in RATED_ACTIONS:
        if cycle.rating_scale and payload.rating not in cycle.rating_scale:
            raise AppException("Select a rating from the approved cycle scale.", status_code=422)
        if not cycle.rating_scale and payload.rating is not None:
            raise AppException("This cycle uses a narrative assessment.", status_code=422)

    transition = {
        "submit_self_review": "self_submitted",
        "submit_manager_review": "manager_reviewed",
        "calibrate": "calibrated",
        "acknowledge_final": "closed",
        "reassign_manager": "draft",
    }.get(payload.action)
    previous_reviewer_id = None
    if payload.action == "reassign_manager":
        if replacement is None or payload.replacement_reviewer_id != replacement.id:
            raise AppException("Reload and confirm the current eligible reviewer.", status_code=409)
        previous_reviewer_id = review.reviewer_employee_id
        review.reviewer_employee_id = replacement.id
    if payload.action == "acknowledge_goals":
        other_events = (
            _current_manager_events(events)
            if participant == "employee"
            else [e for e in events if e.participant == "employee"]
        )
        if any(e.action == "acknowledge_goals" for e in other_events):
            transition = (
                "self_submitted"
                if any(e.action == "submit_self_review" for e in events)
                else "goals_acknowledged"
            )
    if transition is not None:
        review.status = transition
    session.add(
        HrPerformanceEvent(
            id=payload.event_id,
            review_id=review.id,
            revision=len(events) + 1,
            action=payload.action,
            participant=participant,
            actor_id=actor.id,
            notes=payload.notes,
            rating=payload.rating,
            previous_reviewer_id=previous_reviewer_id,
            replacement_reviewer_id=payload.replacement_reviewer_id,
        )
    )
    try:
        await AuditService(session).record(
            action=f"hr.performance.{payload.action}",
            user_id=actor.id,
            entity_type="hr_reviews",
            entity_id=review.id,
            new_values={"revision": len(events) + 1},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AppException(
            "The performance event ID or revision already exists.", status_code=409
        ) from exc
    return await get_performance_review(session, review.id, actor)
