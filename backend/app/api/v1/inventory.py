from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.dependencies import DbSession, require_permission
from app.models.inventory import InventoryItem, InventoryLocationStock
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
from app.services.inventory_service import PRICE_VISIBLE_ROLES, InventoryService
from app.utils.exceptions import AppException
from app.utils.permissions import PERMISSION_INVENTORY_MANAGE, PERMISSION_INVENTORY_VIEW

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
    if actor.role not in PRICE_VISIBLE_ROLES:
        response.unit_cost = None
    return response


@router.get("/locations", response_model=list[LocationResponse])
async def list_locations(_: CanViewInventory, session: DbSession) -> list[LocationResponse]:
    locations = await InventoryService(session).list_locations()
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
    _: CanViewInventory,
    session: DbSession,
) -> list[StockResponse]:
    stock_rows = await InventoryService(session).list_stock(item_id)
    return [stock_response(stock) for stock in stock_rows]


@router.get("/assets", response_model=list[AssetResponse])
async def list_assets(_: CanViewInventory, session: DbSession) -> list[AssetResponse]:
    assets = await InventoryService(session).list_assets()
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
    _: CanViewInventory,
    session: DbSession,
    response: Response,
    item_id: Annotated[UUID | None, Query()] = None,
    location_id: Annotated[UUID | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MovementResponse]:
    movements, total = await InventoryService(session).list_movements(
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
) -> MovementResponse:
    movement = await InventoryService(session).create_movement(payload, current_user)
    return MovementResponse.model_validate(movement)


@router.get("/low-stock", response_model=list[StockResponse])
async def low_stock(_: CanViewInventory, session: DbSession) -> list[StockResponse]:
    stock_rows = await InventoryService(session).low_stock()
    return [stock_response(stock) for stock in stock_rows]


@router.get("/requests", response_model=list[MaterialRequestResponse], responses=PAGINATION_HEADERS)
async def list_material_requests(
    _: CanViewInventory,
    session: DbSession,
    response: Response,
    request_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MaterialRequestResponse]:
    requests, total = await InventoryService(session).list_material_requests(
        request_id=request_id, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return [MaterialRequestResponse.model_validate(request) for request in requests]


@router.post(
    "/requests", response_model=MaterialRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_material_request(
    payload: MaterialRequestCreateRequest,
    current_user: CanViewInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).create_material_request(payload, current_user)
    return MaterialRequestResponse.model_validate(request)


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
        return await service.fulfill_quantities(
            request_id, current_user, command, action="reserve", key=quantity_key(idempotency_key)
        )
    request = await service.reserve_request(request_id, current_user)
    return MaterialRequestResponse.model_validate(request)


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
        return await service.fulfill_quantities(
            request_id, current_user, command, action="issue", key=quantity_key(idempotency_key)
        )
    request = await service.issue_request(request_id, current_user)
    return MaterialRequestResponse.model_validate(request)


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
    current_user: CanViewInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).cancel_request(request_id, current_user)
    return MaterialRequestResponse.model_validate(request)
