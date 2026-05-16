from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse

from app.api.dependencies import DbSession, require_permission
from app.models.user import User
from app.schemas.imports import ImportPreviewResponse, ImportRunResponse
from app.services.import_service import ImportService
from app.utils.permissions import PERMISSION_USERS_MANAGE

router = APIRouter(prefix="/imports", tags=["Imports"])

CanManageImports = Annotated[User, Depends(require_permission(PERMISSION_USERS_MANAGE))]


@router.get("/templates/{template_type}")
async def download_template(
    template_type: str,
    _: CanManageImports,
    session: DbSession,
) -> FileResponse:
    path = ImportService(session).template_path(template_type)
    return FileResponse(path, media_type="text/csv", filename=path.name)


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
