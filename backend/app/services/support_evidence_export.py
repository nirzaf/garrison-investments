import asyncio
import csv
from datetime import UTC, timedelta
from hashlib import sha256
from hmac import compare_digest
from io import StringIO
from secrets import token_bytes
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers.exceptions import WebAuthnException

from app.models.support_cases import SupportCaseMember, SupportOperatorGrant
from app.models.support_evidence_export import SupportEvidenceExport, SupportEvidenceProof
from app.models.support_identity import SupportOperator, SupportSession
from app.schemas.support_evidence_export import (
    MAX_EXPORT_BYTES,
    ExportReason,
    ExportStage,
    SupportEvidenceExportCreate,
    SupportEvidenceExportRead,
    SupportEvidenceFilters,
)
from app.services.support_case_logs import require_case_request_log_scope
from app.services.support_custody import _CUSTODY_LOCK
from app.services.support_identity import SupportIdentity, _digest, support_session_deadline
from app.services.support_request_logs import SupportRequestLogPage, project_request_logs
from app.utils.exceptions import AppException, NotFoundException
from app.utils.security import utc_now

_EXPORT_GRANT = "logs.export"


def _denied() -> AppException:
    return AppException(
        "The evidence export could not be authorized.",
        status_code=403,
        error_code="SUPPORT_EXPORT_DENIED",
    )


def _stale() -> AppException:
    return AppException(
        "The evidence export is stale or unavailable. Request a new review.",
        status_code=409,
        error_code="SUPPORT_EXPORT_STALE",
    )


def _row_limit() -> AppException:
    return AppException(
        "Wait before creating another evidence export or proof.",
        status_code=429,
        error_code="SUPPORT_EXPORT_LIMIT",
    )


def export_csv(
    case_id: UUID,
    filters: SupportEvidenceFilters,
    reason: ExportReason,
    page: SupportRequestLogPage,
) -> bytes:
    # All variable cells come from UUIDs, bounded integers, UTC timestamps or fixed enums.
    # The source's raw endpoints, messages and arbitrary strings never enter this writer.
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "record_type",
            "case_id",
            "request_id",
            "started_at_utc",
            "ended_at_utc",
            "reason",
            "status_filter",
            "row_limit",
            "row_count",
            "truncated",
            "event_id",
            "occurred_at_utc",
            "event_kind",
            "method",
            "status_code",
        ]
    )
    writer.writerow(
        [
            "manifest",
            str(case_id),
            filters.request_id,
            filters.started_at.astimezone(UTC).isoformat(),
            filters.ended_at.astimezone(UTC).isoformat(),
            reason,
            filters.status_code,
            filters.limit,
            len(page.events),
            str(page.truncated).lower(),
            "",
            "",
            "",
            "",
            "",
        ]
    )
    for event in page.events:
        writer.writerow(
            [
                "event",
                str(case_id),
                filters.request_id,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                str(event.id),
                event.occurred_at.astimezone(UTC).isoformat(),
                event.kind,
                event.method,
                event.status_code,
            ]
        )
    content = output.getvalue().encode("utf-8")
    if len(content) > MAX_EXPORT_BYTES:
        raise AppException("The evidence export exceeds its size limit.", status_code=413)
    return content


