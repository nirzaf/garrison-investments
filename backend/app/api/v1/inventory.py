from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.models.inventory import InventoryItem, InventoryLocationStock, MaterialRequest
from app.models.user import User
from app.schemas.inventory import (
    AssetCreateRequest,
    AssetResponse,
    InventoryItemCreateRequest,
    InventoryItemResponse,
    InventoryRegistrationCorrectionRequest,
    InventoryRegistrationCreateRequest,
    InventoryRegistrationDecisionRequest,
    InventoryRegistrationPageResponse,
    InventoryRegistrationResponse,
    InventoryRegistrationSubmitRequest,
    LocationCreateRequest,
    LocationResponse,
    MaterialDraftSave,
    MaterialQuantityCommand,
    MaterialRequestDraftCreate,
    MaterialRequestReplacementRequest,
    MaterialRequestResponse,
    MaterialRequestResubmitRequest,
    MaterialRequestSubmitRequest,
    MaterialSubmissionHistoryResponse,
    MaterialSubmissionResponse,
    MovementCreateRequest,
    MovementResponse,
    RegistrationCorrectionAsset,
    RegistrationCorrectionAssets,
    RequestProjectOption,
    RequestProjectOptions,
    StockResponse,
)
from app.services.approval_service import ApprovalService
from app.services.evidence_classification import readable_document_ids, readable_photo_ids
from app.services.idempotency import validate_key
from app.services.inventory_registration_service import InventoryRegistrationService
from app.services.inventory_service import InventoryService
from app.utils.exceptions import AppException
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_FINANCIAL_VIEW,
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_INVENTORY_VIEW,
    ROLE_ADMINISTRATIVE_EXECUTIVE,
    ensure_permission,
    has_permission,
)

router = APIRouter(prefix="/inventory", tags=["Inventory"])

CanViewInventory = Annotated[User, Depends(require_permission(PERMISSION_INVENTORY_VIEW))]
CanManageInventory = Annotated[User, Depends(require_permission(PERMISSION_INVENTORY_MANAGE))]


def require_material_processor(actor: CurrentUser) -> User:
    if actor.role != ROLE_ADMINISTRATIVE_EXECUTIVE:
        ensure_permission(actor, PERMISSION_INVENTORY_MANAGE)
    return actor


CanProcessMaterial = Annotated[User, Depends(require_material_processor)]

PAGINATION_HEADERS: dict[int | str, dict[str, Any]] = {
    200: {"headers": {"X-Total-Count": {"schema": {"type": "integer", "minimum": 0}}}}
}


def stock_response(stock: InventoryLocationStock) -> StockResponse:
    return StockResponse(
        id=stock.id,
        item_id=stock.item_id,
        location_id=stock.location_id,
        location_name=stock.location.name,
        on_hand_qty=stock.on_hand_qty,
        reserved_qty=stock.reserved_qty,
        available_qty=stock.on_hand_qty - stock.reserved_qty,
    )


def item_response(item: InventoryItem, actor: User) -> InventoryItemResponse:
    """Mask unit_cost on the response only — never on the persistent ORM instance."""
    response = InventoryItemResponse.model_validate(item)
    if actor.role not in COMPANY_RESOURCE_ROLES or not has_permission(
        actor, PERMISSION_FINANCIAL_VIEW
    ):
        response.unit_cost = None
    return response


def material_request_response(
    request: MaterialRequest | MaterialRequestResponse, actor: User
) -> MaterialRequestResponse:
    response = (
        request
        if isinstance(request, MaterialRequestResponse)
        else MaterialRequestResponse.model_validate(request)
    )
    can_view_financial = has_permission(actor, PERMISSION_FINANCIAL_VIEW)
    if can_view_financial and response.submission_revision is not None:
        # Current line prices are persisted with the request. A null line cost
        # means the stored total is only a known subtotal, not a full estimate.
        complete = bool(response.lines) and all(
            line.unit_cost is not None for line in response.lines
        )
        response = response.model_copy(
            update={
                "valuation_status": "complete" if complete else "incomplete",
                "total_estimated_cost": response.total_estimated_cost if complete else None,
            }
        )
    else:
        response = response.model_copy(update={"valuation_status": None})
    if not can_view_financial:
        response = response.model_copy(
            update={
                "total_estimated_cost": None,
                "lines": [line.model_copy(update={"unit_cost": None}) for line in response.lines],
            }
        )
    return response


