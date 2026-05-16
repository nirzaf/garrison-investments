import smtplib
from email.message import EmailMessage

from app.config import get_settings


class EmailService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send(self, *, recipients: list[str], subject: str, body: str) -> int:
        if not recipients:
            raise ValueError("At least one recipient is required")

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{self.settings.smtp_from_name} <{self.settings.smtp_from_email}>"
        message["To"] = ", ".join(recipients)
        message.set_content(body)

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as client:
            if self.settings.smtp_use_tls:
                client.starttls()
            if self.settings.smtp_username and self.settings.smtp_password:
                client.login(self.settings.smtp_username, self.settings.smtp_password)
            client.send_message(message)

        return len(recipients)