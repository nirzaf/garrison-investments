from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AuthUserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    must_change_password: bool
    permissions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class LoginChallengeResponse(BaseModel):
    challenge_id: UUID
    expires_at: datetime
    expires_in_seconds: int
    dev_otp: str | None = None


class VerifyOtpRequest(BaseModel):
    challenge_id: UUID
    otp: str = Field(min_length=6, max_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: AuthUserResponse


class RefreshResponse(TokenResponse):
    pass


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetChallengeResponse(BaseModel):
    challenge_id: UUID | None = None
    expires_at: datetime | None = None
    expires_in_seconds: int | None = None
    dev_otp: str | None = None
    message: str


class PasswordResetConfirmRequest(BaseModel):
    challenge_id: UUID
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=256)


class MessageResponse(BaseModel):
    message: str
