"""Deliver reviewed recovery codes at most once per queued attempt."""

import asyncio
from datetime import timedelta
from hmac import compare_digest
from uuid import UUID

from sqlalchemy import select

from app.config import Settings, get_settings
from app.database import AsyncSessionLocal
from app.models.notification import Notification
from app.models.support_business_actions import SupportBusinessAction, SupportRecoveryDelivery
from app.repositories.auth_repository import AuthRepository
from app.services.email_service import EmailService
from app.services.support_business_actions import SupportBusinessActions
from app.services.support_identity import SUPPORT_HOST
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import celery_app
from app.utils.exceptions import AppException
from app.utils.recovery_destination import (
    recovery_portal_origin,
    support_recovery_otp,
    support_recovery_otp_digest,
)
from app.utils.security import utc_now


def _portal_origin(settings: Settings) -> str | None:
    return recovery_portal_origin(settings, support_host=SUPPORT_HOST)


async def _claim() -> UUID | None:
    now = utc_now()
    async with AsyncSessionLocal() as db:
        interrupted = await db.scalars(
            select(SupportRecoveryDelivery)
            .where(
                SupportRecoveryDelivery.status == "dispatching",
                SupportRecoveryDelivery.dispatch_started_at <= now - timedelta(minutes=2),
            )
            .order_by(
                SupportRecoveryDelivery.dispatch_started_at, SupportRecoveryDelivery.action_id
            )
            .limit(25)
            .with_for_update(skip_locked=True)
        )
        for delivery in interrupted:
            delivery.status = "unknown"
            delivery.dispatch_finished_at = now
        pending = await db.scalar(
            select(SupportRecoveryDelivery)
            .where(SupportRecoveryDelivery.status == "pending")
            .order_by(SupportRecoveryDelivery.created_at, SupportRecoveryDelivery.action_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        action_id = pending.action_id if pending is not None else None
        if pending is not None:
            pending.status = "dispatching"
            pending.dispatch_started_at = now
        await db.commit()
        return action_id


async def _deliver(action_id: UUID, origin: str, settings: Settings) -> None:
    async with AsyncSessionLocal() as db:
        queued = await db.get(SupportRecoveryDelivery, action_id)
        action = await db.get(SupportBusinessAction, action_id)
        if queued is None or action is None:
            return
        challenge_id = queued.challenge_id
        address = None
        code = None
        target_id: UUID | None = None
        try:
            # Use the same lock order as account actions and authentication.
            target = await SupportBusinessActions(db).lock_recovery_delivery_target(action)
            target_id = target.id
            challenge = await AuthRepository(db).get_otp_challenge(challenge_id, for_update=True)
            code = support_recovery_otp(settings, challenge_id)
            digest = support_recovery_otp_digest(settings, challenge_id, code) if code else None
            operator_mailboxes = {
                mailbox.strip().casefold()
                for mailbox in settings.support_email_otp_recipients.values()
            }
            if (
                challenge is not None and challenge.purpose == "support_password_reset"
                and challenge.user_id == target.id and challenge.consumed_at is None
                and challenge.expires_at > utc_now() and digest is not None
                and compare_digest(challenge.otp_hash, digest)
                and target.email.strip().casefold() not in operator_mailboxes
            ):
                address = target.email
        except AppException:
            pass
        delivery = await db.get(
            SupportRecoveryDelivery, action_id, with_for_update=True, populate_existing=True
        )
        if delivery is None or delivery.status != "dispatching":
            return
        if address is None or code is None or action.expires_at <= utc_now():
            delivery.status = "cancelled"
        else:
            try:
                accepted = await asyncio.to_thread(
                    EmailService().send,
                    recipients=[address],
                    subject="Your Garrisons recovery code",
                    body=(
                        f"Open {origin}/password-reset#recovery={challenge_id}\n\n"
                        f"Your verification code is: {code}\n\n"
                        "If you did not request assisted recovery, contact your administrator."
                    ),
                    allow_fallback=False,
                )
                delivery.status = "accepted" if accepted == 1 else "unknown"
            except Exception:
                # A transport exception cannot prove that the message was not accepted.
                delivery.status = "unknown"
        delivery.dispatch_finished_at = utc_now()
        if target_id is not None and delivery.status in {"accepted", "unknown"}:
            # Record a non-secret notification without OTP, challenge reference, or destination.
            notice = (
                "An approved account recovery code was accepted by the mail provider."
                if delivery.status == "accepted"
                else "An approved account recovery dispatch ended with an unknown transport state."
            )
            db.add(
                Notification(
                    user_id=target_id,
                    title="Account recovery update",
                    body=notice,
                    notification_type="security_alert",
                    reference_type="support_recovery",
                    reference_id=action.id,
                    email_status=delivery.status,
                )
            )
        await db.commit()
        if (
            delivery.status == "unknown"
            and settings.should_send_exception_emails
            and settings.exception_email_recipients_list
        ):
            try:
                await asyncio.to_thread(
                    EmailService().send,
                    recipients=settings.exception_email_recipients_list,
                    subject="Support recovery delivery outcome unknown",
                    body=(
                        f"Support recovery action {action.id} ended in an unknown delivery state. "
                        "Review delivery status before manual intervention; do not resend codes."
                    ),
                    allow_fallback=False,
                )
            except Exception:
                pass


async def dispatch_recovery_deliveries() -> int:
    settings = get_settings()
    origin = _portal_origin(settings)
    if origin is None:
        return 0
    processed = 0
    for _ in range(8):
        action_id = await _claim()
        if action_id is None:
            break
        await _deliver(action_id, origin, settings)
        processed += 1
    return processed


@celery_app.task(name="dispatch_support_recovery_deliveries", queue="email")
def dispatch_support_recovery_deliveries() -> int:
    return run_async_task(dispatch_recovery_deliveries())
