from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthOtpChallenge, AuthRefreshToken


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_otp_challenge(self, challenge: AuthOtpChallenge) -> AuthOtpChallenge:
        self.session.add(challenge)
        await self.session.flush()
        return challenge

    async def get_otp_challenge(
        self,
        challenge_id: UUID,
        *,
        for_update: bool = False,
    ) -> AuthOtpChallenge | None:
        query = select(AuthOtpChallenge).where(
            AuthOtpChallenge.id == challenge_id,
            AuthOtpChallenge.deleted_at.is_(None),
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def add_refresh_token(self, refresh_token: AuthRefreshToken) -> AuthRefreshToken:
        self.session.add(refresh_token)
        await self.session.flush()
        return refresh_token

    async def get_refresh_token_by_hash(
        self,
        token_hash: str,
        *,
        for_update: bool = False,
    ) -> AuthRefreshToken | None:
        query = select(AuthRefreshToken).where(
            AuthRefreshToken.token_hash == token_hash,
            AuthRefreshToken.deleted_at.is_(None),
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
