import json
from datetime import datetime
from functools import partial
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, StrictBool, StringConstraints
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.api.streaming import ManagedEventStream
from app.config import get_settings
from app.models.support_cases import SupportOperatorGrant
from app.schemas.feedback import (
    FeedbackInboxItem,
    FeedbackInboxPage,
    FeedbackStatus,
    FeedbackStatusChange,
)
from app.schemas.support_business_actions import (
    ActionDigest,
    BusinessActionCreate,
    BusinessActionRead,
    BusinessActionStage,
    SupportRecoveryStatus,
)
from app.schemas.support_case_actions import CaseActionCreate, CaseActionRead
from app.schemas.support_cases import (
    SupportCaseCreate,
    SupportCasePage,
    SupportCaseRead,
    SupportCaseTransition,
)
from app.schemas.support_company_admin import (
    SupportAdminCommandPlanRequest,
    SupportAdminCommandRead,
    SupportCompanyContextRead,
    SupportCompanyUserAccessRead,
    SupportCompanyUserPage,
    SupportCompanyUserProfileRead,
    SupportDataInspectorCatalogRead,
    SupportDataInspectorPage,
    SupportDiagnoseCaseRead,
    SupportDiagnoseCaseRequest,
    SupportOwnerSecurityRead,
    SupportSafeSettingsRead,
    SupportUserActivityPage,
    SupportUserSessionInventoryRead,
)
from app.schemas.support_evidence_export import (
    SupportEvidenceExportCreate,
    SupportEvidenceExportRead,
)
from app.schemas.support_oversight import (
    SupportApprovalsOverviewRead,
    SupportBackupsMonitorRead,
    SupportCompanyOverviewRead,
    SupportConfigStatusRead,
    SupportDocumentsOverviewRead,
    SupportFinanceOverviewRead,
    SupportIncidentsQuery,
    SupportIncidentsSummaryRead,
    SupportInventoryOverviewRead,
    SupportJobsMonitorRead,
    SupportJobsQuery,
    SupportPolicyExplainQuery,
    SupportPolicyExplainRead,
    SupportProjectsOverviewRead,
    SupportSuppliersOverviewRead,
    SupportWorkforceOverviewRead,
)
from app.services.feedback_service import FeedbackService
from app.services.support_account_directory import (
    diagnose_or_link_user_case,
    list_company_users,
    query_data_inspector_entity,
    read_company_user_access,
    read_company_user_activity,
    read_company_user_profile,
    read_company_user_sessions,
    read_data_inspector_catalog,
)
from app.services.support_admin_commands import SupportAdminCommands
from app.services.support_admin_policy import (
    read_company_context,
    read_owner_security,
    read_safe_settings,
)
from app.services.support_business_actions import SupportBusinessActions
from app.services.support_case_actions import SupportCaseActions
from app.services.support_case_audit import SupportAuditPage, SupportAuditQuery, read_case_audit
from app.services.support_case_logs import read_case_request_logs
from app.services.support_cases import SupportCases
from app.services.support_cli_proof import SupportCliProofs
from app.services.support_custody import GrantCapability, RegistrationKind, Stage, SupportCustody
from app.services.support_directory import (
    SupportAccountRead,
    SupportAccountSelector,
    read_support_account,
)
from app.services.support_evidence_export import SupportEvidenceExports
from app.services.support_health import SupportHealthRead, read_support_health
from app.services.support_identity import (
    SUPPORT_HOST,
    SUPPORT_ORIGIN,
    SUPPORT_SESSION_SECONDS,
    AuthenticatedSupport,
    PendingSupportOtp,
    SupportIdentity,
)
from app.services.support_log_stream import (
    case_log_events,
    close_case_log_stream,
    open_case_log_stream,
)
from app.services.support_monitors import (
    read_backups_monitor,
    read_config_status,
    read_incidents_summary,
    read_jobs_monitor,
)
from app.services.support_overview import (
    explain_role_policy,
    read_approvals_overview,
    read_company_overview,
    read_documents_overview,
    read_finance_overview,
    read_inventory_overview,
    read_projects_overview,
    read_suppliers_overview,
    read_workforce_overview,
)
from app.services.support_permission_views import (
    PortalPreviewPage,
    SupportNavigationProjection,
    SupportPermissionExplanation,
    SupportPermissionViews,
    SupportPortalPreview,
    SupportProjectDetail,
    SupportProjectList,
    SupportRequestSummary,
)
from app.services.support_registration import RegistrationState, SupportRegistrationService
from app.services.support_request_logs import (
    SupportRequestLogPage,
    SupportRequestLogQuery,
    SupportRequestLogStreamQuery,
)
from app.services.support_timeline import SupportTimelineRead, read_case_timeline
from app.utils.exceptions import AppException, NotFoundException
from app.utils.request import is_trusted_proxy
from app.utils.security import utc_now

SESSION_COOKIE = "__Host-garrison-support"
CSRF_COOKIE = "__Host-garrison-support-csrf"
Base64Value = Annotated[
    str, StringConstraints(min_length=1, max_length=4096, pattern=r"^[A-Za-z0-9_-]+$")
]


class _StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SupportLoginRequest(_StrictPayload):
    operator_id: UUID


class SupportAssertionResponse(_StrictPayload):
    authenticatorData: Base64Value
    clientDataJSON: Base64Value
    signature: Base64Value
    userHandle: Base64Value


class SupportAssertion(_StrictPayload):
    id: Base64Value
    rawId: Base64Value
    type: Literal["public-key"]
    response: SupportAssertionResponse


class SupportVerifyRequest(_StrictPayload):
    challenge_id: UUID
    credential: SupportAssertion


CliCommitment = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
CliCode = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{12}$")]


class SupportCliStart(SupportLoginRequest):
    token_hash: CliCommitment
    csrf_hash: CliCommitment
    code_hash: CliCommitment


class SupportCliHandoff(_StrictPayload):
    challenge_id: UUID


class SupportCliOptionsRequest(SupportCliHandoff):
    pairing_code: CliCode


class SupportCliVerifyRequest(SupportVerifyRequest):
    pairing_code: CliCode


CliEncryptionKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{350,512}$")]
SealedProof = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,32768}$")]


class SupportCliProofStart(_StrictPayload):
    proof_id: UUID
    pairing_hash: CliCommitment
    encryption_key: CliEncryptionKey


class SupportCliProofReference(_StrictPayload):
    reference: UUID


class SupportCliProofPair(SupportCliProofReference):
    pairing_code: CliCode


class SupportCliProofSubmit(SupportCliProofPair):
    sealed: SealedProof


class SupportCliProofEnvelope(_StrictPayload):
    sealed: SealedProof


class SupportPublicKeyOptions(_StrictPayload):
    challenge: Base64Value
    rpId: str
    timeout: int
    userVerification: Literal["required"]
    allowCredentials: list[object] = []


class SupportLoginOptions(BaseModel):
    challenge_id: UUID
    public_key: SupportPublicKeyOptions


class SupportCliProofOptions(SupportLoginOptions):
    encryption_key: CliEncryptionKey
    operation: str
    stage: str
    action_id: UUID


class SupportEvidenceProofOptions(SupportLoginOptions):
    export: SupportEvidenceExportRead


class SupportEvidenceDecision(SupportVerifyRequest):
    expected_sha256: ActionDigest


class SupportSessionRead(BaseModel):
    operator_id: UUID
    expires_at: datetime


class SupportOtpRequired(BaseModel):
    otp_reference: UUID


class SupportOtpVerification(_StrictPayload):
    otp_reference: UUID
    otp: Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")]
    pairing_code: CliCode | None = None


class SupportProfile(SupportSessionRead):
    capabilities: list[str]


def require_support_ingress(request: Request) -> None:
    settings = get_settings()
    if not settings.support_portal_enabled or request.headers.get("host") != SUPPORT_HOST:
        raise NotFoundException("Support portal")
    if settings.app_env != "test":
        peer = settings.support_ingress_peer
        if (
            settings.app_env != "production"
            or peer is None
            or not request.client
            or not is_trusted_proxy(request.client.host, [str(peer)])
        ):
            raise NotFoundException("Support portal")
    origin = request.headers.get("origin")
    if (request.method != "GET" or origin is not None) and origin != SUPPORT_ORIGIN:
        raise AppException(
            "Support request origin is not allowed.",
            status_code=403,
            error_code="SUPPORT_ORIGIN_DENIED",
        )


router = APIRouter(
    prefix="/support", tags=["Support"], dependencies=[Depends(require_support_ingress)]
)


class SupportAuthModeRead(BaseModel):
    otp_only_login: bool


@router.get("/auth/mode", response_model=SupportAuthModeRead)
async def login_mode() -> SupportAuthModeRead:
    return SupportAuthModeRead(otp_only_login=get_settings().support_email_otp_only_login)


@router.post("/auth/request-otp", response_model=SupportOtpRequired)
async def request_login_otp(
    payload: SupportLoginRequest, request: Request, session: DbSession
) -> SupportOtpRequired:
    pending = await SupportIdentity(session).request_email_otp(
        payload.operator_id, request.state.request_id
    )
    return SupportOtpRequired(otp_reference=pending.reference)


@router.post("/auth/options", response_model=SupportLoginOptions)
async def login_options(payload: SupportLoginRequest, session: DbSession) -> SupportLoginOptions:
    challenge_id, options = await SupportIdentity(session).options(payload.operator_id)
    return SupportLoginOptions(
        challenge_id=challenge_id,
        public_key=SupportPublicKeyOptions.model_validate(json.loads(options)),
    )


@router.post("/auth/verify", response_model=SupportSessionRead | SupportOtpRequired)
async def verify_login(
    payload: SupportVerifyRequest,
    request: Request,
    response: Response,
    session: DbSession,
) -> SupportSessionRead | SupportOtpRequired:
    result = await SupportIdentity(session).verify(
        payload.challenge_id, payload.credential.model_dump(), request.state.request_id
    )
    if isinstance(result, PendingSupportOtp):
        return SupportOtpRequired(otp_reference=result.reference)
    return _set_browser_session(result, response)


def _set_browser_session(result: AuthenticatedSupport, response: Response) -> SupportSessionRead:
    operator, active, token, csrf = result
    assert token is not None and csrf is not None
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SUPPORT_SESSION_SECONDS,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=SUPPORT_SESSION_SECONDS,
        secure=True,
        samesite="strict",
    )
    return SupportSessionRead(operator_id=operator.id, expires_at=active.expires_at)


@router.post(
    "/auth/verify-otp",
    response_model=SupportSessionRead,
    responses={204: {"description": "CLI session confirmed"}},
)
async def verify_login_otp(
    payload: SupportOtpVerification, request: Request, response: Response, session: DbSession
) -> SupportSessionRead | Response:
    result = await SupportIdentity(session).verify_otp(
        payload.otp_reference, payload.otp, request.state.request_id, cli_code=payload.pairing_code
    )
    if payload.pairing_code is not None:
        return Response(status_code=204)
    return _set_browser_session(result, response)


@router.post("/auth/cli/start", response_model=SupportCliHandoff)
async def start_cli_login(payload: SupportCliStart, session: DbSession) -> SupportCliHandoff:
    challenge_id, _ = await SupportIdentity(session).options(
        payload.operator_id, cli_binding=(payload.token_hash, payload.csrf_hash, payload.code_hash)
    )
    return SupportCliHandoff(challenge_id=challenge_id)


@router.post("/auth/cli/options", response_model=SupportLoginOptions)
async def cli_login_options(
    payload: SupportCliOptionsRequest, session: DbSession
) -> SupportLoginOptions:
    options = await SupportIdentity(session).cli_options(payload.challenge_id, payload.pairing_code)
    return SupportLoginOptions(
        challenge_id=payload.challenge_id,
        public_key=SupportPublicKeyOptions.model_validate(json.loads(options)),
    )


