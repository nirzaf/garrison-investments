from decimal import Decimal
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import Select, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.business_policy import MAX_MONEY
from app.models.approval import Approval
from app.models.daily_report import DailyReport
from app.models.idempotency_record import IdempotencyRecord
from app.models.inventory import (
    InventoryAsset,
    InventoryItem,
    InventoryLocationStock,
    InventoryMovement,
    InventoryRegistration,
    MaterialRequest,
    MaterialRequestLine,
    MaterialRequestSubmission,
    StorageLocation,
)
from app.models.notification import Notification
from app.models.photo import Photo
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.schemas.approvals import ApprovalCreateRequest
from app.schemas.inventory import (
    AssetCreateRequest,
    InventoryItemCreateRequest,
    LocationCreateRequest,
    MaterialDraftSave,
    MaterialQuantityCommand,
    MaterialRequestDraftCreate,
    MaterialRequestReplacementRequest,
    MaterialRequestResponse,
    MaterialRequestResubmitRequest,
    MaterialRequestSubmitRequest,
    MovementCreateRequest,
)
from app.services.approval_service import (
    MATERIAL_STAGE_ROLES,
    ApprovalService,
    frozen_material_stages,
)
from app.services.audit_service import AuditService
from app.services.authorization import accessible_project_ids, ensure_project_access
from app.services.document_service import DocumentService
from app.services.idempotency import bind, resolve_or_reserve
from app.services.notification_service import NotificationService
from app.services.supplier_service import SupplierService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_INVENTORY_VIEW,
    PROJECT_OPERATIONAL_MANAGER_ROLES,
    ROLE_ADMINISTRATIVE_EXECUTIVE,
    SUPERVISOR_ROLES,
    ensure_permission,
    has_permission,
    roles_with_permission,
)
from app.utils.security import utc_now

