import smtplib
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import HttpUrl, SecretStr

from app.config import Settings
from app.services.email_service import EmailDeliveryError, EmailService


@pytest.mark.parametrize("status", [200, 401])
def test_usesend_sends_text_and_checks_provider_response(status: int) -> None:
    endpoint = "https://mail.example.com/api/v1/emails"
    with patch(
        "app.services.email_service.get_settings",
        return_value=Settings(
            usesend_api_url=HttpUrl(endpoint),
            usesend_api_key=SecretStr("test-key"),
            smtp_from_email="mail@example.com",
        ),
    ):
        service = EmailService()
    response = httpx.Response(status, request=httpx.Request("POST", endpoint))
    with patch("app.services.email_service.httpx.post", return_value=response) as post:
        if status == 200:
            assert (
                service.send(recipients=["test@example.com"], subject="Subject", body="Body") == 1
            )
        else:
            with pytest.raises(EmailDeliveryError, match="useSend rejected"):
                service.send(recipients=["test@example.com"], subject="Subject", body="Body")

    post.assert_called_once_with(
        endpoint,
        headers={"Authorization": "Bearer test-key"},
        json={
            "from": "mail@example.com",
            "to": ["test@example.com"],
            "subject": "Subject",
            "text": "Body",
        },
        timeout=10,
    )


def test_usesend_never_sends_key_to_unencrypted_endpoint() -> None:
    settings = Settings(
        usesend_api_url=HttpUrl("http://mail.example.com/api/v1/emails"),
        usesend_api_key=SecretStr("test-key"),
    )
    with patch("app.services.email_service.get_settings", return_value=settings):
        service = EmailService()
    post = Mock()
    with patch("app.services.email_service.httpx.post", post):
        with pytest.raises(EmailDeliveryError, match="useSend is not configured"):
            service.send(recipients=["test@example.com"], subject="Subject", body="Body")
    post.assert_not_called()


def test_smtp_failure_raises_a_transport_error() -> None:
    with (
        patch(
            "app.services.email_service.get_settings",
            return_value=Settings(usesend_api_url=None, usesend_api_key=None),
        ),
        patch(
            "app.services.email_service.smtplib.SMTP",
            side_effect=smtplib.SMTPConnectError(421, b"Service unavailable"),
        ),
        pytest.raises(EmailDeliveryError, match="SMTP delivery failed"),
    ):
        EmailService().send(recipients=["test@example.com"], subject="Subject", body="Body")
