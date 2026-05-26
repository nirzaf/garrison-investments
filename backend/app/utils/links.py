from urllib.parse import urlencode
from uuid import UUID

from app.config import get_settings


def build_frontend_url(path: str, *, query: dict[str, str | None] | None = None) -> str | None:
    base_url = get_settings().normalized_frontend_base_url
    if not base_url:
        return None

    normalized_path = path if path.startswith("/") else f"/{path}"
    if not query:
        return f"{base_url}{normalized_path}"

    encoded_query = urlencode({key: value for key, value in query.items() if value})
    if not encoded_query:
        return f"{base_url}{normalized_path}"
    return f"{base_url}{normalized_path}?{encoded_query}"


def approval_inbox_url(
    *,
    tab: str,
    approval_id: UUID | None = None,
    report_id: UUID | None = None,
) -> str | None:
    return build_frontend_url(
        "/approvals",
        query={
            "tab": tab,
            "approvalId": str(approval_id) if approval_id else None,
            "reportId": str(report_id) if report_id else None,
        },
    )


def daily_report_url(report_id: UUID) -> str | None:
    return build_frontend_url("/reports/daily", query={"reportId": str(report_id)})


def document_url(document_id: UUID, *, version_id: UUID | None = None) -> str | None:
    return build_frontend_url(
        "/documents",
        query={
            "documentId": str(document_id),
            "versionId": str(version_id) if version_id else None,
        },
    )


def finance_invoice_url(invoice_id: UUID) -> str | None:
    return build_frontend_url("/finance", query={"invoiceId": str(invoice_id)})


def material_request_url(request_id: UUID) -> str | None:
    return build_frontend_url("/materials", query={"materialRequestId": str(request_id)})


def append_link(body: str, *, label: str, url: str | None) -> str:
    if not url:
        return body
    return f"{body}\n\n{label}: {url}"
