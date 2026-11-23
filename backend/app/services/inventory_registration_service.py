from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.inventory import (
    InventoryAsset,
    InventoryItem,
    InventoryRegistration,
    StorageLocation,
)
from app.models.photo import Photo
from app.models.project import Project
from app.models.user import User
from app.schemas.inventory import (
    InventoryRegistrationCorrectionRequest,
    InventoryRegistrationCreateRequest,
    InventoryRegistrationDecisionRequest,
    MovementCreateRequest,
)
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.authorization import (
    INVENTORY_REGISTRATION_READER_ROLES,
    accessible_project_ids,
    ensure_inventory_registration_access,
    ensure_project_access,
)
from app.services.inventory_service import InventoryService
from app.services.notification_service import NotificationService
from app.services.supplier_service import SupplierService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.links import append_link, build_frontend_url
from app.utils.permissions import ROLE_MEP_PROJECT_MANAGER, SUPERVISOR_ROLES
from app.utils.security import utc_now


class InventoryRegistrationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    async def list_registrations(
        self, actor: User, *, limit: int, offset: int, registration_id: UUID | None = None
    ) -> tuple[list[InventoryRegistration], int]:
        replacement = aliased(InventoryRegistration)
        query = select(InventoryRegistration).join(
            Project, Project.id == InventoryRegistration.project_id
        )
        query = query.where(Project.deleted_at.is_(None))
        if actor.role in SUPERVISOR_ROLES:
            query = query.where(InventoryRegistration.created_by == actor.id)
        elif actor.role in INVENTORY_REGISTRATION_READER_ROLES:
            query = query.where(InventoryRegistration.status != "draft")
        else:
            raise PermissionDeniedException("read inventory registrations")
        scoped = await accessible_project_ids(self.session, actor)
        if scoped is not None:
            query = query.where(InventoryRegistration.project_id.in_(scoped))
        if registration_id is not None:
            query = query.where(InventoryRegistration.id == registration_id)
        else:
            successor = select(replacement.id).where(
                replacement.previous_id == InventoryRegistration.id
            )
            if actor.role not in SUPERVISOR_ROLES:
                successor = successor.where(replacement.status != "draft")
            query = query.where(~successor.exists())
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.scalars(
            query.order_by(InventoryRegistration.created_at.desc(), InventoryRegistration.id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def history(self, registration_id: UUID, actor: User) -> list[InventoryRegistration]:
        row = await self._get(registration_id)
        await ensure_inventory_registration_access(self.session, row, actor)
        root = row.root_id or row.id
        query = select(InventoryRegistration).where(
            (InventoryRegistration.id == root) | (InventoryRegistration.root_id == root)
        )
        if actor.role not in SUPERVISOR_ROLES:
            query = query.where(InventoryRegistration.status != "draft")
        return list(
            await self.session.scalars(
                query.order_by(InventoryRegistration.submission_revision.desc())
            )
        )

    async def create(
        self, payload: InventoryRegistrationCreateRequest, actor: User
    ) -> InventoryRegistration:
        self._ensure_supervisor(actor)
        return await self._create_draft(payload, actor)

    async def correct(
        self, registration_id: UUID, payload: InventoryRegistrationCorrectionRequest, actor: User
    ) -> InventoryRegistration:
        self._ensure_supervisor(actor)
        row = await self._get(registration_id, lock=True)
        await ensure_inventory_registration_access(self.session, row, actor)
        self._check_revision(row, payload.expected_submission_revision)
        if row.status not in {"returned", "rejected"} or payload.project_id != row.project_id:
            raise self._state_conflict()
        if await self.session.scalar(
            select(InventoryRegistration.id).where(InventoryRegistration.previous_id == row.id)
        ):
            raise self._state_conflict()
        return await self._create_draft(payload, actor, previous=row)

    async def submit(
        self, registration_id: UUID, expected_revision: int, actor: User
    ) -> InventoryRegistration:
        self._ensure_supervisor(actor)
        row = await self._get(registration_id, lock=True)
        await ensure_inventory_registration_access(self.session, row, actor)
        self._check_revision(row, expected_revision)
        if row.status != "draft":
            raise self._state_conflict()
        await self._eligible_location(row.project_id, row.location_id)
        evidence = await self.session.execute(
            select(Photo.id, Photo.kind)
            .where(
                Photo.entity_type == "inventory_registration",
                Photo.entity_id == row.id,
                Photo.uploaded_by == actor.id,
                Photo.deleted_at.is_(None),
                Photo.processing_status == "ready",
            )
            .order_by(Photo.created_at, Photo.id)
        )
        photos = evidence.all()
        if not any(kind == "photo" for _, kind in photos):
            raise AppException(
                "Upload at least one photograph of the received item.",
                status_code=422,
                error_code="REGISTRATION_PHOTO_REQUIRED",
            )
        reviewer = await ApprovalService(self.session).require_project_reviewer(
            row.project_id, ROLE_MEP_PROJECT_MANAGER, excluded_user_ids={actor.id}
        )
        row.status = "pending_engineer"
        row.reviewer_id = reviewer.id
        row.submitted_at = utc_now()
        row.evidence_ids = [str(photo_id) for photo_id, _ in photos]
        await self._audit(row, actor, "submitted")
        await self._notify(
            reviewer.id,
            row,
            "Inventory registration awaiting review",
            "Review the received items and attached evidence.",
        )
        await self.session.commit()
        return row

    async def decide(
        self, registration_id: UUID, payload: InventoryRegistrationDecisionRequest, actor: User
    ) -> InventoryRegistration:
        if actor.role != ROLE_MEP_PROJECT_MANAGER:
            raise PermissionDeniedException("decide inventory registrations")
        row = await self._get(registration_id, lock=True)
        await ensure_inventory_registration_access(self.session, row, actor)
        if row.reviewer_id != actor.id or row.created_by == actor.id:
            raise PermissionDeniedException("decide this inventory registration")
        self._check_revision(row, payload.expected_submission_revision)
        if row.status != "pending_engineer":
            raise self._state_conflict()
        await ApprovalService(self.session).require_project_reviewer(
            row.project_id,
            ROLE_MEP_PROJECT_MANAGER,
            approver_id=actor.id,
            excluded_user_ids={row.created_by},
        )
        comments = payload.comments.strip() if payload.comments else None
        if payload.decision != "approved" and not comments:
            raise AppException(
                "Give a reason for returning or rejecting this registration.",
                status_code=422,
                error_code="DECISION_REASON_REQUIRED",
            )
        await self._eligible_location(row.project_id, row.location_id)
        if payload.decision == "approved":
            await self._receive(row, actor)
        row.status = payload.decision
        row.decided_at = utc_now()
        row.decision_comments = comments
        await self._audit(row, actor, payload.decision, comments=comments)
        await self._notify(
            row.created_by,
            row,
            f"Inventory registration {payload.decision}",
            comments or "The inventory receipt is confirmed.",
        )
        await self.session.commit()
        return row

    async def _create_draft(
        self,
        payload: InventoryRegistrationCreateRequest,
        actor: User,
        *,
        previous: InventoryRegistration | None = None,
    ) -> InventoryRegistration:
        await ensure_project_access(self.session, payload.project_id, actor)
        await self._eligible_location(payload.project_id, payload.location_id)
        await self._catalog_item(payload)
        row = InventoryRegistration(
            project_id=payload.project_id,
            location_id=payload.location_id,
            created_by=actor.id,
            root_id=(previous.root_id or previous.id) if previous else None,
            previous_id=previous.id if previous else None,
            submission_revision=previous.submission_revision + 1 if previous else 1,
            status="draft",
            requirements=payload.model_dump(mode="json", exclude={"expected_submission_revision"}),
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(row, actor, "correction_drafted" if previous else "drafted")
        await self.session.commit()
        return row

    async def _catalog_item(
        self, payload: InventoryRegistrationCreateRequest
    ) -> InventoryItem | None:
        if payload.supplier_id is not None:
            await SupplierService(self.session).get_active_supplier(payload.supplier_id)
        if payload.catalog_item_id is None:
            return None
        item = await self.session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == payload.catalog_item_id,
                InventoryItem.is_active.is_(True),
                InventoryItem.deleted_at.is_(None),
                InventoryItem.unit == payload.unit,
                InventoryItem.item_type
                == ("consumable" if payload.category == "material" else "asset"),
            )
        )
        if item is None:
            raise NotFoundException("Matching active inventory item")
        return item

    async def _receive(self, row: InventoryRegistration, actor: User) -> None:
        payload = InventoryRegistrationCreateRequest.model_validate(row.requirements)
        item = await self._catalog_item(payload)
        if item is None:
            item = InventoryItem(
                name=payload.name,
                item_code=f"REG-{row.id.hex}",
                category=payload.category,
                item_type="consumable" if payload.category == "material" else "asset",
                unit=payload.unit,
                supplier_id=payload.supplier_id,
            )
            self.session.add(item)
            await self.session.flush()
        if payload.category != "material":
            for index in range(1, int(payload.quantity) + 1):
                self.session.add(
                    InventoryAsset(
                        item_id=item.id,
                        asset_tag=f"REG-{row.id.hex}-{index:03d}",
                        current_location_id=row.location_id,
                        condition=payload.condition,
                    )
                )
        movement = await InventoryService(self.session)._apply_movement(
            MovementCreateRequest(
                item_id=item.id,
                movement_type="receive",
                quantity=payload.quantity,
                to_location_id=row.location_id,
                project_id=row.project_id,
                reference_type="inventory_registration",
                reference_id=row.id,
                notes=payload.remarks,
            ),
            actor,
            registration=row,
        )
        row.confirmed_item_id = item.id
        row.movement_id = movement.id

    async def _eligible_location(self, project_id: UUID, location_id: UUID) -> None:
        location = await self.session.scalar(
            select(StorageLocation.id)
            .join(Project, Project.id == StorageLocation.project_id)
            .where(
                StorageLocation.id == location_id,
                StorageLocation.project_id == project_id,
                StorageLocation.is_active.is_(True),
                StorageLocation.deleted_at.is_(None),
                Project.status == "active",
                Project.deleted_at.is_(None),
            )
            .with_for_update(read=True, of=[StorageLocation, Project])
        )
        if location is None:
            raise NotFoundException("Active project stock location")

    async def _get(self, registration_id: UUID, *, lock: bool = False) -> InventoryRegistration:
        query = select(InventoryRegistration).where(InventoryRegistration.id == registration_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = await self.session.scalar(query)
        if row is None:
            raise NotFoundException("Inventory registration")
        return row

    @staticmethod
    def _check_revision(row: InventoryRegistration, expected_revision: int) -> None:
        if row.submission_revision != expected_revision:
            raise AppException(
                "Reload the inventory submission before taking action.",
                status_code=409,
                error_code="SUBMISSION_REVISION_CONFLICT",
            )

    @staticmethod
    def _state_conflict() -> AppException:
        return AppException(
            "This inventory registration is no longer at the required stage.",
            status_code=409,
            error_code="REGISTRATION_STATUS_INVALID",
        )

    @staticmethod
    def _ensure_supervisor(actor: User) -> None:
        if actor.role not in SUPERVISOR_ROLES:
            raise PermissionDeniedException("submit inventory registrations")

    async def _audit(
        self, row: InventoryRegistration, actor: User, action: str, *, comments: str | None = None
    ) -> None:
        await self.audit.record(
            action=f"inventory.registrations.{action}",
            user_id=actor.id,
            entity_type="inventory_registration",
            entity_id=row.id,
            comments=comments,
            new_values={
                "submission_revision": row.submission_revision,
                "status": row.status,
                "movement_id": str(row.movement_id) if row.movement_id else None,
            },
        )

    async def _notify(
        self, user_id: UUID, row: InventoryRegistration, title: str, body: str
    ) -> None:
        await self.notifications.create(
            user_id=user_id,
            title=title,
            body=append_link(
                body,
                label="Open inventory registration",
                url=build_frontend_url("/materials", query={"registrationId": str(row.id)}),
            ),
            notification_type="inventory",
            reference_type="inventory_registration",
            reference_id=row.id,
        )