class SupportEvidenceExports:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.identity = SupportIdentity(session)

    async def _actor(
        self, token: str | None, csrf: str | None
    ) -> tuple[SupportOperator, SupportSession]:
        # Serialize with case-scope and custody changes in the established lock order.
        await self.session.execute(select(func.pg_advisory_xact_lock(_CUSTODY_LOCK)))
        actor, active = await self.identity.current(token)
        if not csrf or len(csrf) != 43 or not compare_digest(active.csrf_hash, _digest(csrf)):
            raise _denied()
        return actor, active

    async def _scope(self, operator_id: UUID, case_id: UUID, request_id: str) -> None:
        await require_case_request_log_scope(
            self.session, operator_id, case_id, request_id, additional_grant=_EXPORT_GRANT
        )

    async def _still_eligible(self, actor_id: UUID, case_id: UUID, epoch: int) -> bool:
        actor = await self.session.get(SupportOperator, actor_id)
        if actor is None or actor.status != "active" or actor.grant_epoch != epoch:
            return False
        for capability in ("logs.runtime", _EXPORT_GRANT):
            if await self.session.get(SupportOperatorGrant, (actor.id, capability)) is None:
                return False
        return await self.session.get(SupportCaseMember, (case_id, actor.id)) is not None

    @staticmethod
    def _receipt(record: SupportEvidenceExport) -> SupportEvidenceExportRead:
        return SupportEvidenceExportRead.model_validate(
            {
                "id": record.id,
                "case_id": record.case_id,
                "filters": {
                    "request_id": record.source_request_id,
                    "started_at": record.started_at,
                    "ended_at": record.ended_at,
                    "limit": record.row_limit,
                    "status_code": record.filter_status_code,
                },
                "reason": record.reason,
                "row_count": record.row_count,
                "truncated": record.truncated,
                "sha256": record.sha256,
                "expires_at": record.expires_at,
                "approved_at": record.approved_at,
                "downloaded_at": record.downloaded_at,
            }
        )

    async def _project(self, filters: SupportEvidenceFilters) -> SupportRequestLogPage:
        try:
            async with asyncio.timeout(3):
                return await project_request_logs(self.session, filters)
        except TimeoutError:
            raise AppException(
                "Evidence export is temporarily unavailable.",
                status_code=503,
                error_code="SUPPORT_EXPORT_TIMEOUT",
            ) from None

    async def propose(
        self,
        token: str | None,
        csrf: str | None,
        case_id: UUID,
        payload: SupportEvidenceExportCreate,
        request_id: str,
    ) -> SupportEvidenceExportRead:
        actor, active = await self._actor(token, csrf)
        filters = payload.filters
        await self._scope(actor.id, case_id, filters.request_id)
        now = utc_now()
        if filters.ended_at > now:
            raise AppException("The export window cannot end in the future.", status_code=422)
        count = await self.session.scalar(
            select(func.count())
            .select_from(SupportEvidenceExport)
            .where(
                SupportEvidenceExport.requester_id == actor.id,
                SupportEvidenceExport.expires_at > now,
            )
        )
        if count is not None and count >= 10:
            raise _row_limit()
        page = await self._project(filters)
        content = export_csv(case_id, filters, payload.reason, page)
        expires_at = min(now + timedelta(minutes=15), support_session_deadline(active))
        if expires_at <= utc_now():
            raise _stale()
        record = SupportEvidenceExport(
            id=uuid4(),
            case_id=case_id,
            requester_id=actor.id,
            requester_session_id=active.id,
            reason=payload.reason,
            source_request_id=filters.request_id,
            started_at=filters.started_at.astimezone(UTC),
            ended_at=filters.ended_at.astimezone(UTC),
            row_limit=filters.limit,
            filter_status_code=filters.status_code,
            row_count=len(page.events),
            truncated=page.truncated,
            sha256=sha256(content).hexdigest(),
            created_at=now,
            expires_at=expires_at,
            request_id=request_id,
        )
        self.session.add(record)
        receipt = self._receipt(record)
        await self.session.commit()
        return receipt

    async def _eligible(
        self,
        actor: SupportOperator,
        active: SupportSession,
        case_id: UUID,
        export_id: UUID,
        stage: ExportStage,
    ) -> SupportEvidenceExport:
        record = await self.session.get(SupportEvidenceExport, export_id, with_for_update=True)
        if record is None or record.case_id != case_id:
            raise NotFoundException("Support evidence export")
        await self._scope(actor.id, case_id, record.source_request_id)
        if (stage == "review" and actor.id == record.requester_id) or (
            stage == "download" and active.id != record.requester_session_id
        ):
            raise _denied()
        if record.expires_at <= utc_now() or record.downloaded_at is not None:
            raise _stale()
        requester = await self.session.get(SupportSession, record.requester_session_id)
        if (
            requester is None
            or requester.revoked_at is not None
            or requester.operator_id != record.requester_id
            or support_session_deadline(requester) <= utc_now()
            or not await self._still_eligible(requester.operator_id, case_id, requester.grant_epoch)
        ):
            raise _stale()
        if stage == "review":
            if record.approved_at is not None:
                raise _stale()
        elif (
            record.reviewer_id is None
            or record.reviewer_epoch is None
            or not await self._still_eligible(record.reviewer_id, case_id, record.reviewer_epoch)
        ):
            raise _stale()
        return record

    async def options(
        self,
        token: str | None,
        csrf: str | None,
        case_id: UUID,
        export_id: UUID,
        stage: ExportStage,
    ) -> tuple[UUID, str, SupportEvidenceExportRead]:
        actor, active = await self._actor(token, csrf)
        record = await self._eligible(actor, active, case_id, export_id, stage)
        now = utc_now()
        count = await self.session.scalar(
            select(func.count())
            .select_from(SupportEvidenceProof)
            .where(
                SupportEvidenceProof.action_id == export_id,
                SupportEvidenceProof.stage == stage,
            )
        )
        if count is not None and count >= 10:
            raise _row_limit()
        proof = SupportEvidenceProof(
            id=uuid4(),
            action_id=export_id,
            session_id=active.id,
            stage=stage,
            challenge=token_bytes(32),
            expires_at=min(
                now + timedelta(minutes=2), record.expires_at, support_session_deadline(active)
            ),
        )
        if proof.expires_at <= now:
            raise _stale()
        self.session.add(proof)
        receipt = self._receipt(record)
        await self.session.commit()
        return proof.id, self.identity._public_key_options(proof.challenge), receipt

    async def decide(
        self,
        token: str | None,
        csrf: str | None,
        case_id: UUID,
        export_id: UUID,
        stage: ExportStage,
        expected_sha256: str,
        challenge_id: UUID,
        credential: dict[str, object],
        request_id: str,
    ) -> tuple[SupportEvidenceExportRead, bytes]:
        actor, active = await self._actor(token, csrf)
        record = await self._eligible(actor, active, case_id, export_id, stage)
        proof = await self.session.get(SupportEvidenceProof, challenge_id, with_for_update=True)
        now = utc_now()
        if (
            proof is None
            or proof.action_id != record.id
            or proof.stage != stage
            or proof.session_id != active.id
            or proof.consumed_at is not None
            or proof.expires_at <= now
            or not compare_digest(record.sha256, expected_sha256)
        ):
            raise _stale()
        proof.consumed_at = now
        try:
            await self.identity.verify_assertion(actor.id, proof.challenge, credential)
        except (WebAuthnException, AppException, ValueError):
            await self.session.commit()
            raise _denied() from None
        receipt = self._receipt(record)
        page = await self._project(receipt.filters)
        content = export_csv(case_id, receipt.filters, receipt.reason, page)
        now = utc_now()
        if min(
            support_session_deadline(active), record.expires_at, proof.expires_at
        ) <= now or not compare_digest(record.sha256, sha256(content).hexdigest()):
            raise _stale()
        if stage == "review":
            record.approved_at, record.reviewer_id = now, actor.id
            record.reviewer_epoch, record.review_request_id = actor.grant_epoch, request_id
        else:
            record.downloaded_at, record.download_request_id = now, request_id
        receipt = self._receipt(record)
        await self.session.commit()
        return receipt, content
