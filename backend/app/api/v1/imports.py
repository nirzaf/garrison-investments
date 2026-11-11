import csv
from io import StringIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from app.api.dependencies import DbSession, require_permission
from app.models.import_batch import ImportBatch
from app.models.user import User
from app.schemas.imports import ImportBatchListResponse, ImportPreviewResponse, ImportRunResponse
from app.services.import_service import TEMPLATE_COLUMNS, ImportService
from app.tasks.imports import run_import_async
from app.utils.permissions import PERMISSION_USERS_MANAGE

router = APIRouter(prefix="/imports", tags=["Imports"])

CanManageImports = Annotated[User, Depends(require_permission(PERMISSION_USERS_MANAGE))]


@router.get("/templates/{template_type}")
async def download_template(
    template_type: str,
    _: CanManageImports,
    session: DbSession,
) -> Response:
    ImportService(session).template_path(template_type)
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
    _: CanManageImports,
    session: DbSession,
):
    batch = await session.scalar(
        select(ImportBatch).where(ImportBatch.id == batch_id)
    )
    if not batch:
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
    _: CanManageImports,
    session: DbSession,
) -> ImportBatchListResponse:
    batches = (
        await session.scalars(
            select(ImportBatch)
            .where(ImportBatch.deleted_at.is_(None))
            .order_by(ImportBatch.created_at.desc())
            .limit(25)
        )
    ).all()
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
    _: CanManageImports,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> ImportPreviewResponse:
    content = await file.read()
    return await ImportService(session).preview(template_type, content)


@router.post("/{template_type}/run", response_model=ImportRunResponse)
async def run_import(
    template_type: str,
    current_user: CanManageImports,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> ImportRunResponse:
    content = await file.read()
    return await ImportService(session).run_import(
        template_type=template_type,
        file_name=file.filename or "import.csv",
        content=content,
        actor=current_user,
    )


@router.post("/{template_type}/run-async")
async def run_import_async_endpoint(
    template_type: str,
    current_user: CanManageImports,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> JSONResponse:
    content = await file.read()
    batch = ImportBatch(
        template_type=template_type,
        file_name=file.filename or "import.csv",
        status="queued",
        created_by=current_user.id,
        row_count=0,
        error_count=0,
        summary={},
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    task = run_import_async.delay(
        template_type=template_type,
        file_name=file.filename or "import.csv",
        content=content,
        actor_id=str(current_user.id),
        batch_id=str(batch.id),
    )
    return JSONResponse(
        status_code=202,
        content={
            "task_id": task.id,
            "batch_id": str(batch.id),
            "template_type": template_type,
            "status": "queued",
        },
    )
