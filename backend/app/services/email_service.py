import re
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)


class EmailDeliveryError(RuntimeError):
    """The configured transport did not accept the message."""


class EmailService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send(
        self, *, recipients: list[str], subject: str, body: str, allow_fallback: bool = True
    ) -> int:
        if not recipients:
            raise ValueError("At least one recipient is required")

        if self.settings.app_env.lower() == "staging":
            subject = f"[Testing] {subject}"

        try:
            if (
                self.settings.usesend_api_url is not None
                or self.settings.usesend_api_key is not None
            ):
                return self._send_usesend(recipients=recipients, subject=subject, body=body)
            refused = self._send_smtp(recipients=recipients, subject=subject, body=body)
        except EmailDeliveryError:
            if not allow_fallback or not self._cloudflare_configured():
                raise
            return self._send_cloudflare(recipients=recipients, subject=subject, body=body)

        accepted = len(recipients) - len(refused)
        if refused:
            logger.warning("email_recipients_refused", refused=len(refused), accepted=accepted)
            if allow_fallback and self._cloudflare_configured():
                try:
                    accepted += self._send_cloudflare(
                        recipients=refused, subject=subject, body=body
                    )
                except EmailDeliveryError:
                    if not accepted:
                        raise
        if not accepted:
            raise EmailDeliveryError("SMTP refused all recipients.")
        return accepted

    def _cloudflare_configured(self) -> bool:
        account = self.settings.cloudflare_email_account_id
        token = self.settings.cloudflare_email_api_token
        return bool(
            account
            and re.fullmatch(r"[0-9a-fA-F]{32}", account)
            and token
            and token.get_secret_value().strip()
        )

    def _send_smtp(self, *, recipients: list[str], subject: str, body: str) -> list[str]:

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{self.settings.smtp_from_name} <{self.settings.smtp_from_email}>"
        message["To"] = ", ".join(recipients)
        message.set_content(body)

        try:
            with smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=10,
            ) as client:
                if self.settings.smtp_use_tls:
                    client.starttls()
                if self.settings.smtp_username and self.settings.smtp_password:
                    client.login(self.settings.smtp_username, self.settings.smtp_password)
                refused = client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            logger.warning(
                "email_delivery_failed",
                recipients=len(recipients),
                error_type=type(exc).__name__,
            )
            raise EmailDeliveryError("SMTP delivery failed.") from None

        refused_addresses = {address.casefold() for address in refused}
        return [
            address
            for address in recipients
            if parseaddr(address)[1].casefold() in refused_addresses
        ]

    def _send_cloudflare(self, *, recipients: list[str], subject: str, body: str) -> int:
        account = self.settings.cloudflare_email_account_id
        token = self.settings.cloudflare_email_api_token
        assert account is not None and token is not None
        url = f"https://api.cloudflare.com/client/v4/accounts/{account}/email/sending/send"
        accepted = 0
        for start in range(0, len(recipients), 50):
            batch = [parseaddr(address)[1] for address in recipients[start : start + 50]]
            try:
                response = httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {token.get_secret_value()}"},
                    json={
                        "from": {
                            "address": self.settings.cloudflare_email_from
                            or self.settings.smtp_from_email,
                            "name": self.settings.smtp_from_name,
                        },
                        "to": batch,
                        "subject": subject,
                        "text": body,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("success") is not True:
                    raise ValueError("Cloudflare did not accept the request")
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise ValueError("Cloudflare did not return recipient results")
                delivered, queued = result.get("delivered", []), result.get("queued", [])
                if not isinstance(delivered, list) or not isinstance(queued, list):
                    raise ValueError("Invalid Cloudflare recipient results")
                accepted_addresses = {
                    item.casefold() for item in delivered + queued if isinstance(item, str)
                }
                accepted += sum(address.casefold() in accepted_addresses for address in batch)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("cloudflare_email_delivery_failed", error_type=type(exc).__name__)
        if not accepted:
            raise EmailDeliveryError("Cloudflare Email Sending accepted no recipients.")
        logger.info(
            "cloudflare_email_fallback_accepted", accepted=accepted, recipients=len(recipients)
        )
        return accepted

    def _send_usesend(self, *, recipients: list[str], subject: str, body: str) -> int:
        url = self.settings.usesend_api_url
        key = self.settings.usesend_api_key
        if url is None or url.scheme != "https" or key is None or not key.get_secret_value():
            logger.warning("usesend_configuration_invalid")
            raise EmailDeliveryError("useSend is not configured correctly.")

        try:
            response = httpx.post(
                str(url),
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                json={
                    "from": self.settings.smtp_from_email,
                    "to": recipients,
                    "subject": subject,
                    "text": body,
                },
                timeout=10,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("usesend_delivery_failed", status_code=exc.response.status_code)
            raise EmailDeliveryError("useSend rejected the message.") from None
        except httpx.RequestError as exc:
            logger.warning("usesend_delivery_failed", error_type=type(exc).__name__)
            raise EmailDeliveryError("useSend could not be reached.") from None

        return len(recipients)
