import smtplib
from email.message import EmailMessage

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)


class EmailService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send(self, *, recipients: list[str], subject: str, body: str) -> int:
        if not recipients:
            raise ValueError("At least one recipient is required")

        if self.settings.app_env.lower() == "staging":
            subject = f"[Testing] {subject}"

        if self.settings.usesend_api_url is not None or self.settings.usesend_api_key is not None:
            return self._send_usesend(recipients=recipients, subject=subject, body=body)

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
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            logger.warning(
                "email_delivery_failed",
                recipients=len(recipients),
                subject=subject,
                error=str(exc),
            )
            return 0

        return len(recipients)

    def _send_usesend(self, *, recipients: list[str], subject: str, body: str) -> int:
        url = self.settings.usesend_api_url
        key = self.settings.usesend_api_key
        if url is None or url.scheme != "https" or key is None or not key.get_secret_value():
            logger.warning("usesend_configuration_invalid")
            return 0

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
            return 0
        except httpx.RequestError as exc:
            logger.warning("usesend_delivery_failed", error_type=type(exc).__name__)
            return 0

        return len(recipients)