@router.post(
    "/auth/cli/verify",
    status_code=204,
    response_class=Response,
    responses={202: {"model": SupportOtpRequired, "description": "Email verification required"}},
)
async def verify_cli_login(
    payload: SupportCliVerifyRequest, request: Request, session: DbSession
) -> Response:
    result = await SupportIdentity(session).verify(
        payload.challenge_id, payload.credential.model_dump(), request.state.request_id,
        cli_code=payload.pairing_code,
    )
    if isinstance(result, PendingSupportOtp):
        pending = SupportOtpRequired(otp_reference=result.reference)
        return JSONResponse(status_code=202, content=pending.model_dump(mode="json"))
    return Response(status_code=204)


@router.post("/auth/cli-proof/start", response_model=SupportCliProofReference)
async def start_cli_proof(
    payload: SupportCliProofStart, request: Request, session: DbSession
) -> SupportCliProofReference:
    reference = await SupportCliProofs(session).start(
        request.cookies.get(SESSION_COOKIE), request.headers.get("x-support-csrf"),
        payload.proof_id, payload.pairing_hash, payload.encryption_key,
    )
    return SupportCliProofReference(reference=reference)


@router.post("/auth/cli-proof/options", response_model=SupportCliProofOptions)
async def cli_proof_options(
    payload: SupportCliProofPair, session: DbSession
) -> SupportCliProofOptions:
    handoff, options, display = await SupportCliProofs(session).options(
        payload.reference, payload.pairing_code
    )
    return SupportCliProofOptions(
        challenge_id=handoff.proof_id,
        public_key=SupportPublicKeyOptions.model_validate(json.loads(options)),
        encryption_key=handoff.public_key,
        operation=display.operation, stage=display.stage, action_id=display.action_id,
    )


@router.post("/auth/cli-proof/submit", status_code=204, response_class=Response)
async def submit_cli_proof(payload: SupportCliProofSubmit, session: DbSession) -> Response:
    await SupportCliProofs(session).submit(payload.reference, payload.pairing_code, payload.sealed)
    return Response(status_code=204)


@router.post("/auth/cli-proof/take", response_model=SupportCliProofEnvelope)
async def take_cli_proof(
    payload: SupportCliProofReference, request: Request, session: DbSession
) -> SupportCliProofEnvelope:
    sealed = await SupportCliProofs(session).take(
        request.cookies.get(SESSION_COOKIE), request.headers.get("x-support-csrf"),
        payload.reference,
    )
    return SupportCliProofEnvelope(sealed=sealed)


@router.get("/me", response_model=SupportProfile)
async def read_me(request: Request, session: DbSession) -> SupportProfile:
    operator, active = await SupportIdentity(session).current(request.cookies.get(SESSION_COOKIE))
    capabilities = list(
        await session.scalars(
            select(SupportOperatorGrant.capability)
            .where(SupportOperatorGrant.operator_id == operator.id)
            .order_by(SupportOperatorGrant.capability)
        )
    )
    active.last_seen_at = utc_now()
    await session.commit()
    return SupportProfile(
        operator_id=operator.id, expires_at=active.expires_at, capabilities=capabilities
    )


@router.get("/cases/{case_id}/logs", response_model=SupportRequestLogPage)
async def get_case_logs(
    case_id: UUID,
    query: Annotated[SupportRequestLogQuery, Query()],
    request: Request,
    session: DbSession,
) -> SupportRequestLogPage:
    return await read_case_request_logs(
        session, request.cookies.get(SESSION_COOKIE), case_id, query, request.state.request_id
    )


@router.post("/cases/{case_id}/exports", status_code=201, response_model=SupportEvidenceExportRead)
async def propose_evidence_export(
    case_id: UUID, payload: SupportEvidenceExportCreate, request: Request, session: DbSession
) -> SupportEvidenceExportRead:
    return await SupportEvidenceExports(session).propose(
        request.cookies.get(SESSION_COOKIE), request.headers.get("x-support-csrf"),
        case_id, payload, request.state.request_id,
    )


@router.post(
    "/cases/{case_id}/exports/{export_id}/{stage}/options",
    response_model=SupportEvidenceProofOptions,
)
async def evidence_export_options(
    case_id: UUID, export_id: UUID, stage: Literal["review", "download"],
    request: Request, session: DbSession,
) -> SupportEvidenceProofOptions:
    challenge_id, options, receipt = await SupportEvidenceExports(session).options(
        request.cookies.get(SESSION_COOKIE), request.headers.get("x-support-csrf"),
        case_id, export_id, stage,
    )
    return SupportEvidenceProofOptions(
        challenge_id=challenge_id,
        public_key=SupportPublicKeyOptions.model_validate_json(options),
        export=receipt,
    )


@router.post(
    "/cases/{case_id}/exports/{export_id}/review", response_model=SupportEvidenceExportRead
)
async def review_evidence_export(
    case_id: UUID, export_id: UUID, payload: SupportEvidenceDecision,
    request: Request, session: DbSession,
) -> SupportEvidenceExportRead:
    receipt, _ = await SupportEvidenceExports(session).decide(
        request.cookies.get(SESSION_COOKIE), request.headers.get("x-support-csrf"),
        case_id, export_id, "review", payload.expected_sha256, payload.challenge_id,
        payload.credential.model_dump(), request.state.request_id,
    )
    return receipt


@router.post(
    "/cases/{case_id}/exports/{export_id}/download",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def download_evidence_export(
    case_id: UUID, export_id: UUID, payload: SupportEvidenceDecision,
    request: Request, session: DbSession,
) -> Response:
    receipt, content = await SupportEvidenceExports(session).decide(
        request.cookies.get(SESSION_COOKIE), request.headers.get("x-support-csrf"),
        case_id, export_id, "download", payload.expected_sha256, payload.challenge_id,
        payload.credential.model_dump(), request.state.request_id,
    )
    return Response(content, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="support-evidence-{export_id}.csv"',
        "Cache-Control": "no-store",
        "X-Support-Export-Sha256": receipt.sha256,
        "X-Support-Export-Truncated": str(receipt.truncated).lower(),
    })


