import smtplib
from email.message import EmailMessage

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
