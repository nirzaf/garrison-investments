from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.models.inventory import InventoryLocationStock
from app.models.user import User
from app.schemas.inventory import (
    AssetCreateRequest,
    AssetResponse,
    InventoryItemCreateRequest,
    InventoryItemResponse,
    LocationCreateRequest,
    LocationResponse,
    MaterialRequestCreateRequest,
    MaterialRequestResponse,
    MovementCreateRequest,
    MovementResponse,
    StockResponse,
)
from app.services.inventory_service import InventoryService
from app.utils.permissions import PERMISSION_INVENTORY_MANAGE, PERMISSION_INVENTORY_VIEW

router = APIRouter(prefix="/inventory", tags=["Inventory"])

CanViewInventory = Annotated[User, Depends(require_permission(PERMISSION_INVENTORY_VIEW))]
CanManageInventory = Annotated[User, Depends(require_permission(PERMISSION_INVENTORY_MANAGE))]


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


@router.get("/items", response_model=list[InventoryItemResponse])
async def list_items(
    current_user: CanViewInventory,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> list[InventoryItemResponse]:
    items = await InventoryService(session).list_items(current_user, search)
    return [InventoryItemResponse.model_validate(item) for item in items]


@router.post("/items", response_model=InventoryItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: InventoryItemCreateRequest,
    current_user: CanManageInventory,
    session: DbSession,
) -> InventoryItemResponse:
    item = await InventoryService(session).create_item(payload, current_user)
    return InventoryItemResponse.model_validate(item)


@router.get("/items/{item_id}", response_model=InventoryItemResponse)
async def get_item(
    item_id: UUID,
    current_user: CanViewInventory,
    session: DbSession,
) -> InventoryItemResponse:
    item = await InventoryService(session).get_item(item_id, current_user)
    return InventoryItemResponse.model_validate(item)


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


@router.get("/movements", response_model=list[MovementResponse])
async def list_movements(
    _: CanViewInventory,
    session: DbSession,
    item_id: Annotated[UUID | None, Query()] = None,
    location_id: Annotated[UUID | None, Query()] = None,
    project_id: Annotated[UUID | None, Query()] = None,
) -> list[MovementResponse]:
    movements = await InventoryService(session).list_movements(
        item_id=item_id,
        location_id=location_id,
        project_id=project_id,
    )
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


@router.get("/requests", response_model=list[MaterialRequestResponse])
async def list_material_requests(
    _: CurrentUser,
    session: DbSession,
) -> list[MaterialRequestResponse]:
    requests = await InventoryService(session).list_material_requests()
    return [MaterialRequestResponse.model_validate(request) for request in requests]


@router.post(
    "/requests", response_model=MaterialRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_material_request(
    payload: MaterialRequestCreateRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).create_material_request(payload, current_user)
    return MaterialRequestResponse.model_validate(request)


@router.post("/requests/{request_id}/reserve", response_model=MaterialRequestResponse)
async def reserve_material_request(
    request_id: UUID,
    current_user: CanManageInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).reserve_request(request_id, current_user)
    return MaterialRequestResponse.model_validate(request)


@router.post("/requests/{request_id}/issue", response_model=MaterialRequestResponse)
async def issue_material_request(
    request_id: UUID,
    current_user: CanManageInventory,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).issue_request(request_id, current_user)
    return MaterialRequestResponse.model_validate(request)


@router.post("/requests/{request_id}/cancel", response_model=MaterialRequestResponse)
async def cancel_material_request(
    request_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> MaterialRequestResponse:
    request = await InventoryService(session).cancel_request(request_id, current_user)
    return MaterialRequestResponse.model_validate(request)
