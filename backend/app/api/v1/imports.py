import csv
from io import StringIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from app.api.dependencies import DbSession, require_permission
from app.models.import_batch import ImportBatch
from app.models.user import User
from app.schemas.imports import (
    ImportBatchListResponse,
    ImportPreviewResponse,
    ImportQueueResponse,
    ImportRunResponse,
)
from app.services.idempotency import validate_key
from app.services.import_service import TEMPLATE_COLUMNS, ImportService
from app.tasks.imports import run_import_async
from app.utils.permissions import COMPANY_RESOURCE_ROLES, PERMISSION_USERS_MANAGE

router = APIRouter(prefix="/imports", tags=["Imports"])

CanManageImports = Annotated[User, Depends(require_permission(PERMISSION_USERS_MANAGE))]


@router.get("/templates/{template_type}")
async def download_template(
    template_type: str,
    current_user: CanManageImports,
    session: DbSession,
) -> Response:
    ImportService(session).template_path(template_type, current_user)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(TEMPLATE_COLUMNS[template_type])
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{template_type}.csv"'},
    )


@router.get("/batches/{batch_id}")
async def get_batch_status(
    batch_id: UUID,
    current_user: CanManageImports,
    session: DbSession,
):
    batch = await session.scalar(select(ImportBatch).where(ImportBatch.id == batch_id))
    if not batch:
        return JSONResponse(status_code=404, content={"detail": "Import batch not found"})
    ImportService.ensure_template_access(current_user, batch.template_type)
    if current_user.role not in COMPANY_RESOURCE_ROLES and batch.created_by != current_user.id:
        return JSONResponse(status_code=404, content={"detail": "Import batch not found"})
    return {
        "batch_id": str(batch.id),
        "template_type": batch.template_type,
        "file_name": batch.file_name,
        "status": batch.status,
        "row_count": batch.row_count,
        "error_count": batch.error_count,
        "summary": batch.summary,
    }


@router.get("/batches", response_model=ImportBatchListResponse)
async def list_import_batches(
    current_user: CanManageImports,
    session: DbSession,
) -> ImportBatchListResponse:
    query = select(ImportBatch).where(ImportBatch.deleted_at.is_(None))
    if current_user.role not in COMPANY_RESOURCE_ROLES:
        query = query.where(ImportBatch.created_by == current_user.id)
    batches = (await session.scalars(query.order_by(ImportBatch.created_at.desc()).limit(25))).all()
    return ImportBatchListResponse(
        items=[
            ImportRunResponse(
                batch_id=batch.id,
                template_type=batch.template_type,
                file_name=batch.file_name,
                status=batch.status,
                row_count=batch.row_count,
                error_count=batch.error_count,
                summary=batch.summary or {},
            )
            for batch in batches
        ],
        total=len(batches),
    )


@router.post("/{template_type}/preview", response_model=ImportPreviewResponse)
async def preview_import(
    template_type: str,
    current_user: CanManageImports,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> ImportPreviewResponse:
    content = await file.read()
    return await ImportService(session).preview(template_type, content, current_user)


@router.post("/{template_type}/run", response_model=ImportRunResponse)
async def run_import(
    template_type: str,
    current_user: CanManageImports,
    session: DbSession,
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ImportRunResponse:
    content = await file.read()
    return await ImportService(session).run_import(
        template_type=template_type,
        file_name=file.filename or "import.csv",
        content=content,
        actor=current_user,
        idempotency_key=validate_key(idempotency_key),
    )


@router.post("/{template_type}/run-async", response_model=ImportQueueResponse, status_code=202)
async def run_import_async_endpoint(
    template_type: str,
    current_user: CanManageImports,
    session: DbSession,
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ImportQueueResponse:
    content = await file.read()
    batch = await ImportService(session).queue_import(
        template_type=template_type,
        file_name=file.filename or "import.csv",
        content=content,
        actor=current_user,
        idempotency_key=validate_key(idempotency_key),
    )
    task_id = str(batch.batch_id)
    if batch.status == "queued":
        # A retry can publish again if the original broker acknowledgement was lost.
        # Every delivery processes the same database batch under its existing lock.
        run_import_async.apply_async(
            kwargs={
                "template_type": template_type,
                "file_name": file.filename or "import.csv",
                "content": content,
                "actor_id": str(current_user.id),
                "batch_id": task_id,
            },
            task_id=task_id,
        )
    return ImportQueueResponse(**batch.model_dump(), task_id=task_id)
