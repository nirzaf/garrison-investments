import importlib
import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

from app.models.document import Document, DocumentVersion
from app.models.photo import Photo
from app.models.user import User
from app.services.document_service import MAX_DOCUMENT_SIZE, DocumentService
from app.services.finance_service import MAX_INVOICE_FILE_SIZE, FinanceService
from app.services.import_service import ImportService
from app.tasks.maintenance import _business_now
from app.utils.exceptions import AppException, NotFoundException

pil_module = ModuleType("PIL")
pil_image_module = ModuleType("PIL.Image")
pil_image_draw_module = ModuleType("PIL.ImageDraw")
pil_image_module.open = lambda *_args, **_kwargs: None
pil_image_draw_module.Draw = lambda *_args, **_kwargs: SimpleNamespace(text=lambda *_a, **_k: None)
pil_module.Image = pil_image_module
pil_module.ImageDraw = pil_image_draw_module
sys.modules.setdefault("PIL", pil_module)
sys.modules.setdefault("PIL.Image", pil_image_module)
sys.modules.setdefault("PIL.ImageDraw", pil_image_draw_module)

photo_service_module = importlib.import_module("app.services.photo_service")
MAX_FILE_SIZE = photo_service_module.MAX_FILE_SIZE
PhotoService = photo_service_module.PhotoService


def error_messages(errors) -> set[tuple[int, str, str]]:
    return {(error.row, error.field, error.message) for error in errors}


def test_import_validation_reports_missing_columns_and_required_values() -> None:
    service = ImportService.__new__(ImportService)

    errors = service._validate_rows("projects", [{"code": "PRJ-001", "name": ""}])

    messages = error_messages(errors)
    assert (1, "location", "Required column missing.") in messages
    assert (2, "name", "Value is required.") in messages
    assert (2, "scope_of_work", "Value is required.") in messages


@pytest.mark.parametrize(
    ("template_type", "row", "expected_error"),
    [
        (
            "projects",
            {
                "code": "PRJ-001",
                "name": "Project",
                "location": "Doha",
                "scope_of_work": "Fit out",
                "status": "active",
                "budget_amount": "ten",
                "start_date": "2026-01-01",
                "target_end_date": "2026-12-31",
                "client_name": "Client",
                "contract_number": "CON-001",
            },
            (2, "budget_amount", "Must be a number."),
        ),
        (
            "projects",
            {
                "code": "PRJ-001",
                "name": "Project",
                "location": "Doha",
                "scope_of_work": "Fit out",
                "status": "active",
                "budget_amount": "10",
                "start_date": "01-01-2026",
                "target_end_date": "2026-12-31",
                "client_name": "Client",
                "contract_number": "CON-001",
            },
            (2, "start_date", "Must be an ISO date in YYYY-MM-DD format."),
        ),
        (
            "opening_stock",
            {"item_code": "CEM-001", "location_code": "WH-001", "quantity": "-1", "notes": ""},
            (2, "quantity", "Must be positive number."),
        ),
    ],
)
def test_import_validation_rejects_malformed_numbers_dates_and_quantities(
    template_type: str,
    row: dict[str, str],
    expected_error: tuple[int, str, str],
) -> None:
    service = ImportService.__new__(ImportService)

    errors = service._validate_rows(template_type, [row])

    assert expected_error in error_messages(errors)


def test_import_parse_rejects_unknown_template_before_reading_content() -> None:
    service = ImportService.__new__(ImportService)

    with pytest.raises(AppException) as exc_info:
        service._parse("unknown", b"")

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "IMPORT_UNKNOWN"


@pytest.mark.parametrize(
    ("cell_reference", "expected_index"),
    [("A1", 0), ("Z2", 25), ("AA10", 26), ("AZ4", 51), ("BA12", 52), ("", 0)],
)
def test_xlsx_column_index_handles_single_and_multi_letter_columns(
    cell_reference: str,
    expected_index: int,
) -> None:
    service = ImportService.__new__(ImportService)

    assert service._xlsx_column_index(cell_reference) == expected_index


