from datetime import timedelta
from hmac import compare_digest
from secrets import token_bytes
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import generate_authentication_options, options_to_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import UserVerificationRequirement

from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.support_case_actions import (
    SupportCaseAction,
    SupportCaseActionEvent,
    SupportCaseActionProof,
    SupportCaseProject,
)
from app.models.support_cases import (
    SupportCase,
    SupportCaseEvent,
    SupportCaseMember,
    SupportCaseRequest,
    SupportOperatorGrant,
)
from app.models.support_directory import SupportCaseSubject
from app.models.support_identity import SupportOperator, SupportSession
from app.models.user import User
from app.schemas.support_case_actions import (
    MAX_CASE_PROJECTS,
    MEMBERSHIP_ACTIONS,
    PROJECT_ACTIONS,
    SOURCE_ACTIONS,
    SUBJECT_ACTIONS,
    CaseActionCreate,
    CaseActionRead,
)
from app.services.support_custody import _CUSTODY_LOCK, SupportCustody
from app.services.support_identity import (
    SUPPORT_HOST,
    SupportIdentity,
    _digest,
    support_session_deadline,
)
from app.services.support_request_logs import SUPPORT_REQUEST_ID
from app.utils.exceptions import AppException, NotFoundException
from app.utils.security import utc_now


def _scope_capability(kind: str) -> str:
    if kind in SUBJECT_ACTIONS:
        return "directory.read"
    if kind in PROJECT_ACTIONS:
        return "simulation.start"
    return "logs.runtime"


def _denied() -> AppException:
    return AppException(
        "This operator cannot perform the case action.",
        status_code=403,
        error_code="SUPPORT_CASE_ACTION_DENIED",
    )


def _conflict() -> AppException:
    return AppException(
        "The case action is unavailable or its revision changed.",
        status_code=409,
        error_code="SUPPORT_CASE_ACTION_STALE",
    )