@router.get(
    "/cases/{case_id}/logs/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def stream_case_logs(
    case_id: UUID,
    query: Annotated[SupportRequestLogStreamQuery, Query()],
    request: Request,
    last_event_id: Annotated[UUID | None, Header()] = None,
) -> StreamingResponse:
    if request.headers.get("sec-fetch-site") not in (None, "same-origin"):
        raise AppException(
            "Support request origin is not allowed.",
            status_code=403,
            error_code="SUPPORT_ORIGIN_DENIED",
        )
    token = request.cookies.get(SESSION_COOKIE)
    stream = await open_case_log_stream(
        token, case_id, query, request.state.request_id, last_event_id
    )
    return ManagedEventStream(
        case_log_events(stream, token, case_id, query.request_id),
        partial(close_case_log_stream, stream.id),
    )


@router.post("/auth/logout", status_code=204, response_class=Response)
async def logout(request: Request, response: Response, session: DbSession) -> Response:
    await SupportIdentity(session).logout(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        request.state.request_id,
    )
    response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, secure=True, samesite="strict")
    response.status_code = 204
    return response


class SuspensionRequest(_StrictPayload):
    target_id: UUID


class SuspensionRead(BaseModel):
    suspension_id: UUID
    target_id: UUID
    expires_at: datetime


class SuspensionOptions(SupportLoginOptions):
    target_id: UUID


@router.post("/custody/suspensions", status_code=201, response_model=SuspensionRead)
async def propose_suspension(
    payload: SuspensionRequest, request: Request, session: DbSession
) -> SuspensionRead:
    proposal = await SupportCustody(session).propose(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        payload.target_id,
        request.state.request_id,
    )
    return SuspensionRead(
        suspension_id=proposal.id, target_id=proposal.target_id, expires_at=proposal.expires_at
    )


@router.post(
    "/custody/suspensions/{suspension_id}/{stage}/options", response_model=SuspensionOptions
)
async def suspension_options(
    suspension_id: UUID, stage: Stage, request: Request, session: DbSession
) -> SuspensionOptions:
    challenge_id, options, proposal = await SupportCustody(session).options(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        suspension_id,
        stage,
    )
    return SuspensionOptions(
        challenge_id=challenge_id,
        public_key=SupportPublicKeyOptions.model_validate(json.loads(options)),
        target_id=proposal.target_id,
    )


@router.post(
    "/custody/suspensions/{suspension_id}/{stage}", status_code=204, response_class=Response
)
async def decide_suspension(
    suspension_id: UUID,
    stage: Stage,
    payload: SupportVerifyRequest,
    request: Request,
    session: DbSession,
) -> Response:
    await SupportCustody(session).decide(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        suspension_id,
        stage,
        payload.challenge_id,
        payload.credential.model_dump(),
        request.state.request_id,
    )
    return Response(status_code=204)


@router.post("/cases", status_code=201, response_model=SupportCaseRead)
async def create_case(
    payload: SupportCaseCreate, request: Request, session: DbSession
) -> SupportCaseRead:
    return await SupportCases(session).create(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        payload,
        request.state.request_id,
    )


