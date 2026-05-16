from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.inventory import (
    InventoryAsset,
    InventoryItem,
    InventoryLocationStock,
    InventoryMovement,
    MaterialRequest,
    MaterialRequestLine,
    StorageLocation,
)
from app.models.user import User
from app.schemas.approvals import ApprovalCreateRequest
from app.schemas.inventory import (
    AssetCreateRequest,
    InventoryItemCreateRequest,
    LocationCreateRequest,
    MaterialRequestCreateRequest,
    MovementCreateRequest,
)
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.supplier_service import SupplierService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
)

PRICE_VISIBLE_ROLES = {ROLE_ADMIN, ROLE_GENERAL_MANAGER, ROLE_OPERATION_MANAGER, ROLE_ACCOUNTS}
STOCK_OUT_TYPES = {"issue", "consume", "wastage", "damaged"}


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    async def create_location(self, payload: LocationCreateRequest, actor: User) -> StorageLocation:
        location = StorageLocation(**payload.model_dump())
        self.session.add(location)
        await self.session.flush()
        await self.audit.record(
            action="inventory.locations.created",
            user_id=actor.id,
            entity_type="storage_locations",
            entity_id=location.id,
            new_values=payload.model_dump(mode="json"),
        )
        await self.session.commit()
        return location

    async def list_locations(self) -> list[StorageLocation]:
        return list(
            (
                await self.session.scalars(
                    select(StorageLocation)
                    .where(StorageLocation.deleted_at.is_(None))
                    .order_by(StorageLocation.name.asc())
                )
            ).all()
        )

    async def create_item(self, payload: InventoryItemCreateRequest, actor: User) -> InventoryItem:
        if payload.item_type == "asset" and not payload.item_code:
            raise AppException(
                "Material code is required for tools and asset-tagged items.",
                status_code=422,
                error_code="ITEM_CODE_REQUIRED",
            )
        await SupplierService(self.session).get_active_supplier(payload.supplier_id)
        item = InventoryItem(**payload.model_dump())
        self.session.add(item)
        await self.session.flush()
        await self.audit.record(
            action="inventory.items.created",
            user_id=actor.id,
            entity_type="inventory_items",
            entity_id=item.id,
            new_values=payload.model_dump(mode="json"),
        )
        await self.session.commit()
        return item

    async def list_items(self, actor: User, search: str | None = None) -> list[InventoryItem]:
        query: Select[tuple[InventoryItem]] = select(InventoryItem).where(
            InventoryItem.deleted_at.is_(None)
        )
        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(InventoryItem.name).like(pattern),
                    func.lower(InventoryItem.item_code).like(pattern),
                    func.lower(InventoryItem.category).like(pattern),
                )
            )
        items = list((await self.session.scalars(query.order_by(InventoryItem.name.asc()))).all())
        if actor.role not in PRICE_VISIBLE_ROLES:
            for item in items:
                item.unit_cost = None
        return items

    async def get_item(self, item_id: UUID, actor: User) -> InventoryItem:
        item = await self.session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == item_id, InventoryItem.deleted_at.is_(None)
            )
        )
        if not item:
            raise NotFoundException("Inventory item")
        if actor.role not in PRICE_VISIBLE_ROLES:
            item.unit_cost = None
        return item

    async def list_stock(self, item_id: UUID) -> list[InventoryLocationStock]:
        return list(
            (
                await self.session.scalars(
                    select(InventoryLocationStock)
                    .where(
                        InventoryLocationStock.item_id == item_id,
                        InventoryLocationStock.deleted_at.is_(None),
                    )
                    .order_by(InventoryLocationStock.created_at.asc())
                )
            ).all()
        )

    async def create_asset(self, payload: AssetCreateRequest, actor: User) -> InventoryAsset:
        item = await self._get_item(payload.item_id)
        if item.item_type != "asset":
            raise AppException(
                "Assets can only be created for asset-tagged inventory items.",
                status_code=422,
                error_code="ITEM_NOT_ASSET",
            )
        asset = InventoryAsset(**payload.model_dump())
        self.session.add(asset)
        await self._apply_movement(
            MovementCreateRequest(
                item_id=payload.item_id,
                asset_id=None,
                movement_type="receive",
                quantity=Decimal("1"),
                to_location_id=payload.current_location_id,
                notes=f"Asset {payload.asset_tag} registered",
            ),
            actor,
        )
        await self.session.flush()
        await self.session.commit()
        return asset

    async def list_assets(self) -> list[InventoryAsset]:
        return list(
            (
                await self.session.scalars(
                    select(InventoryAsset)
                    .where(InventoryAsset.deleted_at.is_(None))
                    .order_by(InventoryAsset.asset_tag.asc())
                )
            ).all()
        )

    async def create_movement(
        self, payload: MovementCreateRequest, actor: User
    ) -> InventoryMovement:
        movement = await self._apply_movement(payload, actor)
        await self.audit.record(
            action=f"inventory.movements.{payload.movement_type}",
            user_id=actor.id,
            entity_type="inventory_items",
            entity_id=payload.item_id,
            new_values=payload.model_dump(mode="json"),
        )
        await self.session.commit()
        return movement

    async def list_movements(
        self,
        *,
        item_id: UUID | None = None,
        location_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> list[InventoryMovement]:
        query: Select[tuple[InventoryMovement]] = select(InventoryMovement).where(
            InventoryMovement.deleted_at.is_(None)
        )
        if item_id:
            query = query.where(InventoryMovement.item_id == item_id)
        if project_id:
            query = query.where(InventoryMovement.project_id == project_id)
        if location_id:
            query = query.where(
                or_(
                    InventoryMovement.from_location_id == location_id,
                    InventoryMovement.to_location_id == location_id,
                )
            )
        return list(
            (await self.session.scalars(query.order_by(InventoryMovement.created_at.desc()))).all()
        )

    async def low_stock(self) -> list[InventoryLocationStock]:
        return list(
            (
                await self.session.scalars(
                    select(InventoryLocationStock)
                    .join(InventoryItem, InventoryItem.id == InventoryLocationStock.item_id)
                    .where(
                        InventoryLocationStock.deleted_at.is_(None),
                        InventoryItem.deleted_at.is_(None),
                        InventoryItem.reorder_level > 0,
                        InventoryLocationStock.on_hand_qty <= InventoryItem.reorder_level,
                    )
                    .order_by(InventoryItem.name.asc())
                )
            ).all()
        )

    async def create_material_request(
        self,
        payload: MaterialRequestCreateRequest,
        actor: User,
    ) -> MaterialRequest:
        sequence = int(
            await self.session.scalar(select(func.count()).select_from(MaterialRequest)) or 0
        )
        request = MaterialRequest(
            request_number=f"MR-{sequence + 1:05d}",
            project_id=payload.project_id,
            requester_id=actor.id,
            from_location_id=payload.from_location_id,
            status="requested",
            notes=payload.notes,
            total_estimated_cost=Decimal("0"),
        )
        total = Decimal("0")
        self.session.add(request)
        await self.session.flush()
        for line_payload in payload.lines:
            item = await self._get_item(line_payload.item_id)
            line_cost = (item.unit_cost or Decimal("0")) * line_payload.quantity
            total += line_cost
            self.session.add(
                MaterialRequestLine(
                    request_id=request.id,
                    item_id=item.id,
                    quantity=line_payload.quantity,
                    unit_cost=item.unit_cost,
                )
            )
        request.total_estimated_cost = total
        await self.session.flush()
        await ApprovalService(self.session).create_approval(
            ApprovalCreateRequest(
                request_type="material_request",
                request_id=request.id,
                project_id=request.project_id,
                title=request.request_number,
                amount=total,
                currency="USD",
                comments=payload.notes,
            ),
            actor,
        )
        return await self._get_material_request(request.id)

    async def list_material_requests(self) -> list[MaterialRequest]:
        return list(
            (
                await self.session.scalars(
                    select(MaterialRequest)
                    .where(MaterialRequest.deleted_at.is_(None))
                    .order_by(MaterialRequest.created_at.desc())
                )
            ).all()
        )

    async def reserve_request(self, request_id: UUID, actor: User) -> MaterialRequest:
        request = await self._get_material_request(request_id)
        if request.status not in {"requested", "approved"}:
            raise AppException(
                "Only requested or approved material requests can be reserved.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        for line in request.lines:
            remaining = line.quantity - line.reserved_quantity
            if remaining <= 0:
                continue
            await self._reserve_stock(line.item_id, request.from_location_id, remaining)
            line.reserved_quantity += remaining
            self.session.add(
                InventoryMovement(
                    item_id=line.item_id,
                    movement_type="reserve",
                    quantity=remaining,
                    from_location_id=request.from_location_id,
                    project_id=request.project_id,
                    reference_type="material_request",
                    reference_id=request.id,
                    handled_by=actor.id,
                )
            )
        request.status = "reserved"
        await self.session.commit()
        return request

    async def issue_request(self, request_id: UUID, actor: User) -> MaterialRequest:
        request = await self._get_material_request(request_id)
        if request.status not in {"reserved", "partially_issued"}:
            raise AppException(
                "Only reserved material requests can be issued.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        fully_issued = True
        for line in request.lines:
            remaining = line.quantity - line.issued_quantity
            if remaining <= 0:
                continue
            stock = await self._get_stock(line.item_id, request.from_location_id)
            if stock.reserved_qty < remaining:
                fully_issued = False
                continue
            stock.reserved_qty -= remaining
            stock.on_hand_qty -= remaining
            line.issued_quantity += remaining
            self.session.add(
                InventoryMovement(
                    item_id=line.item_id,
                    movement_type="issue",
                    quantity=remaining,
                    from_location_id=request.from_location_id,
                    project_id=request.project_id,
                    reference_type="material_request",
                    reference_id=request.id,
                    handled_by=actor.id,
                )
            )
        request.status = "issued" if fully_issued else "partially_issued"
        await self.session.commit()
        return request

    async def cancel_request(self, request_id: UUID, actor: User) -> MaterialRequest:
        request = await self._get_material_request(request_id)
        if request.status in {"issued", "cancelled"}:
            raise AppException(
                "Material request cannot be cancelled.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        for line in request.lines:
            if line.reserved_quantity > 0:
                stock = await self._get_stock(line.item_id, request.from_location_id)
                stock.reserved_qty -= line.reserved_quantity
                line.reserved_quantity = Decimal("0")
        request.status = "cancelled"
        await self.audit.record(
            action="inventory.requests.cancelled",
            user_id=actor.id,
            entity_type="material_requests",
            entity_id=request.id,
        )
        await self.session.commit()
        return request

    async def _apply_movement(
        self,
        payload: MovementCreateRequest,
        actor: User,
    ) -> InventoryMovement:
        await self._get_item(payload.item_id)
        if payload.movement_type == "receive":
            if not payload.to_location_id:
                raise AppException("Receive requires destination.", status_code=422)
            stock = await self._get_or_create_stock(payload.item_id, payload.to_location_id)
            stock.on_hand_qty += payload.quantity
        elif payload.movement_type == "transfer":
            if not payload.from_location_id or not payload.to_location_id:
                raise AppException("Transfer requires source and destination.", status_code=422)
            await self._decrease_available(
                payload.item_id, payload.from_location_id, payload.quantity
            )
            destination = await self._get_or_create_stock(payload.item_id, payload.to_location_id)
            destination.on_hand_qty += payload.quantity
            await self._move_asset(payload)
        elif payload.movement_type == "return":
            if not payload.to_location_id:
                raise AppException("Return requires destination.", status_code=422)
            stock = await self._get_or_create_stock(payload.item_id, payload.to_location_id)
            stock.on_hand_qty += payload.quantity
        elif payload.movement_type in STOCK_OUT_TYPES:
            if not payload.from_location_id:
                raise AppException("Outgoing movement requires source.", status_code=422)
            await self._decrease_available(
                payload.item_id, payload.from_location_id, payload.quantity
            )
        elif payload.movement_type == "adjustment":
            if not payload.to_location_id:
                raise AppException("Adjustment requires target location.", status_code=422)
            stock = await self._get_or_create_stock(payload.item_id, payload.to_location_id)
            stock.on_hand_qty += payload.quantity
        elif payload.movement_type == "reserve":
            if not payload.from_location_id:
                raise AppException("Reservation requires source.", status_code=422)
            await self._reserve_stock(payload.item_id, payload.from_location_id, payload.quantity)

        movement = InventoryMovement(**payload.model_dump(), handled_by=actor.id)
        self.session.add(movement)
        await self.session.flush()
        return movement

    async def _move_asset(self, payload: MovementCreateRequest) -> None:
        if not payload.asset_id or not payload.to_location_id:
            return
        asset = await self.session.scalar(
            select(InventoryAsset).where(
                InventoryAsset.id == payload.asset_id,
                InventoryAsset.deleted_at.is_(None),
            )
        )
        if asset:
            asset.current_location_id = payload.to_location_id

    async def _decrease_available(
        self, item_id: UUID, location_id: UUID, quantity: Decimal
    ) -> None:
        stock = await self._get_stock(item_id, location_id)
        available = stock.on_hand_qty - stock.reserved_qty
        if available < quantity:
            raise AppException(
                f"Insufficient stock. Available quantity is {available}.",
                status_code=409,
                error_code="INSUFFICIENT_STOCK",
            )
        stock.on_hand_qty -= quantity

    async def _reserve_stock(
        self, item_id: UUID, location_id: UUID | None, quantity: Decimal
    ) -> None:
        if not location_id:
            raise AppException("Reservation requires source location.", status_code=422)
        stock = await self._get_stock(item_id, location_id)
        available = stock.on_hand_qty - stock.reserved_qty
        if available < quantity:
            raise AppException(
                f"Insufficient stock. Available quantity is {available}.",
                status_code=409,
                error_code="INSUFFICIENT_STOCK",
            )
        stock.reserved_qty += quantity

    async def _get_stock(self, item_id: UUID, location_id: UUID | None) -> InventoryLocationStock:
        if not location_id:
            raise AppException("Location is required.", status_code=422)
        stock = await self.session.scalar(
            select(InventoryLocationStock).where(
                InventoryLocationStock.item_id == item_id,
                InventoryLocationStock.location_id == location_id,
                InventoryLocationStock.deleted_at.is_(None),
            )
        )
        if not stock:
            raise AppException("Stock is not available at this location.", status_code=409)
        return stock

    async def _get_or_create_stock(
        self,
        item_id: UUID,
        location_id: UUID,
    ) -> InventoryLocationStock:
        stock = await self.session.scalar(
            select(InventoryLocationStock).where(
                InventoryLocationStock.item_id == item_id,
                InventoryLocationStock.location_id == location_id,
                InventoryLocationStock.deleted_at.is_(None),
            )
        )
        if stock:
            return stock
        stock = InventoryLocationStock(item_id=item_id, location_id=location_id)
        self.session.add(stock)
        await self.session.flush()
        return stock

    async def _get_item(self, item_id: UUID) -> InventoryItem:
        item = await self.session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == item_id, InventoryItem.deleted_at.is_(None)
            )
        )
        if not item:
            raise NotFoundException("Inventory item")
        return item

    async def _get_material_request(self, request_id: UUID) -> MaterialRequest:
        request = await self.session.scalar(
            select(MaterialRequest)
            .where(
                MaterialRequest.id == request_id,
                MaterialRequest.deleted_at.is_(None),
            )
            .options(selectinload(MaterialRequest.lines))
        )
        if not request:
            raise NotFoundException("Material request")
        return request