@pytest.mark.parametrize(
    ("filename", "data", "expected_mime"),
    [
        ("drawing.pdf", b"%PDF-1.4\nbody", "application/pdf"),
        ("photo.jpg", b"\xff\xd8\xff\xe0body", "image/jpeg"),
        ("scan.png", b"\x89PNG\r\n\x1a\nbody", "image/png"),
    ],
)
def test_document_file_validation_accepts_supported_magic_signatures(
    filename: str,
    data: bytes,
    expected_mime: str,
) -> None:
    service = DocumentService.__new__(DocumentService)

    assert service._validate_file(filename, data) == expected_mime


@pytest.mark.parametrize(
    ("filename", "data", "expected_status", "expected_message"),
    [
        ("tool.sh", b"#!/bin/sh", 422, "File type is blocked."),
        ("notes.txt", b"plain text", 422, "Unsupported document type."),
        ("huge.pdf", b"%PDF-" + b"x" * MAX_DOCUMENT_SIZE, 413, "Document exceeds the 60 MB limit."),
    ],
)
def test_document_file_validation_rejects_blocked_unsupported_and_oversized_files(
    filename: str,
    data: bytes,
    expected_status: int,
    expected_message: str,
) -> None:
    service = DocumentService.__new__(DocumentService)

    with pytest.raises(AppException) as exc_info:
        service._validate_file(filename, data)

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.message == expected_message


def test_document_select_version_returns_explicit_version_even_when_superseded() -> None:
    service = DocumentService.__new__(DocumentService)
    old_version = DocumentVersion(id=uuid4(), version=1, status="superseded")
    active_version = DocumentVersion(id=uuid4(), version=2, status="active")
    document = Document(active_version=2)
    document.versions = [old_version, active_version]

    assert service._select_version(document, old_version.id) is old_version
    assert service._select_version(document, None) is active_version


def test_document_select_version_raises_when_active_version_is_missing() -> None:
    service = DocumentService.__new__(DocumentService)
    document = Document(active_version=3)
    document.versions = [DocumentVersion(id=uuid4(), version=1, status="superseded")]

    with pytest.raises(NotFoundException) as exc_info:
        service._select_version(document, None)

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "DOCUMENT VERSION_NOT_FOUND"


@pytest.mark.parametrize(
    ("kind", "filename", "data", "expected_mime"),
    [
        ("photo", "site.jpg", b"\xff\xd8\xff\xe0body", "image/jpeg"),
        ("photo", "site.png", b"\x89PNG\r\n\x1a\nbody", "image/png"),
        ("attachment", "report.pdf", b"%PDF-1.4\nbody", "application/pdf"),
        ("photo", "capture.heic", b"xxxxftypheicbody", "image/heic"),
    ],
)
def test_photo_file_validation_accepts_supported_photo_and_attachment_types(
    kind: str,
    filename: str,
    data: bytes,
    expected_mime: str,
) -> None:
    service = PhotoService.__new__(PhotoService)

    assert service._validate_file(filename, data, kind) == expected_mime


@pytest.mark.parametrize(
    ("kind", "filename", "data", "expected_code"),
    [
        ("photo", "report.pdf", b"%PDF-1.4\nbody", "UNSUPPORTED_PHOTO_TYPE"),
        ("attachment", "capture.heic", b"xxxxftypheicbody", "UNSUPPORTED_ATTACHMENT_TYPE"),
        ("attachment", "script.py", b"print('bad')", "BLOCKED_FILE_TYPE"),
        ("photo", "huge.jpg", b"\xff\xd8\xff" + b"x" * MAX_FILE_SIZE, "FILE_TOO_LARGE"),
        ("photo", "unknown.bin", b"not a supported file", "UNSUPPORTED_FILE_TYPE"),
    ],
)
def test_photo_file_validation_rejects_wrong_kind_blocked_and_oversized_files(
    kind: str,
    filename: str,
    data: bytes,
    expected_code: str,
) -> None:
    service = PhotoService.__new__(PhotoService)

    with pytest.raises(AppException) as exc_info:
        service._validate_file(filename, data, kind)

    assert exc_info.value.error_code == expected_code


@pytest.mark.parametrize(
    ("kind", "filename", "expected_kind"),
    [(" PHOTO ", "site.jpg", "photo"), ("photo", "report.pdf", "attachment")],
)
def test_photo_kind_validation_normalizes_and_forces_pdf_to_attachment(
    kind: str,
    filename: str,
    expected_kind: str,
) -> None:
    service = PhotoService.__new__(PhotoService)

    assert service._validate_kind(kind, filename) == expected_kind


