from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.dependencies import DbSession, require_permission
from app.models.inventory import InventoryItem, InventoryLocationStock, MaterialRequest
from app.models.user import User
from app.schemas.inventory import (
    AssetCreateRequest,
    AssetResponse,
    InventoryItemCreateRequest,
    InventoryItemResponse,
    LocationCreateRequest,
    LocationResponse,
    MaterialQuantityCommand,
    MaterialRequestCreateRequest,
    MaterialRequestResponse,
    MovementCreateRequest,
    MovementResponse,
    RequestProjectOption,
    RequestProjectOptions,
    StockResponse,
)
from app.services.idempotency import validate_key
from app.services.inventory_service import InventoryService
from app.utils.exceptions import AppException
from app.utils.permissions import (
    PERMISSION_FINANCIAL_VIEW,
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_INVENTORY_VIEW,
    has_permission,
)

router = APIRouter(prefix="/inventory", tags=["Inventory"])

CanViewInventory = Annotated[User, Depends(require_permission(PERMISSION_INVENTORY_VIEW))]
CanManageInventory = Annotated[User, Depends(require_permission(PERMISSION_INVENTORY_MANAGE))]

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
    if not has_permission(actor, PERMISSION_FINANCIAL_VIEW):
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
    if not has_permission(actor, PERMISSION_FINANCIAL_VIEW):
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
    payload: MaterialRequestCreateRequest,
    current_user: CanManageInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).create_material_request(payload, current_user)
    return material_request_response(request, current_user)


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
    current_user: CanManageInventory,
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
    current_user: CanManageInventory,
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
