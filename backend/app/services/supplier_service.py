from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.suppliers import SupplierCreateRequest, SupplierUpdateRequest
from app.services.audit_service import AuditService
from app.utils.exceptions import NotFoundException
from app.utils.security import utc_now


class SupplierService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def create_supplier(self, payload: SupplierCreateRequest, actor: User) -> Supplier:
        supplier = Supplier(**payload.model_dump())
        self.session.add(supplier)
        await self.session.flush()
        await self.audit.record(
            action="suppliers.created",
            user_id=actor.id,
            entity_type="suppliers",
            entity_id=supplier.id,
            new_values=payload.model_dump(mode="json"),
        )
        await self.session.commit()
        return supplier

    async def list_suppliers(
        self,
        *,
        active: bool | None,
        compliance_status: str | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Supplier], int]:
        query: Select[tuple[Supplier]] = select(Supplier).where(Supplier.deleted_at.is_(None))
        if active is not None:
            query = query.where(Supplier.is_active.is_(active))
        if compliance_status:
            query = query.where(Supplier.compliance_status == compliance_status)
        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(Supplier.name).like(pattern),
                    func.lower(Supplier.category).like(pattern),
                    func.lower(Supplier.tax_registration_number).like(pattern),
                )
            )
        total_query = select(func.count()).select_from(
            query.with_only_columns(Supplier.id).subquery()
        )
        suppliers = list(
            (
                await self.session.scalars(
                    query.order_by(Supplier.name.asc()).limit(limit).offset(offset)
                )
            ).all()
        )
        total = int(await self.session.scalar(total_query) or 0)
        return suppliers, total

    async def update_supplier(
        self,
        supplier_id: UUID,
        payload: SupplierUpdateRequest,
        actor: User,
    ) -> Supplier:
        supplier = await self.get_supplier(supplier_id)
        updates = payload.model_dump(exclude_unset=True)
        old_values = {key: getattr(supplier, key) for key in updates}
        for key, value in updates.items():
            setattr(supplier, key, value)
        await self.audit.record(
            action="suppliers.updated",
            user_id=actor.id,
            entity_type="suppliers",
            entity_id=supplier.id,
            old_values={
                key: str(value) if value is not None else None for key, value in old_values.items()
            },
            new_values=payload.model_dump(mode="json", exclude_unset=True),
        )
        await self.session.commit()
        return supplier

    async def deactivate_supplier(self, supplier_id: UUID, actor: User) -> Supplier:
        supplier = await self.get_supplier(supplier_id)
        supplier.is_active = False
        supplier.deleted_at = utc_now()
        await self.audit.record(
            action="suppliers.deactivated",
            user_id=actor.id,
            entity_type="suppliers",
            entity_id=supplier.id,
        )
        await self.session.commit()
        return supplier

    async def get_supplier(self, supplier_id: UUID) -> Supplier:
        supplier = await self.session.scalar(
            select(Supplier).where(Supplier.id == supplier_id, Supplier.deleted_at.is_(None))
        )
        if not supplier:
            raise NotFoundException("Supplier")
        return supplier

    async def get_active_supplier(self, supplier_id: UUID) -> Supplier:
        supplier = await self.session.scalar(
            select(Supplier).where(
                Supplier.id == supplier_id,
                Supplier.is_active.is_(True),
                Supplier.deleted_at.is_(None),
            )
        )
        if not supplier:
            raise NotFoundException("Active supplier")
        return supplier