STOCK_OUT_TYPES = {"issue", "consume", "wastage", "damaged"}
MOVEMENT_IDEMPOTENCY_ROUTE = "inventory.movements.create"


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    async def create_location(self, payload: LocationCreateRequest, actor: User) -> StorageLocation:
        ensure_permission(actor, PERMISSION_INVENTORY_MANAGE)
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

    async def list_locations(self, actor: User) -> list[StorageLocation]:
        query = select(StorageLocation).where(StorageLocation.deleted_at.is_(None))
        project_ids = await self._inventory_project_scope(actor)
        if project_ids is not None:
            if not project_ids:
                return []
            query = query.where(StorageLocation.project_id.in_(project_ids))
        return list((await self.session.scalars(query.order_by(StorageLocation.name.asc()))).all())

    async def create_item(self, payload: InventoryItemCreateRequest, actor: User) -> InventoryItem:
        ensure_permission(actor, PERMISSION_INVENTORY_MANAGE)
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

    async def list_items(self, search: str | None = None) -> list[InventoryItem]:
        items, _ = await self.list_item_page(search)
        return items

    async def list_item_page(
        self, search: str | None = None, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[InventoryItem], int]:
        """Return items with their persisted prices intact.

        Price masking is a presentation concern handled by the API layer; mutating
        ``unit_cost`` here would write NULL prices on the next commit in this session.
        """
        query: Select[InventoryItem] = select(InventoryItem).where(
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
        return await self._list_page(
            query.order_by(InventoryItem.name.asc(), InventoryItem.id.asc()), limit, offset
        )

    async def get_item(self, item_id: UUID) -> InventoryItem:
        item = await self.session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == item_id, InventoryItem.deleted_at.is_(None)
            )
        )
        if not item:
            raise NotFoundException("Inventory item")
        return item

    async def list_stock(self, item_id: UUID, actor: User) -> list[InventoryLocationStock]:
        query = (
            select(InventoryLocationStock)
            .join(StorageLocation, StorageLocation.id == InventoryLocationStock.location_id)
            .where(
                InventoryLocationStock.item_id == item_id,
                InventoryLocationStock.deleted_at.is_(None),
                StorageLocation.deleted_at.is_(None),
            )
        )
        project_ids = await self._inventory_project_scope(actor)
        if project_ids is not None:
            if not project_ids:
                return []
            query = query.where(StorageLocation.project_id.in_(project_ids))
        return list(
            (
                await self.session.scalars(query.order_by(InventoryLocationStock.created_at.asc()))
            ).all()
        )

    async def create_asset(self, payload: AssetCreateRequest, actor: User) -> InventoryAsset:
        ensure_permission(actor, PERMISSION_INVENTORY_MANAGE)
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

    async def list_assets(self, actor: User) -> list[InventoryAsset]:
        query = (
            select(InventoryAsset)
            .join(StorageLocation, StorageLocation.id == InventoryAsset.current_location_id)
            .where(
                InventoryAsset.deleted_at.is_(None),
                StorageLocation.deleted_at.is_(None),
            )
        )
        project_ids = await self._inventory_project_scope(actor)
        if project_ids is not None:
            if not project_ids:
                return []
            query = query.where(StorageLocation.project_id.in_(project_ids))
        return list(
            (await self.session.scalars(query.order_by(InventoryAsset.asset_tag.asc()))).all()
        )

    async def create_movement(
        self,
        payload: MovementCreateRequest,
        actor: User,
        *,
        commit: bool = True,
        import_row: tuple[UUID, int] | None = None,
        idempotency_key: str | None = None,
    ) -> InventoryMovement:
        ensure_permission(actor, PERMISSION_INVENTORY_MANAGE)
        return await self._create_movement(
            payload,
            actor,
            commit=commit,
            import_row=import_row,
            idempotency_key=idempotency_key,
        )

    async def _create_movement(
        self,
        payload: MovementCreateRequest,
        actor: User,
        *,
        commit: bool,
        import_row: tuple[UUID, int] | None = None,
        idempotency_key: str | None = None,
    ) -> InventoryMovement:
        """Apply a movement after its caller has established the authorization boundary.

        Public inventory commands use :meth:`create_movement`, which requires
        ``inventory:manage``. The approved-report workflow is the only internal
        caller that uses this helper directly; its report approval authorization
        permits the bounded automatic material consumption side effect.
        """
        if idempotency_key is not None:
            recorded_id = await resolve_or_reserve(
                self.session,
                key=idempotency_key,
                user_id=actor.id,
                route=MOVEMENT_IDEMPOTENCY_ROUTE,
            )
            if recorded_id is not None:
                recorded = await self.session.get(InventoryMovement, recorded_id)
                if recorded is None or any(
                    getattr(recorded, field) != value
                    for field, value in payload.model_dump().items()
                ):
                    raise AppException(
                        "This movement key was already used for a different stock movement.",
                        status_code=409,
                        error_code="MOVEMENT_REPLAY_CONFLICT",
                    )
                return recorded
        movement = await self._apply_movement(payload, actor, import_row=import_row)
        await self.audit.record(
            action=f"inventory.movements.{payload.movement_type}",
            user_id=actor.id,
            entity_type="inventory_items",
            entity_id=payload.item_id,
            new_values=payload.model_dump(mode="json"),
        )
        await self._notify_low_stock_for_movement(payload)
        if idempotency_key is not None:
            await bind(
                self.session,
                key=idempotency_key,
                user_id=actor.id,
                route=MOVEMENT_IDEMPOTENCY_ROUTE,
                resource_type="inventory_movement",
                resource_id=movement.id,
            )
            await self.session.refresh(movement)
        if commit:
            await self.session.commit()
        return movement

    async def consume_daily_report_materials(
        self,
        report: DailyReport,
        actor: User,
    ) -> int:
        consumed = 0
        for line in report.material_consumption:
            item: InventoryItem | None = None
            stock: InventoryLocationStock | None = None
            for candidate in await self._find_consumption_items(line.material_name):
                candidate_stock = await self._find_consumption_stock(
                    item_id=candidate.id,
                    project_id=report.project_id,
                    quantity=line.quantity,
                )
                if candidate_stock:
                    item = candidate
                    stock = candidate_stock
                    break
            if not stock:
                continue
            if not item:
                continue
            await self._create_movement(
                MovementCreateRequest(
                    item_id=item.id,
                    movement_type="consume",
                    quantity=line.quantity,
                    from_location_id=stock.location_id,
                    project_id=report.project_id,
                    reference_type="daily_report",
                    reference_id=report.id,
                    notes=f"Daily report consumption: {report.report_number or report.id}",
                ),
                actor,
                commit=False,
            )
            consumed += 1
        if consumed:
            await self.audit.record(
                action="inventory.daily_report_consumption_applied",
                user_id=actor.id,
                entity_type="daily_reports",
                entity_id=report.id,
                new_values={"lines_consumed": consumed},
            )
        return consumed

    async def list_movements(
        self,
        *,
        actor: User,
        item_id: UUID | None = None,
        location_id: UUID | None = None,
        project_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[InventoryMovement], int]:
        query: Select[InventoryMovement] = select(InventoryMovement).where(
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
        project_ids = await self._inventory_project_scope(actor)
        if project_ids is not None:
            if not project_ids:
                return [], 0
            query = query.where(InventoryMovement.project_id.in_(project_ids))
        return await self._list_page(
            query.order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc()),
            limit,
            offset,
        )

    async def low_stock(self, actor: User | None = None) -> list[InventoryLocationStock]:
        query = (
            select(InventoryLocationStock)
            .join(InventoryItem, InventoryItem.id == InventoryLocationStock.item_id)
            .join(StorageLocation, StorageLocation.id == InventoryLocationStock.location_id)
            .where(
                InventoryLocationStock.deleted_at.is_(None),
                InventoryItem.deleted_at.is_(None),
                StorageLocation.deleted_at.is_(None),
                InventoryItem.reorder_level > 0,
                InventoryLocationStock.on_hand_qty <= InventoryItem.reorder_level,
            )
        )
        if actor is not None:
            project_ids = await self._inventory_project_scope(actor)
            if project_ids is not None:
                if not project_ids:
                    return []
                query = query.where(StorageLocation.project_id.in_(project_ids))
        return list((await self.session.scalars(query.order_by(InventoryItem.name.asc()))).all())

    async def create_material_draft(
        self, payload: MaterialRequestDraftCreate, actor: User
    ) -> MaterialRequest:
        project_id = payload.project_id
        if actor.role not in SUPERVISOR_ROLES:
            raise PermissionDeniedException("create material evidence drafts")
        self._ensure_material_submitter(actor)
        projects = await self._request_projects_query(actor)
        if await self.session.scalar(projects.where(Project.id == project_id)) is None:
            raise NotFoundException("Eligible request project")
        if payload.correction_target_id is not None:
            original = await self._get_material_request(payload.correction_target_id)
            if original.project_id != project_id or original.requester_id != actor.id:
                raise NotFoundException("Material request")
            self._check_material_draft_revision(original, payload.correction_expected_revision)
            if original.status not in {"requested", "approved", "returned", "rejected"}:
                raise AppException(
                    "This request is no longer eligible for correction.",
                    status_code=409,
                    error_code="REQUEST_STATUS_INVALID",
                )
        draft = await self._new_material_request(project_id, actor)
        draft.status = "draft"
        draft.correction_target_id = payload.correction_target_id
        draft.correction_expected_revision = payload.correction_expected_revision
        self.session.add(draft)
        await self.session.flush()
        await self.audit.record(
            action="inventory.requests.drafted",
            user_id=actor.id,
            entity_type="material_requests",
            entity_id=draft.id,
        )
        await self.session.commit()
        return draft

    @staticmethod
    def _check_material_draft_revision(request: MaterialRequest, expected: int | None) -> None:
        if request.revision != expected:
            raise AppException(
                "Refresh the request before editing it.",
                status_code=409,
                error_code="REQUEST_REVISION_CONFLICT",
            )

    async def _editable_material_draft(self, draft_id: UUID, actor: User) -> MaterialRequest:
        self._ensure_material_submitter(actor)
        draft = await self._get_material_request(draft_id, for_update=True, lock_lines=False)
        if draft.status != "draft" or draft.requester_id != actor.id:
            raise NotFoundException("Material request draft")
        await ensure_project_access(self.session, draft.project_id, actor)
        return draft

    async def save_material_draft(
        self, draft_id: UUID, payload: MaterialDraftSave, actor: User
    ) -> MaterialRequest:
        draft = await self._editable_material_draft(draft_id, actor)
        self._check_material_draft_revision(draft, payload.expected_revision)
        await self._supporting_document_versions(
            payload.payload.supporting_document_ids, draft.project_id, actor
        )
        draft.draft_payload = payload.payload.model_dump(mode="json")
        draft.revision += 1
        await self.session.commit()
        return draft

    async def submit_material_correction_draft(
        self, draft_id: UUID, payload: MaterialRequestResubmitRequest, actor: User
    ) -> MaterialRequest:
        draft = await self._editable_material_draft(draft_id, actor)
        self._check_material_draft_revision(draft, payload.expected_revision)
        if draft.correction_target_id is None or draft.correction_expected_revision is None:
            raise NotFoundException("Material correction draft")
        return await self.resubmit_material_request(
            draft.correction_target_id,
            payload.model_copy(update={"expected_revision": draft.correction_expected_revision}),
            actor,
            correction_draft=draft,
        )

    async def create_material_request(
        self, payload: MaterialRequestSubmitRequest, actor: User
    ) -> MaterialRequest:
        self._ensure_material_submitter(actor)
        request = await self._new_material_request(payload.project_id, actor)
        return await self._submit_material_requirements(request, payload, actor)

    async def _new_material_request(self, project_id: UUID, actor: User) -> MaterialRequest:
        sequence = int(
            await self.session.scalar(text("select nextval('material_request_number_seq')"))
        )
        return MaterialRequest(
            request_number=f"MR-{sequence:05d}",
            project_id=project_id,
            requester_id=actor.id,
            total_estimated_cost=None,
            lines=[],
        )

    async def resubmit_material_request(
        self,
        request_id: UUID,
        payload: MaterialRequestResubmitRequest,
        actor: User,
        *,
        correction_draft: MaterialRequest | None = None,
    ) -> MaterialRequest:
        self._ensure_material_submitter(actor)
        request = await self._get_material_request(request_id, for_update=True, lock_lines=False)
        await ensure_project_access(self.session, request.project_id, actor)
        if request.requester_id != actor.id and actor.role not in COMPANY_RESOURCE_ROLES:
            raise NotFoundException("Material request")
        if request.correction_target_id is not None:
            raise AppException(
                "Submit the correction draft through its correction endpoint.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        if request.project_id != payload.project_id:
            raise AppException(
                "A corrected request must remain on its original project.",
                status_code=422,
                error_code="REQUEST_PROJECT_INVALID",
            )
        if request.revision != payload.expected_revision:
            raise AppException(
                "Refresh the request before correcting it.",
                status_code=409,
                error_code="REQUEST_REVISION_CONFLICT",
            )
        legacy_open = request.submission_revision is None and request.status in {
            "requested",
            "approved",
        }
        own_draft = (
            request.status == "draft"
            and request.requester_id == actor.id
            and actor.role in SUPERVISOR_ROLES
        )
        approved = request.submission_revision is not None and request.status == "approved"
        if approved and not (payload.reason or "").strip():
            raise AppException("A correction reason is required.", status_code=422)
        if (
            not legacy_open
            and not own_draft
            and not approved
            and request.status not in {"returned", "rejected"}
        ):
            raise AppException(
                "Only returned or rejected requests may be corrected.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        await ApprovalService(self.session).cancel_material_request_approvals(request.id, actor)
        await self._lock_request_lines(request.id)
        if any(line.reserved_quantity or line.issued_quantity for line in request.lines):
            raise AppException(
                "A request with stock reservations or issues cannot be amended.",
                status_code=409,
                error_code="REQUEST_HAS_STOCK_ACTIVITY",
            )
        if approved:
            await self.audit.record(
                action="inventory.requests.corrected",
                user_id=actor.id,
                entity_type="material_requests",
                entity_id=request.id,
                comments=(payload.reason or "").strip(),
            )
        for line in request.lines:
            line.deleted_at = utc_now()
        request.revision += 1
        request.requester_id = actor.id
        return await self._submit_material_requirements(
            request, payload, actor, correction_draft=correction_draft
        )

    async def replace_material_remainder(
        self, request_id: UUID, payload: MaterialRequestReplacementRequest, actor: User
    ) -> MaterialRequest:
        ensure_permission(actor, PERMISSION_INVENTORY_MANAGE)
        original = await self._get_material_request(request_id, for_update=True, lock_lines=False)
        reason = payload.reason.strip()
        if not reason or original.project_id != payload.project_id:
            raise AppException("Give a reason and retain the original project.", status_code=422)
        if original.revision != payload.expected_revision:
            raise AppException("Refresh the request before replacing it.", status_code=409)
        if original.status not in {
            "approved",
            "reserved",
            "partially_reserved",
            "partially_issued",
        }:
            raise AppException("This request cannot be replaced.", status_code=409)
        await ApprovalService(self.session).cancel_material_request_approvals(original.id, actor)
        await self._lock_request_lines(original.id)
        if not any(line.reserved_quantity or line.issued_quantity for line in original.lines):
            raise AppException(
                "Use ordinary correction for a request without stock.", status_code=409
            )
        remaining = {line.item_id: line.quantity - line.issued_quantity for line in original.lines}
        if any(line.quantity > remaining.get(line.item_id, 0) for line in payload.lines):
            raise AppException(
                "Replacement exceeds the original unissued remainder.", status_code=422
            )
        await self._cancel_locked_request(original, actor)
        replacement = await self._new_material_request(original.project_id, actor)
        replacement.previous_id = original.id
        await self.audit.record(
            action="inventory.requests.replaced",
            user_id=actor.id,
            entity_type="material_requests",
            entity_id=original.id,
            comments=reason,
        )
        return await self._submit_material_requirements(replacement, payload, actor)

    @staticmethod
    def _ensure_material_submitter(actor: User) -> None:
        ensure_permission(actor, PERMISSION_INVENTORY_VIEW)
        if actor.role not in SUPERVISOR_ROLES | COMPANY_RESOURCE_ROLES:
            raise PermissionDeniedException("submit material requests")

    async def _supporting_document_versions(
        self, document_ids: list[UUID], project_id: UUID, actor: User
    ) -> dict[str, int]:
        versions = {}
        for document_id in document_ids:
            document = await DocumentService(self.session).get(document_id, actor)
            if document.project_id != project_id or document.active_version is None:
                raise NotFoundException("Project supporting document")
            versions[str(document.id)] = document.active_version
        return versions

    async def _submit_material_requirements(
        self,
        request: MaterialRequest,
        payload: MaterialRequestSubmitRequest,
        actor: User,
        *,
        correction_draft: MaterialRequest | None = None,
    ) -> MaterialRequest:
        projects = await self._request_projects_query(actor)
        project = await self.session.scalar(projects.where(Project.id == payload.project_id))
        if project is None:
            raise NotFoundException("Eligible request project")
        location = await self.session.scalar(
            select(StorageLocation).where(
                StorageLocation.id == payload.from_location_id,
                StorageLocation.deleted_at.is_(None),
                StorageLocation.is_active.is_(True),
                or_(StorageLocation.project_id.is_(None), StorageLocation.project_id == project.id),
            )
        )
        if location is None:
            raise NotFoundException("Eligible request source location")
        evidence_versions = await self._supporting_document_versions(
            payload.requirements.supporting_document_ids, project.id, actor
        )
        approvals = ApprovalService(self.session)
        engineer = await approvals.require_project_reviewer(
            project.id, MATERIAL_STAGE_ROLES[1], excluded_user_ids={actor.id}
        )
        manager = await approvals.require_project_reviewer(
            project.id, MATERIAL_STAGE_ROLES[2], excluded_user_ids={actor.id, engineer.id}
        )
        processor_id = await self.session.scalar(
            select(User.id)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(
                ProjectMember.project_id == project.id,
                ProjectMember.deleted_at.is_(None),
                User.role == ROLE_ADMINISTRATIVE_EXECUTIVE,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
            .order_by(ProjectMember.assigned_at, User.id)
            .limit(1)
        )
        submission_revision = (request.submission_revision or 0) + 1
        request.submission_revision = submission_revision
        request.from_location_id = location.id
        request.status = "pending_engineer"
        request.draft_payload = None
        request.notes = payload.notes
        request.total_estimated_cost = None
        self.session.add(request)
        await self.session.flush()
        total = Decimal("0")
        valuation_complete = True
        line_snapshots = []
        for line_payload in payload.lines:
            item = await self._get_item(line_payload.item_id)
            if not item.is_active:
                raise AppException(
                    "Select an active inventory item.", status_code=422, error_code="ITEM_INACTIVE"
                )
            if item.unit_cost is None:
                valuation_complete = False
            else:
                total += item.unit_cost * line_payload.quantity
            self.session.add(
                MaterialRequestLine(
                    request_id=request.id,
                    item_id=item.id,
                    quantity=line_payload.quantity,
                    unit_cost=item.unit_cost,
                )
            )
            line_snapshots.append(
                {
                    **line_payload.model_dump(mode="json"),
                    "name": item.name,
                    "unit": item.unit,
                }
            )
        if total > MAX_MONEY:
            raise AppException(
                "Material request total exceeds the allowed amount.",
                status_code=422,
                error_code="MATERIAL_REQUEST_AMOUNT_TOO_LARGE",
            )
        request.total_estimated_cost = total if valuation_complete else None
        snapshot = payload.model_dump(mode="json", exclude={"expected_revision", "reason"})
        snapshot["lines"] = line_snapshots
        snapshot["evidence_versions"] = evidence_versions
        snapshot["valuation_complete"] = valuation_complete
        evidence_owner_id = correction_draft.id if correction_draft else request.id
        snapshot["evidence_file_ids"] = [
            str(file_id)
            for file_id in await self.session.scalars(
                select(Photo.id)
                .where(
                    Photo.entity_type == "material_request",
                    Photo.entity_id == evidence_owner_id,
                    Photo.deleted_at.is_(None),
                )
                .order_by(Photo.id)
            )
        ]
        if correction_draft is not None:
            await self.session.execute(
                update(Photo)
                .where(
                    Photo.entity_type == "material_request",
                    Photo.entity_id == correction_draft.id,
                    Photo.deleted_at.is_(None),
                )
                .values(entity_id=request.id)
            )
            correction_draft.deleted_at = utc_now()
        submission = MaterialRequestSubmission(
            request_id=request.id,
            submission_revision=submission_revision,
            submitted_by=actor.id,
            engineer_id=engineer.id,
            manager_id=manager.id,
            processor_id=processor_id,
            requirements=snapshot,
        )
        self.session.add(submission)
        await self.session.flush()
        await approvals.create_approval(
            ApprovalCreateRequest(
                request_type="material_request",
                request_id=request.id,
                project_id=request.project_id,
                title=f"{request.request_number} · Technical verification",
                amount=total if valuation_complete else None,
                comments=payload.notes,
            ),
            actor,
            commit=False,
            internal=True,
            material_submission=submission,
        )
        await self.audit.record(
            action="inventory.requests.submitted",
            user_id=actor.id,
            entity_type="material_requests",
            entity_id=request.id,
            new_values={"submission_revision": submission_revision, "revision": request.revision},
        )
        request_id = request.id
        await self.session.commit()
        self.session.expire(request, ["lines"])
        return await self._get_material_request(request_id)

    async def material_submission_history(
        self, request_id: UUID, actor: User
    ) -> tuple[list[MaterialRequestSubmission], list[Approval]]:
        ensure_permission(actor, PERMISSION_INVENTORY_VIEW)
        request = await self._get_material_request(request_id)
        if request.status == "draft" and request.requester_id != actor.id:
            raise NotFoundException("Material request")
        await ensure_project_access(self.session, request.project_id, actor)
        submissions = await self.session.scalars(
            select(MaterialRequestSubmission)
            .where(MaterialRequestSubmission.request_id == request.id)
            .order_by(MaterialRequestSubmission.submission_revision.desc())
        )
        decisions = await self.session.scalars(
            select(Approval)
            .where(
                Approval.request_type == "material_request",
                Approval.request_id == request.id,
                Approval.submission_revision.is_not(None),
                Approval.deleted_at.is_(None),
            )
            .order_by(Approval.submission_revision.desc(), Approval.step_order.asc())
        )
        return list(submissions), list(decisions)

    async def _ensure_material_fulfillment(
        self, request: MaterialRequest, actor: User, *, check_decisions: bool = True
    ) -> None:
        if not has_permission(actor, PERMISSION_INVENTORY_MANAGE):
            if actor.role != ROLE_ADMINISTRATIVE_EXECUTIVE:
                raise PermissionDeniedException("fulfill material requests")
            await ApprovalService(self.session).require_project_reviewer(
                request.project_id,
                ROLE_ADMINISTRATIVE_EXECUTIVE,
                approver_id=actor.id,
                excluded_user_ids=set(),
            )
            processor = await self.session.scalar(
                select(MaterialRequestSubmission.processor_id).where(
                    MaterialRequestSubmission.request_id == request.id,
                    MaterialRequestSubmission.submission_revision == request.submission_revision,
                )
            )
            if processor != actor.id:
                raise PermissionDeniedException("fulfill this material request")
        if not check_decisions:
            return
        if request.submission_revision is not None:
            submission = await self.session.get(
                MaterialRequestSubmission, (request.id, request.submission_revision)
            )
            stages = frozen_material_stages(submission) if submission is not None else ()
            if submission is not None and stages:
                decisions = (
                    await self.session.execute(
                        select(Approval.step_order, Approval.decided_by).where(
                            Approval.request_type == "material_request",
                            Approval.request_id == request.id,
                            Approval.submission_revision == request.submission_revision,
                            Approval.step_order.in_(stages),
                            Approval.status == "approved",
                            Approval.deleted_at.is_(None),
                            Approval.decided_by.is_not(None),
                            Approval.decided_by != submission.submitted_by,
                        )
                    )
                ).all()
                if (
                    len(decisions) == len(stages)
                    and {stage for stage, _ in decisions} == set(stages)
                    and len({actor_id for _, actor_id in decisions}) == len(stages)
                ):
                    return
        raise AppException(
            "Every required approval of the current material submission must be recorded.",
            status_code=409,
            error_code="MATERIAL_APPROVALS_REQUIRED",
        )

    async def _request_projects_query(self, actor: User) -> Select[Project]:
        if not has_permission(actor, PERMISSION_INVENTORY_VIEW):
            raise AppException(
                "You cannot create material requests.",
                status_code=403,
                error_code="REQUEST_CREATE_FORBIDDEN",
            )
        query = select(Project).where(Project.deleted_at.is_(None), Project.status == "active")
        if actor.role not in COMPANY_RESOURCE_ROLES:
            ids = await accessible_project_ids(self.session, actor)
            if ids is not None:
                query = query.where(Project.id.in_(ids))
        return query

    async def list_request_projects(
        self,
        actor: User,
        *,
        search: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Project], int]:
        query = await self._request_projects_query(actor)
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            query = query.where(or_(Project.code.ilike(pattern), Project.name.ilike(pattern)))
        return await self._list_page(query.order_by(Project.name, Project.id), limit, offset)

    async def list_material_requests(
        self,
        actor: User,
        *,
        request_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[MaterialRequest], int]:
        query = (
            select(MaterialRequest)
            .where(
                MaterialRequest.deleted_at.is_(None),
                or_(MaterialRequest.status != "draft", MaterialRequest.requester_id == actor.id),
            )
            .options(selectinload(MaterialRequest.lines))
            .order_by(MaterialRequest.created_at.desc(), MaterialRequest.id.desc())
        )
        if request_id:
            query = query.where(MaterialRequest.id == request_id)
        project_ids = await self._inventory_project_scope(actor)
        if project_ids is not None:
            if not project_ids:
                return [], 0
            query = query.where(MaterialRequest.project_id.in_(project_ids))
        return await self._list_page(query, limit, offset)

    async def _inventory_project_scope(self, actor: User) -> list[UUID] | None:
        if actor.role in COMPANY_RESOURCE_ROLES:
            return None
        return await accessible_project_ids(self.session, actor) or []

    async def _list_page[T](
        self, query: Select[T], limit: int | None, offset: int
    ) -> tuple[list[T], int]:
        if limit is None and not offset:
            rows = list(await self.session.scalars(query))
            return rows, len(rows)
        count = select(func.count()).select_from(query.order_by(None).subquery())
        total = await self.session.scalar(count)
        page_rows = await self.session.scalars(query.limit(limit or 100).offset(offset))
        return list(page_rows), int(total or 0)

    async def reserve_request(self, request_id: UUID, actor: User) -> MaterialRequest:
        request = await self._get_material_request(request_id, for_update=True)
        await self._ensure_material_fulfillment(request, actor)
        if request.status != "approved":
            raise AppException(
                "Only approved material requests can be reserved.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        for line in sorted(request.lines, key=lambda line: (line.item_id, line.id)):
            # ``reserved_quantity`` tracks only what is reserved and NOT yet issued, so
            # re-reserving a partially issued request must not reserve the issued part again.
            remaining = line.quantity - line.reserved_quantity - line.issued_quantity
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
        request.revision += 1
        await self.session.commit()
        return request

    async def issue_request(self, request_id: UUID, actor: User) -> MaterialRequest:
        request = await self._get_material_request(request_id, for_update=True)
        await self._ensure_material_fulfillment(request, actor)
        if request.status not in {"reserved", "partially_issued"}:
            raise AppException(
                "Only reserved material requests can be issued.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        fully_issued = True
        for line in sorted(request.lines, key=lambda line: (line.item_id, line.id)):
            remaining = line.quantity - line.issued_quantity
            if remaining <= 0:
                continue
            stock = await self._get_stock(line.item_id, request.from_location_id, for_update=True)
            if (
                line.reserved_quantity < remaining
                or stock.reserved_qty < remaining
                or stock.on_hand_qty < remaining
            ):
                fully_issued = False
                continue
            stock.reserved_qty -= remaining
            stock.on_hand_qty -= remaining
            await self._notify_low_stock(
                item_id=line.item_id,
                location_id=request.from_location_id,
                project_id=request.project_id,
            )
            line.issued_quantity += remaining
            # Issuing consumes the reservation: keep the line invariant
            # reserved_quantity == quantity - issued_quantity (floored at zero).
            line.reserved_quantity = max(Decimal("0"), line.reserved_quantity - remaining)
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
        request.revision += 1
        await self.session.commit()
        return request

    async def cancel_request(self, request_id: UUID, actor: User) -> MaterialRequest:
        ensure_permission(actor, PERMISSION_INVENTORY_MANAGE)
        request = await self._get_material_request(request_id, for_update=True, lock_lines=False)
        if request.status == "issued":
            raise AppException(
                "Material request cannot be cancelled.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        await ApprovalService(self.session).cancel_material_request_approvals(request.id, actor)
        if request.status == "cancelled":
            await self.session.commit()
            return request
        await self._lock_request_lines(request.id)
        await self._cancel_locked_request(request, actor)
        await self.session.commit()
        return request

    async def _cancel_locked_request(self, request: MaterialRequest, actor: User) -> None:
        for line in sorted(request.lines, key=lambda line: (line.item_id, line.id)):
            if line.reserved_quantity > 0:
                stock = await self._get_stock(
                    line.item_id,
                    request.from_location_id,
                    for_update=True,
                )
                # Legacy lines can still include the portion already issued.
                # The stock pool also includes reservations for other requests.
                unissued = max(Decimal("0"), line.quantity - line.issued_quantity)
                available_reservation = max(Decimal("0"), stock.reserved_qty)
                release = min(line.reserved_quantity, unissued, available_reservation)
                stock.reserved_qty -= release
                line.reserved_quantity = Decimal("0")
        request.status = "cancelled"
        request.revision += 1
        await self.audit.record(
            action="inventory.requests.cancelled",
            user_id=actor.id,
            entity_type="material_requests",
            entity_id=request.id,
        )

    async def fulfill_quantities(
        self,
        request_id: UUID,
        actor: User,
        command: MaterialQuantityCommand,
        *,
        action: Literal["reserve", "issue"],
        key: str,
    ) -> MaterialRequestResponse:
        ensure_permission(actor, PERMISSION_INVENTORY_VIEW)
        route = f"inventory.requests.{action}"
        amounts = {line.line_id: line.quantity for line in command.lines}
        payload = "|".join(
            [
                str(request_id),
                str(command.expected_revision),
                *(f"{line_id}:{amount:.3f}" for line_id, amount in sorted(amounts.items())),
            ]
        )
        fingerprint = sha256(payload.encode()).hexdigest()
        replay = await resolve_or_reserve(self.session, key=key, user_id=actor.id, route=route)
        record = await self.session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.key == key,
                IdempotencyRecord.user_id == actor.id,
                IdempotencyRecord.route == route,
            )
        )
        assert record is not None
        if replay is not None:
            request = await self._get_material_request(
                request_id, for_update=True, lock_lines=False
            )
            await self._ensure_material_fulfillment(request, actor, check_decisions=False)
            if record.request_fingerprint != fingerprint or record.response_json is None:
                raise AppException(
                    "This command key was used for different quantities.",
                    status_code=409,
                    error_code="REQUEST_REPLAY_CONFLICT",
                )
            return MaterialRequestResponse.model_validate(record.response_json)

        request = await self._get_material_request(request_id, for_update=True)
        await self._ensure_material_fulfillment(request, actor)
        if request.revision != command.expected_revision:
            raise AppException(
                "Refresh the request before making further changes.",
                status_code=409,
                error_code="REQUEST_REVISION_CONFLICT",
            )
        if request.status not in {"approved", "partially_reserved", "reserved", "partially_issued"}:
            raise AppException(
                "This material request is no longer eligible for fulfillment.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )

        lines = [line for line in request.lines if line.deleted_at is None]
        selected = sorted(
            (line for line in lines if line.id in amounts), key=lambda line: (line.item_id, line.id)
        )
        if len(selected) != len(amounts):
            raise AppException(
                "Every selected line must belong to this request.",
                status_code=422,
                error_code="REQUEST_LINE_INVALID",
            )
        stocks: dict[UUID, InventoryLocationStock] = {}
        allocated: dict[UUID, Decimal] = {}
        for line in selected:
            if line.item_id not in stocks:
                stocks[line.item_id] = await self._get_stock(
                    line.item_id, request.from_location_id, for_update=True
                )
            stock = stocks[line.item_id]
            quantity = amounts[line.id]
            prior = allocated.get(line.item_id, Decimal("0"))
            outstanding = line.quantity - line.issued_quantity
            if action == "reserve":
                allowed = min(
                    outstanding - line.reserved_quantity,
                    stock.on_hand_qty - stock.reserved_qty - prior,
                )
            else:
                allowed = min(
                    outstanding,
                    line.reserved_quantity,
                    stock.reserved_qty - prior,
                    stock.on_hand_qty - prior,
                )
            if quantity > allowed:
                raise AppException(
                    "A selected quantity exceeds the line or available stock balance.",
                    status_code=409,
                    error_code="REQUEST_QUANTITY_UNAVAILABLE",
                )
            allocated[line.item_id] = prior + quantity

        for line in selected:
            quantity = amounts[line.id]
            stock = stocks[line.item_id]
            if action == "reserve":
                stock.reserved_qty += quantity
                line.reserved_quantity += quantity
            else:
                stock.reserved_qty -= quantity
                stock.on_hand_qty -= quantity
                line.reserved_quantity -= quantity
                line.issued_quantity += quantity
            self.session.add(
                InventoryMovement(
                    item_id=line.item_id,
                    movement_type=action,
                    quantity=quantity,
                    from_location_id=request.from_location_id,
                    project_id=request.project_id,
                    reference_type="material_request",
                    reference_id=request.id,
                    handled_by=actor.id,
                )
            )
        if action == "issue":
            for item_id in stocks:
                await self._notify_low_stock(
                    item_id=item_id,
                    location_id=request.from_location_id,
                    project_id=request.project_id,
                )
        if all(line.issued_quantity == line.quantity for line in lines):
            request.status = "issued"
        elif any(line.issued_quantity > 0 for line in lines):
            request.status = "partially_issued"
        elif all(line.reserved_quantity == line.quantity for line in lines):
            request.status = "reserved"
        else:
            request.status = "partially_reserved"
        request.revision += 1
        await self.audit.record(
            action=f"inventory.requests.{action}",
            user_id=actor.id,
            entity_type="material_requests",
            entity_id=request.id,
            new_values={"revision": request.revision, "status": request.status},
        )
        response = MaterialRequestResponse.model_validate(request)
        record.resource_type = "material_request"
        record.resource_id = request.id
        record.request_fingerprint = fingerprint
        record.response_json = response.model_dump(mode="json")
        await self.session.commit()
        return response

    async def _apply_movement(
        self,
        payload: MovementCreateRequest,
        actor: User,
        *,
        import_row: tuple[UUID, int] | None = None,
        registration: InventoryRegistration | None = None,
    ) -> InventoryMovement:
        if payload.reference_type == "material_request":
            raise AppException(
                "Use the material request workflow to post request stock movements.",
                status_code=409,
                error_code="MATERIAL_REQUEST_WORKFLOW_REQUIRED",
            )
        if payload.reference_type == "inventory_registration" and (
            registration is None
            or registration.id != payload.reference_id
            or registration.reviewer_id != actor.id
            or registration.status != "pending_engineer"
        ):
            raise PermissionDeniedException("receive an inventory registration")
        await self._get_item(payload.item_id)
        if payload.movement_type == "receive":
            if not payload.to_location_id:
                raise AppException("Receive requires destination.", status_code=422)
            destination_id = await self.session.scalar(
                select(StorageLocation.id)
                .where(
                    StorageLocation.id == payload.to_location_id,
                    StorageLocation.deleted_at.is_(None),
                    StorageLocation.is_active.is_(True),
                )
                .with_for_update(read=True)
            )
            if destination_id is None:
                raise NotFoundException("Eligible receipt destination")
            stock = await self._get_or_create_stock(payload.item_id, destination_id)
            stock.on_hand_qty += payload.quantity
        elif payload.movement_type == "transfer":
            if not payload.from_location_id or not payload.to_location_id:
                raise AppException("Transfer requires source and destination.", status_code=422)
            if payload.from_location_id == payload.to_location_id:
                raise AppException(
                    "Choose different source and destination locations.",
                    status_code=422,
                    error_code="TRANSFER_SAME_LOCATION",
                )
            active_locations = set(
                await self.session.scalars(
                    select(StorageLocation.id)
                    .where(
                        StorageLocation.id.in_([payload.from_location_id, payload.to_location_id]),
                        StorageLocation.deleted_at.is_(None),
                        StorageLocation.is_active.is_(True),
                    )
                    .order_by(StorageLocation.id)
                    .with_for_update(read=True)
                )
            )
            if len(active_locations) != 2:
                raise NotFoundException("Eligible transfer location")
            asset = await self._lock_transfer_asset(payload) if payload.asset_id else None
            first_loc = sorted([str(payload.from_location_id), str(payload.to_location_id)])[0]

            if first_loc == str(payload.from_location_id):
                await self._decrease_available(
                    payload.item_id, payload.from_location_id, payload.quantity
                )
                destination = await self._get_or_create_stock(
                    payload.item_id, payload.to_location_id
                )
                destination.on_hand_qty += payload.quantity
            else:
                destination = await self._get_or_create_stock(
                    payload.item_id, payload.to_location_id
                )
                destination.on_hand_qty += payload.quantity
                await self._decrease_available(
                    payload.item_id, payload.from_location_id, payload.quantity
                )
            if asset:
                asset.current_location_id = payload.to_location_id
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
            # _get_or_create_stock already holds an advisory lock plus FOR UPDATE on the row.
            stock = await self._get_or_create_stock(payload.item_id, payload.to_location_id)
            if payload.quantity < 0 and stock.on_hand_qty + payload.quantity < stock.reserved_qty:
                raise AppException(
                    "Adjustment would consume reserved stock.",
                    status_code=409,
                    error_code="INSUFFICIENT_STOCK",
                )
            stock.on_hand_qty += payload.quantity
        elif payload.movement_type == "reserve":
            if not payload.from_location_id:
                raise AppException("Reservation requires source.", status_code=422)
            await self._reserve_stock(payload.item_id, payload.from_location_id, payload.quantity)

        movement = InventoryMovement(**payload.model_dump(), handled_by=actor.id)
        if registration is not None:
            movement.registration_id = registration.id
        if import_row:
            movement.import_batch_id, movement.import_row_index = import_row
        self.session.add(movement)
        await self.session.flush()
        return movement

    async def _lock_transfer_asset(self, payload: MovementCreateRequest) -> InventoryAsset:
        asset = await self.session.scalar(
            select(InventoryAsset)
            .where(
                InventoryAsset.id == payload.asset_id,
                InventoryAsset.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if asset is None:
            raise NotFoundException("Inventory asset")
        if asset.item_id != payload.item_id or payload.quantity != Decimal(1):
            raise AppException(
                "A tagged transfer must move one unit of the item assigned to the asset tag.",
                status_code=422,
                error_code="INVALID_ASSET_TRANSFER",
            )
        if asset.current_location_id != payload.from_location_id or asset.status not in {
            "active",
            "available",
        }:
            raise AppException(
                "The asset is no longer available at the selected source.",
                status_code=409,
                error_code="ASSET_NOT_AVAILABLE",
            )
        return asset

    async def _decrease_available(
        self, item_id: UUID, location_id: UUID, quantity: Decimal
    ) -> None:
        stock = await self._get_stock(item_id, location_id, for_update=True)
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
        stock = await self._get_stock(item_id, location_id, for_update=True)
        available = stock.on_hand_qty - stock.reserved_qty
        if available < quantity:
            raise AppException(
                f"Insufficient stock. Available quantity is {available}.",
                status_code=409,
                error_code="INSUFFICIENT_STOCK",
            )
        stock.reserved_qty += quantity

    async def _notify_low_stock_for_movement(self, payload: MovementCreateRequest) -> None:
        if payload.movement_type not in STOCK_OUT_TYPES:
            return
        await self._notify_low_stock(
            item_id=payload.item_id,
            location_id=payload.from_location_id,
            project_id=payload.project_id,
        )

    async def _notify_low_stock(
        self,
        *,
        item_id: UUID,
        location_id: UUID | None,
        project_id: UUID | None,
    ) -> None:
        if not location_id:
            return
        item = await self._get_item(item_id)
        if not item.reorder_level or item.reorder_level <= 0:
            return
        stock = await self._get_stock(item_id, location_id)
        if stock.on_hand_qty > item.reorder_level:
            return
        recipients = await self._low_stock_recipients(project_id)
        for user_id in recipients:
            existing = await self.session.scalar(
                select(Notification.id).where(
                    Notification.user_id == user_id,
                    Notification.title == "Low Stock Alert",
                    Notification.reference_type == "inventory_item",
                    Notification.reference_id == item.id,
                    Notification.deleted_at.is_(None),
                )
            )
            if existing:
                continue
            await self.notifications.create(
                user_id=user_id,
                title="Low Stock Alert",
                body=f"{item.name} stock is at or below reorder level.",
                notification_type="inventory",
                reference_type="inventory_item",
                reference_id=item.id,
            )

    async def _low_stock_recipients(self, project_id: UUID | None) -> set[UUID]:
        recipients = set(
            (
                await self.session.scalars(
                    select(User.id).where(
                        User.role.in_(roles_with_permission(PERMISSION_INVENTORY_VIEW)),
                        User.is_active.is_(True),
                        User.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        if project_id:
            recipients.update(
                (
                    await self.session.scalars(
                        select(ProjectMember.user_id)
                        .join(User, User.id == ProjectMember.user_id)
                        .where(
                            ProjectMember.project_id == project_id,
                            ProjectMember.deleted_at.is_(None),
                            User.role.in_(
                                PROJECT_OPERATIONAL_MANAGER_ROLES - COMPANY_RESOURCE_ROLES
                            ),
                            User.is_active.is_(True),
                            User.deleted_at.is_(None),
                        )
                    )
                ).all()
            )
        return recipients

    async def _get_stock(
        self,
        item_id: UUID,
        location_id: UUID | None,
        *,
        for_update: bool = False,
    ) -> InventoryLocationStock:
        if not location_id:
            raise AppException("Location is required.", status_code=422)
        query = select(InventoryLocationStock).where(
            InventoryLocationStock.item_id == item_id,
            InventoryLocationStock.location_id == location_id,
            InventoryLocationStock.deleted_at.is_(None),
        )
        if for_update:
            query = query.with_for_update()
        stock = await self.session.scalar(query)
        if not stock:
            raise AppException("Stock is not available at this location.", status_code=409)
        return stock

    async def _get_or_create_stock(
        self,
        item_id: UUID,
        location_id: UUID,
    ) -> InventoryLocationStock:
        await self.session.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"inventory-stock:{item_id}:{location_id}"},
        )
        stock = await self.session.scalar(
            select(InventoryLocationStock)
            .where(
                InventoryLocationStock.item_id == item_id,
                InventoryLocationStock.location_id == location_id,
                InventoryLocationStock.deleted_at.is_(None),
            )
            .with_for_update()
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

    async def _find_consumption_items(self, material_name: str) -> list[InventoryItem]:
        normalized = material_name.strip().lower()
        return list(
            (
                await self.session.scalars(
                    select(InventoryItem)
                    .where(
                        InventoryItem.deleted_at.is_(None),
                        or_(
                            func.lower(InventoryItem.name) == normalized,
                            func.lower(InventoryItem.item_code) == normalized,
                        ),
                    )
                    .order_by(InventoryItem.updated_at.desc(), InventoryItem.created_at.desc())
                )
            ).all()
        )

    async def _find_consumption_stock(
        self,
        *,
        item_id: UUID,
        project_id: UUID,
        quantity: Decimal,
    ) -> InventoryLocationStock | None:
        stocks = list(
            (
                await self.session.scalars(
                    select(InventoryLocationStock)
                    .join(StorageLocation, StorageLocation.id == InventoryLocationStock.location_id)
                    .where(
                        InventoryLocationStock.item_id == item_id,
                        InventoryLocationStock.deleted_at.is_(None),
                        StorageLocation.deleted_at.is_(None),
                    )
                    .order_by(
                        (StorageLocation.project_id == project_id).desc(),
                        StorageLocation.location_type.desc(),
                    )
                )
            ).all()
        )
        for stock in stocks:
            if stock.on_hand_qty - stock.reserved_qty >= quantity:
                return stock
        return None

    async def _get_material_request(
        self,
        request_id: UUID,
        *,
        for_update: bool = False,
        lock_lines: bool = True,
    ) -> MaterialRequest:
        query = (
            select(MaterialRequest)
            .where(
                MaterialRequest.id == request_id,
                MaterialRequest.deleted_at.is_(None),
            )
            .options(selectinload(MaterialRequest.lines))
        )
        if for_update:
            query = query.with_for_update()
        request = await self.session.scalar(query)
        if not request:
            raise NotFoundException("Material request")
        if for_update and lock_lines:
            await self._lock_request_lines(request.id)
        return request

    async def _lock_request_lines(self, request_id: UUID) -> None:
        await self.session.scalars(
            select(MaterialRequestLine)
            .where(
                MaterialRequestLine.request_id == request_id,
                MaterialRequestLine.deleted_at.is_(None),
            )
            .order_by(MaterialRequestLine.id)
            .with_for_update()
        )
