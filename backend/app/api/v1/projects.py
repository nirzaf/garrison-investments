from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import DbSession, require_permission
from app.models.user import User
from app.schemas.projects import (
    BoqItemResponse,
    MilestoneResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectMemberCreateRequest,
    ProjectMemberResponse,
    ProjectResponse,
    ProjectTimelineResponse,
    ProjectUpdateRequest,
)
from app.services.project_service import READ_ONLY_STATUSES, ProjectService
from app.utils.permissions import PERMISSION_PROJECTS_MANAGE, PERMISSION_PROJECTS_READ

router = APIRouter(prefix="/projects", tags=["Projects"])

CanReadProjects = Annotated[User, Depends(require_permission(PERMISSION_PROJECTS_READ))]
CanManageProjects = Annotated[User, Depends(require_permission(PERMISSION_PROJECTS_MANAGE))]


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    current_user: CanReadProjects,
    session: DbSession,
    status: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectListResponse:
    projects, total = await ProjectService(session).list_projects(
        current_user=current_user,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(project) for project in projects],
        total=total,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    current_user: CanManageProjects,
    session: DbSession,
) -> ProjectResponse:
    project = await ProjectService(session).create_project(payload, current_user)
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: UUID,
    current_user: CanReadProjects,
    session: DbSession,
) -> ProjectDetailResponse:
    project, members, milestones, boq_items = await ProjectService(session).get_project_detail(
        project_id,
        current_user,
    )
    return ProjectDetailResponse(
        **ProjectResponse.model_validate(project).model_dump(),
        members=[ProjectMemberResponse.model_validate(member) for member in members],
        milestones=[MilestoneResponse.model_validate(milestone) for milestone in milestones],
        boq_items=[BoqItemResponse.model_validate(item) for item in boq_items],
        is_read_only=project.status in READ_ONLY_STATUSES,
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    current_user: CanManageProjects,
    session: DbSession,
) -> ProjectResponse:
    project = await ProjectService(session).update_project(project_id, payload, current_user)
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
async def list_project_members(
    project_id: UUID,
    current_user: CanReadProjects,
    session: DbSession,
) -> list[ProjectMemberResponse]:
    members = await ProjectService(session).list_members(project_id, current_user)
    return [ProjectMemberResponse.model_validate(member) for member in members]


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_project_member(
    project_id: UUID,
    payload: ProjectMemberCreateRequest,
    current_user: CanManageProjects,
    session: DbSession,
) -> ProjectMemberResponse:
    member = await ProjectService(session).assign_member(project_id, payload, current_user)
    return ProjectMemberResponse.model_validate(member)


@router.get("/{project_id}/timeline", response_model=ProjectTimelineResponse)
async def get_project_timeline(
    project_id: UUID,
    current_user: CanReadProjects,
    session: DbSession,
) -> ProjectTimelineResponse:
    project, milestones = await ProjectService(session).list_timeline(project_id, current_user)
    return ProjectTimelineResponse(
        project=ProjectResponse.model_validate(project),
        milestones=[MilestoneResponse.model_validate(milestone) for milestone in milestones],
    )
