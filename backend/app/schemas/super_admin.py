from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class SuperAdminOverview(BaseModel):
    scope: Literal["platform"] = "platform"
    source: Literal["portal-api"] = "portal-api"
    status: Literal["available"] = "available"
    observed_at: datetime


class SuperAdminChallenge(BaseModel):
    challenge_id: UUID
    expires_at: datetime


class SuperAdminToken(BaseModel):
    access_token: str
    expires_at: datetime