@router.get("/locations", response_model=list[LocationResponse])
async def list_locations(
    current_user: CanViewInventory, session: DbSession
) -> list[LocationResponse]:
    locations = await InventoryService(session).list_locations(current_user)
    return [LocationResponse.model_validate(location) for location in locations]


@router.post("/locations", response_model=LocationResponse, status_code=status.HTTP_201_CREATED)
async def create_location(
    payload: LocationCreateRequest,
    current_user: CanManageInventory,
    session: DbSession,
) -> LocationResponse:
    location = await InventoryService(session).create_location(payload, current_user)
    return LocationResponse.model_validate(location)


@router.get("/items", response_model=list[InventoryItemResponse], responses=PAGINATION_HEADERS)
async def list_items(
    current_user: CanViewInventory,
    session: DbSession,
    response: Response,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[InventoryItemResponse]:
    items, total = await InventoryService(session).list_item_page(
        search, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return [item_response(item, current_user) for item in items]


@router.post("/items", response_model=InventoryItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: InventoryItemCreateRequest,
    current_user: CanManageInventory,
    session: DbSession,
) -> InventoryItemResponse:
    item = await InventoryService(session).create_item(payload, current_user)
    return item_response(item, current_user)


@router.get("/items/{item_id}", response_model=InventoryItemResponse)
async def get_item(
    item_id: UUID,
    current_user: CanViewInventory,
    session: DbSession,
) -> InventoryItemResponse:
    item = await InventoryService(session).get_item(item_id)
    return item_response(item, current_user)


@router.get("/items/{item_id}/stock", response_model=list[StockResponse])
async def list_item_stock(
    item_id: UUID,
    current_user: CanViewInventory,
    session: DbSession,
) -> list[StockResponse]:
    stock_rows = await InventoryService(session).list_stock(item_id, current_user)
    return [stock_response(stock) for stock in stock_rows]


@router.get("/assets", response_model=list[AssetResponse])
async def list_assets(current_user: CanViewInventory, session: DbSession) -> list[AssetResponse]:
    assets = await InventoryService(session).list_assets(current_user)
    return [AssetResponse.model_validate(asset) for asset in assets]


@router.post("/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    payload: AssetCreateRequest,
    current_user: CanManageInventory,
    session: DbSession,
) -> AssetResponse:
    asset = await InventoryService(session).create_asset(payload, current_user)
    return AssetResponse.model_validate(asset)


@router.get("/movements", response_model=list[MovementResponse], responses=PAGINATION_HEADERS)
async def list_movements(
    current_user: CanViewInventory,
    session: DbSession,
    response: Response,
    item_id: Annotated[UUID | None, Query()] = None,
    location_id: Annotated[UUID | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MovementResponse]:
    movements, total = await InventoryService(session).list_movements(
        actor=current_user,
        item_id=item_id,
        location_id=location_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return [MovementResponse.model_validate(movement) for movement in movements]


@router.post("/movements", response_model=MovementResponse, status_code=status.HTTP_201_CREATED)
async def create_movement(
    payload: MovementCreateRequest,
    current_user: CanManageInventory,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MovementResponse:
    movement = await InventoryService(session).create_movement(
        payload, current_user, idempotency_key=validate_key(idempotency_key)
    )
    return MovementResponse.model_validate(movement)


@router.get("/low-stock", response_model=list[StockResponse])
async def low_stock(current_user: CanViewInventory, session: DbSession) -> list[StockResponse]:
    stock_rows = await InventoryService(session).low_stock(current_user)
    return [stock_response(stock) for stock in stock_rows]


@router.get("/requests", response_model=list[MaterialRequestResponse], responses=PAGINATION_HEADERS)
async def list_material_requests(
    current_user: CanViewInventory,
    session: DbSession,
    response: Response,
    request_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MaterialRequestResponse]:
    requests, total = await InventoryService(session).list_material_requests(
        current_user, request_id=request_id, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return [material_request_response(request, current_user) for request in requests]


@router.post(
    "/requests", response_model=MaterialRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_material_request(
    payload: MaterialRequestSubmitRequest,
    current_user: CanViewInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).create_material_request(payload, current_user)
    return material_request_response(request, current_user)


@router.post(
    "/requests/drafts", response_model=MaterialRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_material_request_draft(
    payload: MaterialRequestDraftCreate,
    current_user: CanViewInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    draft = await InventoryService(session).create_material_draft(payload, current_user)
    return material_request_response(draft, current_user)


@router.put("/requests/drafts/{draft_id}", response_model=MaterialRequestResponse)
async def save_material_request_draft(
    draft_id: UUID, payload: MaterialDraftSave, current_user: CanViewInventory, session: DbSession
) -> MaterialRequestResponse:
    draft = await InventoryService(session).save_material_draft(draft_id, payload, current_user)
    return material_request_response(draft, current_user)


@router.post(
    "/requests/drafts/{draft_id}/submit-correction", response_model=MaterialRequestResponse
)
async def submit_material_correction_draft(
    draft_id: UUID,
    payload: MaterialRequestResubmitRequest,
    current_user: CanViewInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).submit_material_correction_draft(
        draft_id, payload, current_user
    )
    return material_request_response(request, current_user)


@router.post("/requests/{request_id}/resubmit", response_model=MaterialRequestResponse)
async def resubmit_material_request(
    request_id: UUID,
    payload: MaterialRequestResubmitRequest,
    current_user: CanViewInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).resubmit_material_request(
        request_id, payload, current_user
    )
    return material_request_response(request, current_user)


@router.post(
    "/requests/{request_id}/replacement",
    response_model=MaterialRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def replace_material_request_remainder(
    request_id: UUID,
    payload: MaterialRequestReplacementRequest,
    current_user: CanManageInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    replacement = await InventoryService(session).replace_material_remainder(
        request_id, payload, current_user
    )
    return material_request_response(replacement, current_user)


@router.get("/requests/{request_id}/submissions", response_model=MaterialSubmissionHistoryResponse)
async def material_submission_history(
    request_id: UUID,
    current_user: CanViewInventory,
    session: DbSession,
) -> MaterialSubmissionHistoryResponse:
    submissions, decisions = await InventoryService(session).material_submission_history(
        request_id, current_user
    )
    serialized_submissions = [MaterialSubmissionResponse.model_validate(row) for row in submissions]
    if not has_permission(current_user, PERMISSION_FINANCIAL_VIEW):
        photo_ids = [
            photo_id
            for item in serialized_submissions
            for photo_id in item.requirements.evidence_file_ids
        ]
        document_ids = [
            document_id
            for item in serialized_submissions
            for document_id in item.requirements.requirements.supporting_document_ids
        ]
        visible_photos = set(await readable_photo_ids(session, photo_ids, current_user))
        visible_documents = set(await readable_document_ids(session, document_ids, current_user))
        serialized_submissions = [
            item.model_copy(
                update={
                    "requirements": item.requirements.model_copy(
                        update={
                            "valuation_complete": None,
                            "valuation_status": None,
                            "evidence_file_ids": [
                                photo_id
                                for photo_id in item.requirements.evidence_file_ids
                                if photo_id in visible_photos
                            ],
                            "requirements": item.requirements.requirements.model_copy(
                                update={
                                    "supporting_document_ids": [
                                        document_id
                                        for document_id
                                        in item.requirements.requirements.supporting_document_ids
                                        if document_id in visible_documents
                                    ]
                                }
                            ),
                        }
                    )
                }
            )
            for item in serialized_submissions
        ]
    return MaterialSubmissionHistoryResponse(
        submissions=serialized_submissions,
        decisions=await ApprovalService(session).describe_approvals(decisions, current_user),
    )


@router.get("/request-projects", response_model=RequestProjectOptions)
async def list_material_request_projects(
    current_user: CanViewInventory,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RequestProjectOptions:
    projects, total = await InventoryService(session).list_request_projects(
        current_user, search=search, limit=limit, offset=offset
    )
    return RequestProjectOptions(
        items=[RequestProjectOption.model_validate(project) for project in projects], total=total
    )


@router.post("/requests/{request_id}/reserve", response_model=MaterialRequestResponse)
async def reserve_material_request(
    request_id: UUID,
    current_user: CanProcessMaterial,
    session: DbSession,
    command: MaterialQuantityCommand | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MaterialRequestResponse:
    service = InventoryService(session)
    if command is not None:
        result = await service.fulfill_quantities(
            request_id, current_user, command, action="reserve", key=quantity_key(idempotency_key)
        )
        return material_request_response(result, current_user)
    request = await service.reserve_request(request_id, current_user)
    return material_request_response(request, current_user)


@router.post("/requests/{request_id}/issue", response_model=MaterialRequestResponse)
async def issue_material_request(
    request_id: UUID,
    current_user: CanProcessMaterial,
    session: DbSession,
    command: MaterialQuantityCommand | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MaterialRequestResponse:
    service = InventoryService(session)
    if command is not None:
        result = await service.fulfill_quantities(
            request_id, current_user, command, action="issue", key=quantity_key(idempotency_key)
        )
        return material_request_response(result, current_user)
    request = await service.issue_request(request_id, current_user)
    return material_request_response(request, current_user)


def quantity_key(header: str | None) -> str:
    key = validate_key(header)
    if key is None:
        raise AppException(
            "Selected quantities require an Idempotency-Key.",
            status_code=422,
            error_code="REQUEST_IDEMPOTENCY_KEY_REQUIRED",
        )
    return key


@router.post("/requests/{request_id}/cancel", response_model=MaterialRequestResponse)
async def cancel_material_request(
    request_id: UUID,
    current_user: CanManageInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).cancel_request(request_id, current_user)
    return material_request_response(request, current_user)


@router.get("/registrations", response_model=InventoryRegistrationPageResponse)
async def list_inventory_registrations(
    actor: CanViewInventory,
    session: DbSession,
    registration_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InventoryRegistrationPageResponse:
    rows, total = await InventoryRegistrationService(session).list_registrations(
        actor, limit=limit, offset=offset, registration_id=registration_id
    )
    return InventoryRegistrationPageResponse(
        items=await _registration_responses(rows, session, actor),
        total=total,
    )


@router.get(
    "/registrations/{registration_id}/history", response_model=list[InventoryRegistrationResponse]
)
async def inventory_registration_history(
    registration_id: UUID, actor: CanViewInventory, session: DbSession
) -> list[InventoryRegistrationResponse]:
    rows = await InventoryRegistrationService(session).history(registration_id, actor)
    return await _registration_responses(rows, session, actor)


@router.post(
    "/registrations",
    response_model=InventoryRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_inventory_registration(
    payload: InventoryRegistrationCreateRequest, actor: CanViewInventory, session: DbSession
) -> InventoryRegistrationResponse:
    row = await InventoryRegistrationService(session).create(payload, actor)
    return (await _registration_responses([row], session, actor))[0]


@router.post(
    "/registrations/{registration_id}/submit", response_model=InventoryRegistrationResponse
)
async def submit_inventory_registration(
    registration_id: UUID,
    payload: InventoryRegistrationSubmitRequest,
    actor: CanViewInventory,
    session: DbSession,
) -> InventoryRegistrationResponse:
    row = await InventoryRegistrationService(session).submit(
        registration_id, payload.expected_submission_revision, actor
    )
    return (await _registration_responses([row], session, actor))[0]


@router.post(
    "/registrations/{registration_id}/decision", response_model=InventoryRegistrationResponse
)
async def decide_inventory_registration(
    registration_id: UUID,
    payload: InventoryRegistrationDecisionRequest,
    actor: CanViewInventory,
    session: DbSession,
) -> InventoryRegistrationResponse:
    row = await InventoryRegistrationService(session).decide(registration_id, payload, actor)
    return (await _registration_responses([row], session, actor))[0]


@router.get(
    "/registrations/{registration_id}/correction-assets",
    response_model=RegistrationCorrectionAssets,
)
async def list_registration_correction_assets(
    registration_id: UUID,
    actor: CanViewInventory,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RegistrationCorrectionAssets:
    rows, total, quantity = await InventoryRegistrationService(session).list_correction_assets(
        registration_id, actor, search=search, limit=limit, offset=offset
    )
    return RegistrationCorrectionAssets(
        items=[
            RegistrationCorrectionAsset(
                **AssetResponse.model_validate(row).model_dump(),
                location_name=row.current_location.name,
            )
            for row in rows
        ],
        total=total,
        effective_quantity=quantity,
    )


@router.post(
    "/registrations/{registration_id}/correction",
    response_model=InventoryRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def correct_inventory_registration(
    registration_id: UUID,
    payload: InventoryRegistrationCorrectionRequest,
    actor: CanViewInventory,
    session: DbSession,
) -> InventoryRegistrationResponse:
    row = await InventoryRegistrationService(session).correct(registration_id, payload, actor)
    return (await _registration_responses([row], session, actor))[0]


async def _registration_responses(rows, session, actor) -> list[InventoryRegistrationResponse]:
    responses = [InventoryRegistrationResponse.model_validate(row) for row in rows]
    if has_permission(actor, PERMISSION_FINANCIAL_VIEW):
        return responses
    photo_ids = [photo_id for response in responses for photo_id in response.evidence_ids]
    visible_ids = set(await readable_photo_ids(session, photo_ids, actor))
    return [
        response.model_copy(
            update={
                "evidence_ids": [
                    photo_id for photo_id in response.evidence_ids if photo_id in visible_ids
                ]
            }
        )
        for response in responses
    ]