@router.get("/cases", response_model=SupportCasePage)
async def list_cases(
    request: Request,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> SupportCasePage:
    return await SupportCases(session).list(
        request.cookies.get(SESSION_COOKIE), limit, cursor, request.state.request_id
    )


@router.get("/cases/{case_id}", response_model=SupportCaseRead)
async def read_case(case_id: UUID, request: Request, session: DbSession) -> SupportCaseRead:
    return await SupportCases(session).detail(
        request.cookies.get(SESSION_COOKIE), case_id, request.state.request_id
    )


@router.post("/cases/{case_id}/transitions", response_model=SupportCaseRead)
async def transition_case(
    case_id: UUID,
    payload: SupportCaseTransition,
    request: Request,
    session: DbSession,
    if_match: Annotated[str, Header(pattern=r'^"[1-9][0-9]{0,9}"$')],
) -> SupportCaseRead:
    return await SupportCases(session).transition(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        case_id,
        int(if_match[1:-1]),
        payload,
        request.state.request_id,
    )


class GrantChangeRequest(_StrictPayload):
    target_id: UUID
    capability: GrantCapability
    enable: StrictBool


class GrantChangeRead(BaseModel):
    grant_change_id: UUID
    target_id: UUID
    capability: GrantCapability
    enable: bool
    expires_at: datetime


class GrantChangeOptions(SupportLoginOptions):
    target_id: UUID
    capability: GrantCapability
    enable: bool


@router.post("/custody/grant-changes", status_code=201, response_model=GrantChangeRead)
async def propose_grant_change(
    payload: GrantChangeRequest, request: Request, session: DbSession
) -> GrantChangeRead:
    proposal = await SupportCustody(session).propose(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        payload.target_id,
        request.state.request_id,
        capability=payload.capability,
        enable=payload.enable,
    )
    return GrantChangeRead(
        grant_change_id=proposal.id,
        target_id=proposal.target_id,
        capability=payload.capability,
        enable=payload.enable,
        expires_at=proposal.expires_at,
    )


@router.post(
    "/custody/grant-changes/{change_id}/{stage}/options", response_model=GrantChangeOptions
)
async def grant_change_options(
    change_id: UUID, stage: Stage, request: Request, session: DbSession
) -> GrantChangeOptions:
    challenge_id, options, proposal = await SupportCustody(session).options(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        change_id,
        stage,
        kind="grant_change",
    )
    return GrantChangeOptions.model_validate(
        {
            "challenge_id": challenge_id,
            "public_key": json.loads(options),
            "target_id": proposal.target_id,
            "capability": proposal.capability,
            "enable": proposal.enable,
        }
    )


@router.post("/custody/grant-changes/{change_id}/{stage}", status_code=204, response_class=Response)
async def decide_grant_change(
    change_id: UUID,
    stage: Stage,
    payload: SupportVerifyRequest,
    request: Request,
    session: DbSession,
) -> Response:
    await SupportCustody(session).decide(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        change_id,
        stage,
        payload.challenge_id,
        payload.credential.model_dump(),
        request.state.request_id,
        kind="grant_change",
    )
    return Response(status_code=204)


class RegistrationProposal(_StrictPayload):
    target_id: UUID
    kind: RegistrationKind


class RegistrationProposalRead(BaseModel):
    proposal_id: UUID
    target_id: UUID
    kind: RegistrationKind
    expires_at: datetime


class RegistrationProofOptions(SupportLoginOptions):
    target_id: UUID
    kind: RegistrationKind


class RegistrationDecision(BaseModel):
    invitations: tuple[str, str] | None


@router.post("/custody/registrations", status_code=201, response_model=RegistrationProposalRead)
async def propose_registration(
    payload: RegistrationProposal, request: Request, session: DbSession
) -> RegistrationProposalRead:
    proposal = await SupportCustody(session).propose(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        payload.target_id,
        request.state.request_id,
        registration_kind=payload.kind,
    )
    return RegistrationProposalRead(
        proposal_id=proposal.id,
        target_id=proposal.target_id,
        kind=payload.kind,
        expires_at=proposal.expires_at,
    )


@router.post(
    "/custody/registrations/{kind}/{proposal_id}/{stage}/options",
    response_model=RegistrationProofOptions,
)
async def registration_proof_options(
    kind: RegistrationKind, proposal_id: UUID, stage: Stage, request: Request, session: DbSession
) -> RegistrationProofOptions:
    challenge_id, options, proposal = await SupportCustody(session).options(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        proposal_id,
        stage,
        kind=kind,
    )
    return RegistrationProofOptions(
        challenge_id=challenge_id,
        public_key=SupportPublicKeyOptions.model_validate(json.loads(options)),
        kind=kind,
        target_id=proposal.target_id,
    )


@router.post(
    "/custody/registrations/{kind}/{proposal_id}/{stage}", response_model=RegistrationDecision
)
async def decide_registration(
    kind: RegistrationKind,
    proposal_id: UUID,
    stage: Stage,
    payload: SupportVerifyRequest,
    request: Request,
    session: DbSession,
) -> RegistrationDecision:
    invitations = await SupportCustody(session).decide(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        proposal_id,
        stage,
        payload.challenge_id,
        payload.credential.model_dump(),
        request.state.request_id,
        kind=kind,
    )
    return RegistrationDecision(invitations=invitations)


class RegistrationInvitation(_StrictPayload):
    invitation: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")]


class RegistrationAttestationResponse(_StrictPayload):
    attestationObject: Annotated[
        str, StringConstraints(min_length=1, max_length=16384, pattern=r"^[A-Za-z0-9_-]+$")
    ]
    clientDataJSON: Base64Value


class RegistrationAttestation(_StrictPayload):
    id: Base64Value
    rawId: Base64Value
    type: Literal["public-key"]
    response: RegistrationAttestationResponse


class RegistrationVerify(RegistrationInvitation):
    credential: RegistrationAttestation


class RegistrationRp(BaseModel):
    id: str
    name: str


class RegistrationUser(BaseModel):
    id: Base64Value
    name: str
    displayName: str


class RegistrationAlgorithm(BaseModel):
    type: Literal["public-key"]
    alg: int


class RegistrationAuthenticator(BaseModel):
    residentKey: Literal["required"]
    requireResidentKey: bool
    userVerification: Literal["required"]


class RegistrationPublicKeyOptions(BaseModel):
    challenge: Base64Value
    rp: RegistrationRp
    user: RegistrationUser
    pubKeyCredParams: list[RegistrationAlgorithm]
    timeout: int
    attestation: Literal["none"]
    authenticatorSelection: RegistrationAuthenticator


class RegistrationCreationOptions(BaseModel):
    public_key: RegistrationPublicKeyOptions


class RegistrationResult(BaseModel):
    activated: bool
    awaiting_other_custodian: bool = False


class RegistrationStatus(BaseModel):
    operator_id: UUID
    state: RegistrationState


@router.post("/registration/status", response_model=RegistrationStatus)
async def registration_status(
    payload: RegistrationInvitation, session: DbSession
) -> RegistrationStatus:
    operator_id, state = await SupportRegistrationService(session).status(payload.invitation)
    return RegistrationStatus(operator_id=operator_id, state=state)


@router.post("/registration/options", response_model=RegistrationCreationOptions)
async def passkey_registration_options(
    payload: RegistrationInvitation, session: DbSession
) -> RegistrationCreationOptions:
    return RegistrationCreationOptions(
        public_key=RegistrationPublicKeyOptions.model_validate(
            json.loads(await SupportRegistrationService(session).options(payload.invitation))
        )
    )


@router.post(
    "/registration/verify", response_model=RegistrationResult, response_model_exclude_defaults=True
)
async def register_passkey(
    payload: RegistrationVerify, request: Request, session: DbSession
) -> RegistrationResult:
    activated, waiting = await SupportRegistrationService(session).register(
        payload.invitation, payload.credential.model_dump(), request.state.request_id
    )
    return RegistrationResult(activated=activated, awaiting_other_custodian=waiting)


@router.get("/health", response_model=SupportHealthRead)
async def support_health(request: Request, session: DbSession) -> SupportHealthRead:
    return await read_support_health(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


class CaseActionOptions(SupportLoginOptions):
    proposal: CaseActionRead


@router.post("/cases/{case_id}/actions", status_code=201, response_model=CaseActionRead)
async def propose_case_action(
    case_id: UUID,
    payload: CaseActionCreate,
    request: Request,
    session: DbSession,
    if_match: Annotated[str, Header(pattern=r'^"[1-9][0-9]{0,9}"$')],
) -> CaseActionRead:
    return await SupportCaseActions(session).propose(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        case_id,
        int(if_match[1:-1]),
        payload,
        request.state.request_id,
    )


@router.post("/cases/{case_id}/actions/{action_id}/options", response_model=CaseActionOptions)
async def case_action_options(
    case_id: UUID,
    action_id: UUID,
    request: Request,
    session: DbSession,
) -> CaseActionOptions:
    proof_id, options, proposal = await SupportCaseActions(session).options(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        case_id,
        action_id,
    )
    return CaseActionOptions(
        challenge_id=proof_id,
        public_key=SupportPublicKeyOptions.model_validate(json.loads(options)),
        proposal=proposal,
    )


@router.post("/cases/{case_id}/actions/{action_id}/apply", response_model=CaseActionRead)
async def apply_case_action(
    case_id: UUID,
    action_id: UUID,
    payload: SupportVerifyRequest,
    request: Request,
    session: DbSession,
) -> CaseActionRead:
    return await SupportCaseActions(session).apply(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        case_id,
        action_id,
        payload.challenge_id,
        payload.credential.model_dump(),
        request.state.request_id,
    )


@router.get("/cases/{case_id}/accounts", response_model=SupportAccountRead)
async def support_case_account(
    case_id: UUID, request: Request, session: DbSession
) -> SupportAccountRead:
    return await read_support_account(
        session, request.cookies.get(SESSION_COOKIE), case_id, request.state.request_id
    )


@router.get("/cases/{case_id}/accounts/{user_id}", response_model=SupportAccountRead)
async def support_account(
    case_id: UUID, user_id: UUID, request: Request, session: DbSession
) -> SupportAccountRead:
    return await read_support_account(
        session, request.cookies.get(SESSION_COOKIE), case_id, request.state.request_id,
        user_id=user_id,
    )


@router.post("/cases/{case_id}/accounts/search", response_model=SupportAccountRead)
async def search_support_case_account(
    case_id: UUID, payload: SupportAccountSelector, request: Request, session: DbSession
) -> SupportAccountRead:
    return await read_support_account(
        session, request.cookies.get(SESSION_COOKIE), case_id, request.state.request_id,
        selector=payload,
    )


@router.get("/cases/{case_id}/timeline", response_model=SupportTimelineRead)
async def support_case_timeline(
    case_id: UUID, request: Request, session: DbSession
) -> SupportTimelineRead:
    return await read_case_timeline(
        session, request.cookies.get(SESSION_COOKIE), case_id, request.state.request_id
    )


class BusinessActionProofOptions(SupportLoginOptions):
    proposal: BusinessActionRead
    required_reviews: int
    contact_ref: UUID | None = None


class BusinessActionReviewContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact_ref: UUID | None = None


class BusinessActionProofVerify(SupportVerifyRequest):
    expected_digest: ActionDigest
    expected_contact_ref: UUID | None = None


@router.post("/cases/{case_id}/account-actions", status_code=201, response_model=BusinessActionRead)
async def propose_business_action(
    case_id: UUID,
    payload: BusinessActionCreate,
    request: Request,
    session: DbSession,
    idempotency_key: Annotated[UUID, Header()],
) -> BusinessActionRead:
    return await SupportBusinessActions(session).propose(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        case_id,
        idempotency_key,
        payload,
        request.state.request_id,
    )


@router.post(
    "/cases/{case_id}/account-actions/{action_id}/{stage}/options",
    response_model=BusinessActionProofOptions,
)
async def business_action_options(
    case_id: UUID,
    action_id: UUID,
    stage: BusinessActionStage,
    request: Request,
    session: DbSession,
    payload: BusinessActionReviewContext | None = None,
) -> BusinessActionProofOptions:
    contact_ref = payload.contact_ref if payload else None
    challenge, options, proposal, reviews = await SupportBusinessActions(session).options(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        case_id,
        action_id,
        stage,
        contact_ref,
    )
    return BusinessActionProofOptions(
        challenge_id=challenge,
        public_key=SupportPublicKeyOptions.model_validate(json.loads(options)),
        proposal=proposal,
        required_reviews=reviews,
        contact_ref=contact_ref,
    )


@router.post(
    "/cases/{case_id}/account-actions/{action_id}/{stage}", response_model=BusinessActionRead
)
async def decide_business_action(
    case_id: UUID,
    action_id: UUID,
    stage: BusinessActionStage,
    payload: BusinessActionProofVerify,
    request: Request,
    session: DbSession,
) -> BusinessActionRead:
    return await SupportBusinessActions(session).decide(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        case_id,
        action_id,
        stage,
        payload.challenge_id,
        payload.expected_digest,
        payload.credential.model_dump(),
        request.state.request_id,
        payload.expected_contact_ref,
    )


@router.get(
    "/cases/{case_id}/account-actions/{action_id}/recovery-status",
    response_model=SupportRecoveryStatus,
)
async def support_recovery_status(
    case_id: UUID, action_id: UUID, request: Request, session: DbSession
) -> SupportRecoveryStatus:
    return await SupportBusinessActions(session).recovery_status(
        request.cookies.get(SESSION_COOKIE), case_id, action_id, request.state.request_id
    )


@router.get("/cases/{case_id}/audit", response_model=SupportAuditPage)
async def support_case_audit(
    case_id: UUID,
    query: Annotated[SupportAuditQuery, Query()],
    request: Request,
    session: DbSession,
) -> SupportAuditPage:
    return await read_case_audit(
        session, request.cookies.get(SESSION_COOKIE), case_id, query, request.state.request_id
    )


@router.get(
    "/views/{view_id}/projection/permission-explanation",
    response_model=SupportPermissionExplanation,
)
async def support_permission_view(
    view_id: UUID,
    request: Request,
    session: DbSession,
) -> SupportPermissionExplanation:
    return await SupportPermissionViews(session).read(
        request.cookies.get(SESSION_COOKIE), view_id, request.state.request_id
    )


@router.get("/views/{view_id}/projection/request-summary", response_model=SupportRequestSummary)
async def support_request_summary(
    view_id: UUID, request: Request, session: DbSession
) -> SupportRequestSummary:
    return await SupportPermissionViews(session).read_request_summary(
        request.cookies.get(SESSION_COOKIE), view_id, request.state.request_id
    )


@router.get("/views/{view_id}/projection/navigation", response_model=SupportNavigationProjection)
async def support_navigation(
    view_id: UUID, request: Request, session: DbSession
) -> SupportNavigationProjection:
    return await SupportPermissionViews(session).read_navigation(
        request.cookies.get(SESSION_COOKIE), view_id, request.state.request_id
    )


@router.get("/views/{view_id}/projection/project-list", response_model=SupportProjectList)
async def support_project_list(
    view_id: UUID, request: Request, session: DbSession
) -> SupportProjectList:
    return await SupportPermissionViews(session).read_projects(
        request.cookies.get(SESSION_COOKIE), view_id, request.state.request_id
    )


@router.get(
    "/views/{view_id}/projection/project-detail-summary", response_model=SupportProjectDetail
)
async def support_project_detail(
    view_id: UUID, request: Request, session: DbSession
) -> SupportProjectDetail:
    return await SupportPermissionViews(session).read_project_detail(
        request.cookies.get(SESSION_COOKIE), view_id, request.state.request_id
    )


@router.get("/portal-preview/{view_id}", response_model=SupportPortalPreview)
async def read_portal_preview(
    view_id: UUID,
    request: Request,
    session: DbSession,
    page: PortalPreviewPage = "home",
    project: Annotated[str | None, Query(pattern=r"^Project [0-9]{2}$")] = None,
) -> SupportPortalPreview:
    return await SupportPermissionViews(session).read_portal_preview(
        request.cookies.get(SESSION_COOKIE), view_id, request.state.request_id, page, project
    )


@router.api_route(
    "/portal-preview/{view_id}", methods=["POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def refuse_portal_preview_mutation(
    view_id: UUID, request: Request, session: DbSession,
) -> Response:
    error = AppException(
        "Portal previews are read-only.", status_code=403, error_code="SUPPORT_PREVIEW_READ_ONLY"
    )
    await SupportPermissionViews(session).record_portal_preview_denial(
        request.cookies.get(SESSION_COOKIE), view_id, request.state.request_id, "mutation", error
    )
    raise error


@router.post("/portal-preview/{view_id}/end", status_code=204, response_class=Response)
async def end_portal_preview(view_id: UUID, request: Request, session: DbSession) -> Response:
    await SupportPermissionViews(session).end(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        view_id,
        request.state.request_id,
        expected_kind="portal_preview",
    )
    return Response(status_code=204)


@router.post("/views/{view_id}/end", status_code=204, response_class=Response)
async def end_permission_view(view_id: UUID, request: Request, session: DbSession) -> Response:
    await SupportPermissionViews(session).end(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        view_id,
        request.state.request_id,
    )
    return Response(status_code=204)


@router.get("/overview", response_model=SupportCompanyOverviewRead)
async def support_company_overview(
    request: Request, session: DbSession
) -> SupportCompanyOverviewRead:
    return await read_company_overview(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get("/overview/projects", response_model=SupportProjectsOverviewRead)
async def support_projects_overview(
    request: Request,
    session: DbSession,
    case_id: UUID | None = None,
    project_id: UUID | None = None,
) -> SupportProjectsOverviewRead:
    return await read_projects_overview(
        session,
        request.cookies.get(SESSION_COOKIE),
        request.state.request_id,
        case_id=case_id,
        project_id=project_id,
    )


@router.get("/overview/workforce", response_model=SupportWorkforceOverviewRead)
async def support_workforce_overview(
    request: Request, session: DbSession
) -> SupportWorkforceOverviewRead:
    return await read_workforce_overview(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get("/overview/inventory", response_model=SupportInventoryOverviewRead)
async def support_inventory_overview(
    request: Request,
    session: DbSession,
    case_id: UUID | None = None,
    project_id: UUID | None = None,
) -> SupportInventoryOverviewRead:
    return await read_inventory_overview(
        session,
        request.cookies.get(SESSION_COOKIE),
        request.state.request_id,
        case_id=case_id,
        project_id=project_id,
    )


@router.get("/overview/suppliers", response_model=SupportSuppliersOverviewRead)
async def support_suppliers_overview(
    request: Request, session: DbSession
) -> SupportSuppliersOverviewRead:
    return await read_suppliers_overview(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get("/overview/documents", response_model=SupportDocumentsOverviewRead)
async def support_documents_overview(
    request: Request, session: DbSession
) -> SupportDocumentsOverviewRead:
    return await read_documents_overview(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get("/overview/finance", response_model=SupportFinanceOverviewRead)
async def support_finance_overview(
    request: Request, session: DbSession
) -> SupportFinanceOverviewRead:
    return await read_finance_overview(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get("/overview/approvals", response_model=SupportApprovalsOverviewRead)
async def support_approvals_overview(
    request: Request, session: DbSession
) -> SupportApprovalsOverviewRead:
    return await read_approvals_overview(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get("/policy/explain", response_model=SupportPolicyExplainRead)
async def support_policy_explain(
    query: Annotated[SupportPolicyExplainQuery, Query()],
    request: Request,
    session: DbSession,
) -> SupportPolicyExplainRead:
    return await explain_role_policy(
        session, request.cookies.get(SESSION_COOKIE), query, request.state.request_id
    )


@router.get("/monitor/jobs", response_model=SupportJobsMonitorRead)
async def support_jobs_monitor(
    query: Annotated[SupportJobsQuery, Query()],
    request: Request,
    session: DbSession,
) -> SupportJobsMonitorRead:
    return await read_jobs_monitor(
        session, request.cookies.get(SESSION_COOKIE), query, request.state.request_id
    )


@router.get("/monitor/backups", response_model=SupportBackupsMonitorRead)
async def support_backups_monitor(
    request: Request, session: DbSession
) -> SupportBackupsMonitorRead:
    return await read_backups_monitor(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get("/config/status", response_model=SupportConfigStatusRead)
async def support_config_status(
    request: Request, session: DbSession
) -> SupportConfigStatusRead:
    return await read_config_status(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get("/incidents/summary", response_model=SupportIncidentsSummaryRead)
async def support_incidents_summary(
    query: Annotated[SupportIncidentsQuery, Query()],
    request: Request,
    session: DbSession,
) -> SupportIncidentsSummaryRead:
    return await read_incidents_summary(
        session, request.cookies.get(SESSION_COOKIE), query, request.state.request_id
    )


class SupportAdminCommandProofOptions(SupportLoginOptions):
    command: SupportAdminCommandRead


class SupportAdminCommandExecuteRequest(SupportVerifyRequest):
    expected_plan_sha256: ActionDigest


@router.get("/company/context", response_model=SupportCompanyContextRead)
async def support_company_context(
    request: Request, session: DbSession
) -> SupportCompanyContextRead:
    return await read_company_context(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get("/company/users", response_model=SupportCompanyUserPage)
async def support_company_users(
    request: Request,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=120)] = None,
    role: Annotated[str | None, Query(max_length=64)] = None,
    state: Annotated[Literal["active", "inactive", "locked"] | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> SupportCompanyUserPage:
    return await list_company_users(
        session,
        request.cookies.get(SESSION_COOKIE),
        request.state.request_id,
        search=search,
        role=role,
        state=state,
        cursor=cursor,
        limit=limit,
    )


@router.get("/company/users/{user_id}", response_model=SupportCompanyUserProfileRead)
async def support_company_user_profile(
    user_id: UUID, request: Request, session: DbSession
) -> SupportCompanyUserProfileRead:
    return await read_company_user_profile(
        session, request.cookies.get(SESSION_COOKIE), user_id, request.state.request_id
    )


@router.get("/company/users/{user_id}/access", response_model=SupportCompanyUserAccessRead)
async def support_company_user_access(
    user_id: UUID,
    request: Request,
    session: DbSession,
    project_id: UUID | None = None,
) -> SupportCompanyUserAccessRead:
    return await read_company_user_access(
        session,
        request.cookies.get(SESSION_COOKIE),
        user_id,
        request.state.request_id,
        project_id=project_id,
    )


@router.get("/company/users/{user_id}/sessions", response_model=SupportUserSessionInventoryRead)
async def support_company_user_sessions(
    user_id: UUID, request: Request, session: DbSession
) -> SupportUserSessionInventoryRead:
    return await read_company_user_sessions(
        session, request.cookies.get(SESSION_COOKIE), user_id, request.state.request_id
    )


@router.get("/company/users/{user_id}/activity", response_model=SupportUserActivityPage)
async def support_company_user_activity(
    user_id: UUID, request: Request, session: DbSession
) -> SupportUserActivityPage:
    return await read_company_user_activity(
        session, request.cookies.get(SESSION_COOKIE), user_id, request.state.request_id
    )


@router.post(
    "/company/users/{user_id}/diagnose-case",
    status_code=201,
    response_model=SupportDiagnoseCaseRead,
)
async def support_company_user_diagnose_case(
    user_id: UUID,
    payload: SupportDiagnoseCaseRequest,
    request: Request,
    session: DbSession,
) -> SupportDiagnoseCaseRead:
    return await diagnose_or_link_user_case(
        session,
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        user_id,
        payload,
        request.state.request_id,
    )


@router.post(
    "/company/commands/plan",
    status_code=201,
    response_model=SupportAdminCommandRead,
)
async def plan_company_admin_command(
    payload: SupportAdminCommandPlanRequest,
    request: Request,
    session: DbSession,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=64)],
) -> SupportAdminCommandRead:
    return await SupportAdminCommands(session).plan(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        idempotency_key,
        payload,
        request.state.request_id,
    )


@router.post(
    "/company/commands/{command_id}/proof/options",
    response_model=SupportAdminCommandProofOptions,
)
async def company_admin_command_proof_options(
    command_id: UUID, request: Request, session: DbSession
) -> SupportAdminCommandProofOptions:
    challenge_id, options_json, command = await SupportAdminCommands(session).options(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        command_id,
        request.state.request_id,
    )
    return SupportAdminCommandProofOptions(
        challenge_id=challenge_id,
        public_key=SupportPublicKeyOptions.model_validate(json.loads(options_json)),
        command=command,
    )


@router.post(
    "/company/commands/{command_id}/execute",
    response_model=SupportAdminCommandRead,
)
async def execute_company_admin_command(
    command_id: UUID,
    payload: SupportAdminCommandExecuteRequest,
    request: Request,
    session: DbSession,
) -> SupportAdminCommandRead:
    return await SupportAdminCommands(session).execute(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        command_id,
        payload.challenge_id,
        payload.expected_plan_sha256,
        payload.credential.model_dump(),
        request.state.request_id,
    )


@router.get("/company/commands/{command_id}", response_model=SupportAdminCommandRead)
async def read_company_admin_command(
    command_id: UUID, request: Request, session: DbSession
) -> SupportAdminCommandRead:
    return await SupportAdminCommands(session).get_command(
        request.cookies.get(SESSION_COOKIE), command_id, request.state.request_id
    )


@router.get("/company/settings", response_model=SupportSafeSettingsRead)
async def support_company_safe_settings(
    request: Request, session: DbSession
) -> SupportSafeSettingsRead:
    return await read_safe_settings(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get("/company/owner-security", response_model=SupportOwnerSecurityRead)
async def support_company_owner_security(
    request: Request, session: DbSession
) -> SupportOwnerSecurityRead:
    return await read_owner_security(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get(
    "/company/data-inspector/entities",
    response_model=SupportDataInspectorCatalogRead,
)
async def support_company_data_inspector_catalog(
    request: Request, session: DbSession
) -> SupportDataInspectorCatalogRead:
    return await read_data_inspector_catalog(
        session, request.cookies.get(SESSION_COOKIE), request.state.request_id
    )


@router.get(
    "/company/data-inspector/{entity_key}",
    response_model=SupportDataInspectorPage,
)
async def support_company_data_inspector_query(
    entity_key: str,
    request: Request,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=120)] = None,
    status: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    offset: Annotated[int, Query(ge=0, le=5000)] = 0,
) -> SupportDataInspectorPage:
    return await query_data_inspector_entity(
        session,
        request.cookies.get(SESSION_COOKIE),
        entity_key,
        request.state.request_id,
        search=search,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/feedback", response_model=FeedbackInboxPage)
async def support_feedback_inbox(
    request: Request,
    session: DbSession,
    status: FeedbackStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FeedbackInboxPage:
    return await FeedbackService(session).list_inbox(
        request.cookies.get(SESSION_COOKIE),
        request.state.request_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.patch("/feedback/{feedback_id}/status", response_model=FeedbackInboxItem)
async def support_feedback_status(
    feedback_id: UUID,
    payload: FeedbackStatusChange,
    request: Request,
    session: DbSession,
) -> FeedbackInboxItem:
    return await FeedbackService(session).change_status(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("x-support-csrf"),
        request.state.request_id,
        feedback_id,
        payload,
    )
