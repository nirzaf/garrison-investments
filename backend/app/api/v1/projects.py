from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import DbSession, require_permission
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.projects import (
    BoqItemResponse,
    MilestoneResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectMemberCreateRequest,
    ProjectMemberResponse,
    ProjectMemberRevocationResponse,
    ProjectResponse,
    ProjectTaskCreateRequest,
    ProjectTaskResponse,
    ProjectTaskUpdateRequest,
    ProjectTimelineResponse,
    ProjectUpdateRequest,
)
from app.services.project_service import READ_ONLY_STATUSES, ProjectService
from app.utils.permissions import (
    PERMISSION_FINANCIAL_VIEW,
    PERMISSION_PROJECTS_MANAGE,
    PERMISSION_PROJECTS_READ,
    has_permission,
)

router = APIRouter(prefix="/projects", tags=["Projects"])

CanReadProjects = Annotated[User, Depends(require_permission(PERMISSION_PROJECTS_READ))]
CanManageProjects = Annotated[User, Depends(require_permission(PERMISSION_PROJECTS_MANAGE))]


async def _member_responses(
    members: list[ProjectMember], session: DbSession
) -> list[ProjectMemberResponse]:
    names = await UserRepository(session).display_names({member.user_id for member in members})
    return [
        ProjectMemberResponse.model_validate(member).model_copy(
            update={"user_name": names.get(member.user_id)}
        )
        for member in members
    ]


def _project_response(project: object, actor: User) -> ProjectResponse:
    response = ProjectResponse.model_validate(project)
    if not has_permission(actor, PERMISSION_FINANCIAL_VIEW):
        response = response.model_copy(update={"budget_amount": None})
    return response


def _boq_responses(items: list[object], actor: User) -> list[BoqItemResponse]:
    responses = [BoqItemResponse.model_validate(item) for item in items]
    if not has_permission(actor, PERMISSION_FINANCIAL_VIEW):
        return [
            item.model_copy(update={"unit_rate": None, "planned_amount": None})
            for item in responses
        ]
    return responses


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
        items=[_project_response(project, current_user) for project in projects],
        total=total,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    current_user: CanManageProjects,
    session: DbSession,
) -> ProjectResponse:
    project = await ProjectService(session).create_project(payload, current_user)
    return _project_response(project, current_user)


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
        **_project_response(project, current_user).model_dump(),
        members=await _member_responses(members, session),
        milestones=[MilestoneResponse.model_validate(milestone) for milestone in milestones],
        boq_items=_boq_responses(boq_items, current_user),
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
    return _project_response(project, current_user)


@router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
async def list_project_members(
    project_id: UUID,
    current_user: CanReadProjects,
    session: DbSession,
) -> list[ProjectMemberResponse]:
    members = await ProjectService(session).list_members(project_id, current_user)
    return await _member_responses(members, session)


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
    responses = await _member_responses([member], session)
    return responses[0]


@router.delete("/{project_id}/members/{user_id}", response_model=ProjectMemberRevocationResponse)
async def revoke_project_member(
    project_id: UUID,
    user_id: UUID,
    expected_revision: Annotated[int, Query(ge=1)],
    current_user: CanManageProjects,
    session: DbSession,
) -> ProjectMemberRevocationResponse:
    revision = await ProjectService(session).revoke_member(
        project_id, user_id, expected_revision, current_user
    )
    return ProjectMemberRevocationResponse(
        project_id=project_id, user_id=user_id, revision=revision
    )


@router.get("/{project_id}/timeline", response_model=ProjectTimelineResponse)
async def get_project_timeline(
    project_id: UUID,
    current_user: CanReadProjects,
    session: DbSession,
) -> ProjectTimelineResponse:
    project, milestones, tasks = await ProjectService(session).list_timeline(
        project_id, current_user
    )
    return ProjectTimelineResponse(
        project=_project_response(project, current_user),
        milestones=[MilestoneResponse.model_validate(milestone) for milestone in milestones],
        tasks=[ProjectTaskResponse.model_validate(task) for task in tasks],
        owner_names=await UserRepository(session).display_names(
            {task.owner_id for task in tasks if task.owner_id is not None}
        ),
    )


@router.post(
    "/{project_id}/tasks",
    response_model=ProjectTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_task(
    project_id: UUID,
    payload: ProjectTaskCreateRequest,
    current_user: CanManageProjects,
    session: DbSession,
) -> ProjectTaskResponse:
    task = await ProjectService(session).create_task(project_id, payload, current_user)
    return ProjectTaskResponse.model_validate(task)


@router.patch("/{project_id}/tasks/{task_id}", response_model=ProjectTaskResponse)
async def update_project_task(
    project_id: UUID,
    task_id: UUID,
    payload: ProjectTaskUpdateRequest,
    current_user: CanManageProjects,
    session: DbSession,
) -> ProjectTaskResponse:
    task = await ProjectService(session).update_task(project_id, task_id, payload, current_user)
    return ProjectTaskResponse.model_validate(task)
