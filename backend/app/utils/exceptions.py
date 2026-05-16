from pydantic import BaseModel


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class AppException(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        error_code: str = "APP_ERROR",
        errors: list[ErrorDetail] | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.errors = [error.model_dump() for error in errors or []]
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, entity: str) -> None:
        super().__init__(
            f"{entity} not found",
            status_code=404,
            error_code=f"{entity.upper()}_NOT_FOUND",
        )


class PermissionDeniedException(AppException):
    def __init__(self, action: str) -> None:
        super().__init__(
            f"Permission denied: {action}",
            status_code=403,
            error_code="PERMISSION_DENIED",
        )


class BusinessRuleException(AppException):
    def __init__(self, message: str, *, error_code: str = "BUSINESS_RULE_VIOLATION") -> None:
        super().__init__(message, status_code=409, error_code=error_code)