class SupportCaseActions:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.identity = SupportIdentity(session)

    async def _actor(
        self, token: str | None, csrf: str | None
    ) -> tuple[SupportOperator, SupportSession]:
        # Share custody serialization so epoch and roster checks hold through commit.
        await self.session.execute(select(func.pg_advisory_xact_lock(_CUSTODY_LOCK)))
        operator, active = await self.identity.current(token)
        if not csrf or len(csrf) != 43 or not compare_digest(active.csrf_hash, _digest(csrf)):
            raise _denied()
        return operator, active

    async def _grant(self, actor_id: UUID, capability: str) -> bool:
        return await self.session.get(SupportOperatorGrant, (actor_id, capability)) is not None

    async def _case(self, case_id: UUID) -> SupportCase:
        case = await self.session.get(SupportCase, case_id, with_for_update=True)
        if case is None or case.owner_id is None:
            raise NotFoundException("Support case")
        return case

    def _audit(
        self, action: SupportCaseAction, actor: SupportOperator, event: str, request_id: str
    ) -> None:
        self.session.add(
            SupportCaseActionEvent(
                id=uuid4(),
                action_id=action.id,
                actor_id=actor.id,
                event=event,
                request_id=request_id,
                occurred_at=utc_now(),
            )
        )

    @staticmethod
    def _eligible_state(case: SupportCase, kind: str) -> bool:
        if kind in SUBJECT_ACTIONS or kind in PROJECT_ACTIONS:
            return case.status in {"open", "investigating"}
        if kind == "close":
            return case.status == "verified"
        if kind == "verify":
            return case.status == "mitigated"
        return case.status in {"open", "investigating", "mitigated"}

    async def propose(
        self,
        token: str | None,
        csrf: str | None,
        case_id: UUID,
        revision: int,
        payload: CaseActionCreate,
        request_id: str,
    ) -> CaseActionRead:
        actor, active = await self._actor(token, csrf)
        if not await self._grant(actor.id, "cases.manage"):
            raise _denied()
        if (payload.kind in SUBJECT_ACTIONS or payload.kind in PROJECT_ACTIONS) and not (
            await self._grant(actor.id, _scope_capability(payload.kind))
        ):
            raise _denied()
        case = await self._case(case_id)
        owner_membership = await self.session.get(SupportCaseMember, (case_id, actor.id))
        if case.owner_id != actor.id or owner_membership is None:
            raise NotFoundException("Support case")
        single_owner = await self.identity.is_single_owner(actor.id)
        if single_owner and payload.kind in MEMBERSHIP_ACTIONS:
            raise _denied()
        if payload.member_id == actor.id:
            raise _denied()
        if payload.member_id is not None:
            target = await self.session.get(SupportOperator, payload.member_id)
            if target is None:
                raise _conflict()
        if case.revision != revision or not self._eligible_state(case, payload.kind):
            raise _conflict()
        now = utc_now()
        recent = await self.session.scalar(
            select(func.count())
            .select_from(SupportCaseAction)
            .where(SupportCaseAction.case_id == case_id, SupportCaseAction.expires_at > now)
        )
        if recent is not None and recent >= 20:
            raise AppException(
                "Wait before opening another case action.",
                status_code=429,
                error_code="SUPPORT_CASE_ACTION_LIMIT",
            )
        action = SupportCaseAction(
            id=uuid4(),
            case_id=case.id,
            kind=payload.kind,
            authorization_mode="single_owner" if single_owner else "paired",
            requester_id=actor.id,
            requester_epoch=actor.grant_epoch,
            member_id=payload.member_id,
            source_event_id=payload.source_event_id,
            subject_user_id=payload.subject_user_id,
            project_id=payload.project_id,
            case_revision=revision,
            expires_at=now + timedelta(minutes=15),
        )
        self.session.add(action)
        await self.session.flush()
        self._audit(action, actor, "requested", request_id)
        result = CaseActionRead.model_validate(action)
        if support_session_deadline(active) <= utc_now():
            raise _denied()
        await self.session.commit()
        return result

    async def _review(
        self, case_id: UUID, action_id: UUID, actor: SupportOperator
    ) -> tuple[SupportCase, SupportCaseAction]:
        case = await self._case(case_id)
        action = await self.session.get(SupportCaseAction, action_id, with_for_update=True)
        if action is None or action.case_id != case.id:
            raise NotFoundException("Support case action")
        if action.authorization_mode == "single_owner":
            if actor.id != action.requester_id or not await self.identity.is_single_owner(actor.id):
                raise _denied()
        elif actor.id in {action.requester_id, action.member_id}:
            raise _denied()
        if action.kind in MEMBERSHIP_ACTIONS:
            if (
                await self.session.scalar(
                    SupportCustody.usable_custodians().where(SupportOperator.id == actor.id)
                )
                is None
            ):
                raise NotFoundException("Support case action")
        else:
            if (
                not await self._grant(actor.id, "cases.manage")
                or not await self._grant(actor.id, _scope_capability(action.kind))
                or await self.session.get(SupportCaseMember, (case.id, actor.id)) is None
            ):
                raise NotFoundException("Support case action")
            if action.kind == "verify":
                mitigator = await self.session.scalar(
                    select(SupportCaseEvent.operator_id)
                    .where(
                        SupportCaseEvent.case_id == case.id,
                        SupportCaseEvent.action == "transitioned",
                        SupportCaseEvent.status == "mitigated",
                    )
                    .order_by(SupportCaseEvent.revision.desc())
                    .limit(1)
                )
                if mitigator is None or (
                    mitigator == actor.id and action.authorization_mode == "paired"
                ):
                    raise _denied()
        requester = await self.session.get(SupportOperator, action.requester_id)
        if (
            requester is None
            or requester.status != "active"
            or requester.grant_epoch != action.requester_epoch
            or case.owner_id != requester.id
            or not await self._grant(requester.id, "cases.manage")
            or (
                action.kind in PROJECT_ACTIONS
                and not await self._grant(requester.id, "simulation.start")
            )
            or await self.session.get(SupportCaseMember, (case.id, requester.id)) is None
            or case.revision != action.case_revision
            or action.applied_at is not None
            or action.expires_at <= utc_now()
            or not self._eligible_state(case, action.kind)
        ):
            raise _conflict()
        return case, action

    async def _linked_evidence(
        self, case_id: UUID, event_id: UUID | None
    ) -> SupportCaseAction | None:
        return await self.session.scalar(
            select(SupportCaseAction).where(
                SupportCaseAction.case_id == case_id,
                SupportCaseAction.kind == "evidence_link",
                SupportCaseAction.source_event_id == event_id,
                SupportCaseAction.applied_at.is_not(None),
            )
        )

    async def _verification(self, case: SupportCase) -> SupportCaseAction | None:
        return await self.session.scalar(
            select(SupportCaseAction).where(
                SupportCaseAction.case_id == case.id,
                SupportCaseAction.kind == "verify",
                SupportCaseAction.case_revision == case.revision - 1,
                SupportCaseAction.applied_at.is_not(None),
                SupportCaseAction.source_request_id.is_not(None),
                SupportCaseAction.source_status.between(200, 299),
            )
        )

    async def options(
        self,
        token: str | None,
        csrf: str | None,
        case_id: UUID,
        action_id: UUID,
    ) -> tuple[UUID, str, CaseActionRead]:
        actor, active = await self._actor(token, csrf)
        case, action = await self._review(case_id, action_id, actor)
        now = utc_now()
        challenge = token_bytes(32)
        proof = SupportCaseActionProof(
            id=uuid4(),
            action_id=action.id,
            session_id=active.id,
            challenge=challenge,
            expires_at=min(
                now + timedelta(minutes=2), action.expires_at, support_session_deadline(active)
            ),
        )
        if proof.expires_at <= now:
            raise _conflict()
        self.session.add(proof)
        options = generate_authentication_options(
            rp_id=SUPPORT_HOST,
            challenge=challenge,
            timeout=120_000,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        receipt = CaseActionRead.model_validate(action)
        if action.kind in {"verify", "close"}:
            source = await (
                self._linked_evidence(case.id, action.source_event_id)
                if action.kind == "verify"
                else self._verification(case)
            )
            if source is None:
                raise _conflict()
            receipt = receipt.model_copy(
                update={
                    "source_event_id": source.source_event_id,
                    "source_request_id": source.source_request_id,
                    "source_status": source.source_status,
                }
            )
        if action.kind == "subject_remove":
            subject = await self.session.get(SupportCaseSubject, case.id)
            if subject is None:
                raise _conflict()
            receipt = receipt.model_copy(update={"subject_user_id": subject.user_id})
        await self.session.commit()
        return proof.id, options_to_json(options), receipt

    async def _membership(self, case: SupportCase, action: SupportCaseAction) -> None:
        if action.member_id is None or action.member_id == case.owner_id:
            raise _conflict()
        existing = await self.session.get(SupportCaseMember, (case.id, action.member_id))
        if action.kind == "member_remove" and existing is not None:
            await self.session.delete(existing)
            return
        operator = await self.session.get(SupportOperator, action.member_id)
        if (
            action.kind != "member_add"
            or existing is not None
            or operator is None
            or operator.status != "active"
            or not await self._grant(operator.id, "cases.manage")
        ):
            raise _conflict()
        self.session.add(SupportCaseMember(case_id=case.id, operator_id=operator.id))

    async def _evidence(self, case: SupportCase, action: SupportCaseAction) -> None:
        row = (
            await self.session.execute(
                select(
                    ActivityLog.request_id,
                    ActivityLog.status_code,
                    ActivityLog.action,
                    ActivityLog.created_at,
                ).where(
                    ActivityLog.id == action.source_event_id,
                    ActivityLog.entity_type == "request",
                    ActivityLog.action.in_(
                        ("http.request", "http.app_exception", "http.unhandled_exception")
                    ),
                    ActivityLog.deleted_at.is_(None),
                    ActivityLog.created_at >= case.created_at - timedelta(hours=24),
                    ActivityLog.created_at <= utc_now(),
                )
            )
        ).one_or_none()
        if (
            row is None
            or row.request_id is None
            or not SUPPORT_REQUEST_ID.fullmatch(row.request_id)
        ):
            raise _conflict()
        existing = await self.session.get(SupportCaseRequest, (case.id, row.request_id))
        if action.kind == "evidence_link":
            if existing is not None:
                raise _conflict()
            self.session.add(SupportCaseRequest(case_id=case.id, request_id=row.request_id))
        else:
            linked = await self._linked_evidence(case.id, action.source_event_id)
            mitigated_at = await self.session.scalar(
                select(func.max(SupportCaseEvent.occurred_at)).where(
                    SupportCaseEvent.case_id == case.id,
                    SupportCaseEvent.action == "transitioned",
                    SupportCaseEvent.status == "mitigated",
                )
            )
            if (
                existing is None
                or linked is None
                or row.action != "http.request"
                or mitigated_at is None
                or row.created_at < mitigated_at
                or row.request_id != linked.source_request_id
                or row.status_code != linked.source_status
                or row.status_code is None
                or not 200 <= row.status_code < 300
            ):
                raise _conflict()
            case.status = "verified"
        action.source_request_id = row.request_id
        action.source_status = (
            row.status_code
            if (row.status_code is not None and 100 <= row.status_code <= 599)
            else None
        )

    async def _subject(self, case: SupportCase, action: SupportCaseAction) -> None:
        current = await self.session.get(SupportCaseSubject, case.id, with_for_update=True)
        if action.kind == "subject_remove":
            if current is None:
                raise _conflict()
            # Preserve the previous subject in the applied history.
            await self.session.delete(current)
            return
        user_id = await self.session.scalar(
            select(User.id).where(User.id == action.subject_user_id)
        )
        if user_id is None or (current is not None and current.user_id == user_id):
            raise _conflict()
        if current is None:
            self.session.add(SupportCaseSubject(case_id=case.id, user_id=user_id))
        else:
            current.user_id = user_id

    async def _project_scope(self, case: SupportCase, action: SupportCaseAction) -> None:
        project_id = action.project_id
        if project_id is None:
            raise _conflict()
        current = await self.session.get(SupportCaseProject, (case.id, project_id))
        if action.kind == "project_remove":
            if current is None:
                raise _conflict()
            await self.session.delete(current)
            return
        project = await self.session.scalar(
            select(Project.id)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
            .with_for_update(read=True)
        )
        count = await self.session.scalar(
            select(func.count())
            .select_from(SupportCaseProject)
            .where(SupportCaseProject.case_id == case.id)
        )
        if current is not None or project is None or (count or 0) >= MAX_CASE_PROJECTS:
            raise _conflict()
        self.session.add(SupportCaseProject(case_id=case.id, project_id=project_id))

    async def _close(self, case: SupportCase) -> None:
        verified = await self._verification(case)
        if verified is None:
            raise _conflict()
        case.status = "closed"

    async def apply(
        self,
        token: str | None,
        csrf: str | None,
        case_id: UUID,
        action_id: UUID,
        challenge_id: UUID,
        credential: dict[str, object],
        request_id: str,
    ) -> CaseActionRead:
        actor, active = await self._actor(token, csrf)
        case, action = await self._review(case_id, action_id, actor)
        proof = await self.session.get(SupportCaseActionProof, challenge_id, with_for_update=True)
        now = utc_now()
        if (
            proof is None
            or proof.action_id != action.id
            or proof.session_id != active.id
            or proof.consumed_at is not None
            or proof.expires_at <= now
        ):
            raise _conflict()
        proof.consumed_at = now
        try:
            await self.identity.verify_assertion(actor.id, proof.challenge, credential)
        except (WebAuthnException, AppException, ValueError) as exc:
            self._audit(action, actor, "proof_denied", request_id)
            await self.session.commit()
            raise _denied() from exc
        if action.kind in MEMBERSHIP_ACTIONS:
            await self._membership(case, action)
        elif action.kind in SOURCE_ACTIONS:
            await self._evidence(case, action)
        elif action.kind in SUBJECT_ACTIONS:
            await self._subject(case, action)
        elif action.kind in PROJECT_ACTIONS:
            await self._project_scope(case, action)
        else:
            await self._close(case)
        now = utc_now()
        if min(support_session_deadline(active), proof.expires_at, action.expires_at) <= now:
            raise _conflict()
        case.revision += 1
        case.updated_at = now
        action.applied_at = now
        if action.authorization_mode == "paired":
            action.reviewer_id = actor.id
        self._audit(action, actor, "applied", request_id)
        receipt = CaseActionRead.model_validate(action)
        await self.session.commit()
        return receipt
