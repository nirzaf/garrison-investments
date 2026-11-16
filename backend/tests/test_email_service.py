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


@pytest.mark.parametrize("failure", ["request", "status", "timeout", "none"])
def test_cloudflare_fallback_after_usesend_failure(failure: str) -> None:
    endpoint = "https://mail.example.com/api/v1/emails"
    settings = Settings(
        usesend_api_url=HttpUrl(endpoint) if failure != "none" else None,
        usesend_api_key=SecretStr("primary-token"),
        cloudflare_email_account_id="a" * 32,
        cloudflare_email_api_token=SecretStr("fallback-token"),
        cloudflare_email_from="mailservice@send.example.com",
    )
    recipient = "receiver@example.com"
    url = f"https://api.cloudflare.com/client/v4/accounts/{'a' * 32}/email/sending/send"
    success = httpx.Response(
        200,
        json={"success": True, "result": {"queued": [recipient]}},
        request=httpx.Request("POST", url),
    )
    failures = {
        "request": httpx.ConnectError("unavailable"),
        "status": httpx.Response(403, request=httpx.Request("POST", endpoint)),
        "timeout": httpx.ReadTimeout("response timed out"),
    }
    responses = [failures[failure], success] if failure in failures else [success]
    with (
        patch("app.services.email_service.get_settings", return_value=settings),
        patch("app.services.email_service.httpx.post", side_effect=responses) as post,
    ):
        assert EmailService().send(recipients=[recipient], subject="Subject", body="Body") == 1
    assert post.call_count == len(responses)
    assert post.call_args.args == (url,)
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer fallback-token"}
    assert post.call_args.kwargs["json"] == {
        "from": {"address": "mailservice@send.example.com", "name": "Garrisons Investments"},
        "to": [recipient],
        "subject": "Subject",
        "text": "Body",
    }


@pytest.mark.parametrize("fallback_accepts", [True, False])
def test_smtp_partial_refusal_falls_back_only_for_refused_recipient(fallback_accepts: bool) -> None:
    settings = Settings(
        usesend_api_url=None,
        usesend_api_key=None,
        cloudflare_email_account_id="b" * 32,
        cloudflare_email_api_token=SecretStr("fallback-token"),
    )
    refused = "second@example.com"
    response = httpx.Response(
        200,
        json={
            "success": True,
            "result": {
                "delivered": [refused] if fallback_accepts else [],
                "permanent_bounces": [] if fallback_accepts else [refused],
            },
        },
        request=httpx.Request("POST", "https://api.cloudflare.com"),
    )
    with (
        patch("app.services.email_service.get_settings", return_value=settings),
        patch("app.services.email_service.smtplib.SMTP") as smtp,
        patch("app.services.email_service.httpx.post", return_value=response) as post,
    ):
        smtp.return_value.__enter__.return_value.send_message.return_value = {refused: (550, b"No")}
        assert EmailService().send(
            recipients=["first@example.com", refused], subject="Subject", body="Body"
        ) == (2 if fallback_accepts else 1)
    assert post.call_args.kwargs["json"]["to"] == [refused]


def test_cloudflare_rejects_provider_failure_even_with_http_200() -> None:
    settings = Settings(
        usesend_api_url=None,
        usesend_api_key=None,
        cloudflare_email_account_id="c" * 32,
        cloudflare_email_api_token=SecretStr("fallback-token"),
    )
    response = httpx.Response(
        200, json={"success": False}, request=httpx.Request("POST", "https://api.cloudflare.com")
    )
    with (
        patch("app.services.email_service.get_settings", return_value=settings),
        patch("app.services.email_service.smtplib.SMTP", side_effect=OSError()),
        patch("app.services.email_service.httpx.post", return_value=response),
        pytest.raises(EmailDeliveryError, match="Cloudflare Email Sending accepted no recipients"),
    ):
        EmailService().send(recipients=["test@example.com"], subject="Subject", body="Body")
