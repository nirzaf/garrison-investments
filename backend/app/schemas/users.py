from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    employee_code: str | None
    phone: str | None
    designation: str | None
    is_active: bool
    must_change_password: bool
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int


class UserDetailResponse(UserResponse):
    permissions: list[str]


class UserRoleResponse(BaseModel):
    role: str
    label: str
    permissions: list[str]
    assignable: bool = False


class UserRoleListResponse(BaseModel):
    items: list[UserRoleResponse]


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    role: str
    employee_code: str = Field(min_length=1, max_length=64)
    phone: str = Field(min_length=3, max_length=32)
    designation: str | None = Field(default=None, max_length=100)
    temporary_password: str = Field(min_length=8, max_length=256)


class UserUpdateRequest(BaseModel):
    expected_updated_at: AwareDatetime | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    role: str | None = None
    employee_code: str | None = Field(default=None, min_length=1, max_length=64)
    phone: str | None = Field(default=None, min_length=3, max_length=32)
    designation: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class AdminPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)
    expected_updated_at: AwareDatetime | None = None
