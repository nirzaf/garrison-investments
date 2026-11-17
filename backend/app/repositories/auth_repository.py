from datetime import datetime
from typing import Any
from typing import cast as type_cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthOtpChallenge, AuthRefreshToken, AuthSession
from app.utils.security import utc_now


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
            query = query.with_for_update().execution_options(populate_existing=True)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def recent_otp_challenges(
        self, user_id: UUID, purpose: str, since: datetime
    ) -> list[AuthOtpChallenge]:
        result = await self.session.scalars(
            select(AuthOtpChallenge)
            .where(
                AuthOtpChallenge.user_id == user_id,
                AuthOtpChallenge.purpose == purpose,
                AuthOtpChallenge.created_at >= since,
                AuthOtpChallenge.deleted_at.is_(None),
            )
            .order_by(AuthOtpChallenge.created_at.desc())
            .limit(3)
        )
        return list(result)

    async def revoke_all_refresh_tokens(self, user_id: UUID) -> int:
        """Revoke every live session for a user; returns the number of rows affected.

        Runs in the caller's transaction so a credential change and the revocation are
        atomic: a stolen refresh token cannot outlive the password it was issued under.
        """
        result = await self.session.execute(
            update(AuthRefreshToken)
            .where(
                AuthRefreshToken.user_id == user_id,
                AuthRefreshToken.revoked_at.is_(None),
                AuthRefreshToken.deleted_at.is_(None),
            )
            .values(revoked_at=utc_now())
        )
        return int(type_cast(CursorResult[Any], result).rowcount or 0)

    async def revoke_user_authentication(self, user_id: UUID) -> None:
        # Callers already hold the user's lock, which every session issuer takes.
        await self.revoke_all_refresh_tokens(user_id)
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utc_now())
        )
        await self.session.execute(
            update(AuthOtpChallenge)
            .where(
                AuthOtpChallenge.user_id == user_id,
                AuthOtpChallenge.consumed_at.is_(None),
                AuthOtpChallenge.deleted_at.is_(None),
            )
            .values(consumed_at=utc_now())
        )

    async def add_refresh_token(self, refresh_token: AuthRefreshToken) -> AuthRefreshToken:
        self.session.add(refresh_token)
        await self.session.flush()
        return refresh_token

    async def add_session(self, auth_session: AuthSession) -> AuthSession:
        self.session.add(auth_session)
        await self.session.flush()
        return auth_session

    async def get_session(self, session_id: UUID, user_id: UUID) -> AuthSession | None:
        return await self.session.scalar(
            select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user_id)
        )

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
            query = query.with_for_update().execution_options(populate_existing=True)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