def test_photo_kind_validation_rejects_unknown_kind() -> None:
    service = PhotoService.__new__(PhotoService)

    with pytest.raises(AppException) as exc_info:
        service._validate_kind("avatar", "site.jpg")

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "INVALID_FILE_KIND"


@pytest.mark.parametrize(
    "entity_type",
    ["daily_report", "project", "supervisor_update", "document"],
)
def test_photo_entity_type_validation_accepts_supported_owners(entity_type: str) -> None:
    service = PhotoService.__new__(PhotoService)

    service._validate_entity_type(entity_type)


def test_photo_entity_type_validation_rejects_unknown_owner() -> None:
    service = PhotoService.__new__(PhotoService)

    with pytest.raises(AppException) as exc_info:
        service._validate_entity_type("invoice")

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "INVALID_ENTITY_TYPE"


def test_photo_object_key_prefers_requested_variant_when_available() -> None:
    service = PhotoService.__new__(PhotoService)
    photo = Photo(
        storage_path="original.jpg",
        compressed_path="display.jpg",
        thumbnail_path="thumb.jpg",
    )

    assert service._object_key_for_variant(photo, "thumbnail") == "thumb.jpg"
    assert service._object_key_for_variant(photo, "display") == "display.jpg"
    assert service._object_key_for_variant(photo, "original") == "original.jpg"


def test_photo_object_key_falls_back_to_original_when_variant_missing() -> None:
    service = PhotoService.__new__(PhotoService)
    photo = Photo(storage_path="original.pdf", compressed_path=None, thumbnail_path=None)

    assert service._object_key_for_variant(photo, "thumbnail") == "original.pdf"
    assert service._object_key_for_variant(photo, "display") == "original.pdf"


def test_finance_access_rejects_non_finance_roles() -> None:
    service = FinanceService.__new__(FinanceService)

    with pytest.raises(AppException) as exc_info:
        service.ensure_finance_access(User(role="civil_engineer"))

    assert exc_info.value.status_code == 403
    assert exc_info.value.error_code == "FINANCE_FORBIDDEN"


@pytest.mark.parametrize(
    "role",
    ["admin", "accounts", "operation_manager", "general_manager", "project_manager"],
)
def test_finance_access_allows_finance_roles(role: str) -> None:
    service = FinanceService.__new__(FinanceService)

    service.ensure_finance_access(User(role=role))


@pytest.mark.parametrize(
    ("filename", "data", "expected_mime"),
    [
        ("invoice.pdf", b"%PDF-1.4\nbody", "application/pdf"),
        ("invoice.jpg", b"\xff\xd8\xff\xe0body", "image/jpeg"),
        ("invoice.png", b"\x89PNG\r\n\x1a\nbody", "image/png"),
    ],
)
def test_finance_attachment_validation_accepts_supported_files(
    filename: str,
    data: bytes,
    expected_mime: str,
) -> None:
    service = FinanceService.__new__(FinanceService)

    assert service._validate_file(filename, data) == expected_mime


@pytest.mark.parametrize(
    ("filename", "data", "expected_status", "expected_message"),
    [
        ("invoice.exe", b"MZ", 422, "File type is blocked."),
        ("invoice.txt", b"plain text", 422, "Unsupported invoice attachment type."),
        ("huge.pdf", b"%PDF-" + b"x" * MAX_INVOICE_FILE_SIZE, 413, "File exceeds the 10 MB limit."),
    ],
)
def test_finance_attachment_validation_rejects_blocked_unsupported_and_oversized_files(
    filename: str,
    data: bytes,
    expected_status: int,
    expected_message: str,
) -> None:
    service = FinanceService.__new__(FinanceService)

    with pytest.raises(AppException) as exc_info:
        service._validate_file(filename, data)

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.message == expected_message


def test_business_now_falls_back_to_utc_when_timezone_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = datetime(2026, 5, 30, 7, 15, tzinfo=UTC)
    monkeypatch.setattr("app.tasks.maintenance.utc_now", lambda: frozen)

    assert _business_now("Invalid/Zone") == frozen


def test_business_now_uses_configured_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = datetime(2026, 5, 30, 7, 15, tzinfo=UTC)
    monkeypatch.setattr("app.tasks.maintenance.utc_now", lambda: frozen)

    local_now = _business_now("Asia/Qatar")

    assert local_now.hour == 10
    assert local_now.tzinfo is not None
