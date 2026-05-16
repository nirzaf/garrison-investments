from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorItem(BaseModel):
    field: str | None = None
    message: str


class ErrorResponse(BaseModel):
    detail: str
    error_code: str
    errors: list[ErrorItem] = Field(default_factory=list)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
    total_pages: int


class BaseOrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
