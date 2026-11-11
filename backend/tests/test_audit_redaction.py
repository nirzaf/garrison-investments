from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_service import AuditService


@pytest.mark.asyncio
async def test_audit_payloads_redact_nested_credentials() -> None:
    session = MagicMock(spec=AsyncSession)
    old_values = {"profile": {"refresh_token": "old-secret", "name": "Test User"}}
    await AuditService(session).record(
        action="users.updated",
        comments="Provider response: access_token=example-secret",
        old_values=old_values,
        new_values={"new_password": "new-secret"},
        context_payload={"details": [{"otp_code": "123456"}]},
    )

    record = session.add.call_args.args[0]
    assert record.old_values == {"profile": {"refresh_token": "[redacted]", "name": "Test User"}}
    assert record.new_values == {"new_password": "[redacted]"}
    assert record.context_payload["details"] == [{"otp_code": "[redacted]"}]
    assert record.comments == "Provider response: access_token=[redacted]"
    assert old_values["profile"]["refresh_token"] == "old-secret"
