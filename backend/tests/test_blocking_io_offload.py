"""H7: blocking storage, image and PDF work must run off the event loop thread.

Each test drives the real service orchestration and only replaces the blocking leaf
(the network call or the CPU-bound renderer) with a recorder, so what is asserted is
which thread production actually chose, not what a mock returned.
"""

import base64
import binascii
import re
import threading
import zlib
from contextlib import suppress
from dataclasses import dataclass, field
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from fastapi import UploadFile
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from app.database import AsyncSessionLocal, engine
from app.services.analytics_service import AnalyticsService
from app.services.document_service import DocumentService
from app.services.finance_service import FinanceService
from app.services.photo_service import PhotoService
from app.services.report_export_service import ReportExportService
from app.services.supplier_service import SupplierService
from app.tasks.report import _generate_management_export
from app.utils.exceptions import AppException
from tests.test_daily_reports import (
    create_test_client,
    report_payload,
    setup_project_team,
    setup_report_consumption_stock,
    skip_if_database_unavailable,
)
from tests.test_finance import add_invoice, create_project_and_supplier, create_user

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


@dataclass
class Call:
    name: str
    thread_id: int
    args: tuple[Any, ...]


@dataclass
class Recorder:
    calls: list[Call] = field(default_factory=list)

    def stub(self, name: str, result: Any = None):
        recorder = self

        def _stub(_self, *args, **kwargs):
            recorder.calls.append(Call(name, threading.get_ident(), args))
            return result

        return _stub

    def named(self, name: str) -> list[Call]:
        return [call for call in self.calls if call.name == name]


def assert_off_loop(recorder: Recorder, name: str, loop_thread: int, *, times: int = 1) -> None:
    calls = recorder.named(name)
    assert len(calls) == times, f"{name} ran {len(calls)} times, expected {times}"
    on_loop = [call for call in calls if call.thread_id == loop_thread]
    assert not on_loop, f"{name} blocked the event loop thread ({len(on_loop)}/{len(calls)} calls)"


def jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (20, 20), color=(80, 120, 160)).save(buffer, format="JPEG")
    return buffer.getvalue()


def pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def upload_file(name: str, data: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(data),
        filename=name,
        headers=Headers({"content-type": content_type}),
    )


def _inflate(raw: bytes) -> bytes:
    """ReportLab writes streams as ASCII85 then Flate; try both encodings."""
    candidates = [raw]
    stripped = raw.strip()
    if stripped.endswith(b"~>"):
        stripped = stripped[:-2]
    with suppress(ValueError, binascii.Error):
        candidates.append(base64.a85decode(stripped))
    for candidate in candidates:
        with suppress(zlib.error):
            return zlib.decompress(candidate)
    return raw


def pdf_text(data: bytes) -> str:
    """Return the searchable text of a PDF, inflating compressed streams if present."""
    chunks = [data]
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.DOTALL):
        chunks.append(_inflate(match.group(1)))
    return b"\n".join(chunks).decode("latin-1")


async def test_photo_upload_offloads_storage_and_image_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    loop_thread = threading.get_ident()
    recorder = Recorder()
    image = jpeg_bytes()
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        monkeypatch.setattr(PhotoService, "_upload_object", recorder.stub("_upload_object"))
        monkeypatch.setattr(
            PhotoService,
            "_create_photo_variants",
            recorder.stub("_create_photo_variants", (image, image, 20, 20)),
        )
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        response = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report["id"], "kind": "photo"},
            files={"files": ("site.jpg", image, "image/jpeg")},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

    assert response.status_code == 201
    assert_off_loop(recorder, "_upload_object", loop_thread, times=3)
    assert_off_loop(recorder, "_create_photo_variants", loop_thread)


async def test_report_pdf_build_upload_and_download_offload_without_orm_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    loop_thread = threading.get_ident()
    recorder = Recorder()
    stored: dict[str, bytes] = {}
    real_build_pdf = ReportExportService.build_pdf

    def build_pdf(self, data):
        recorder.calls.append(Call("build_pdf", threading.get_ident(), (data,)))
        return real_build_pdf(self, data)

    def upload_pdf(self, object_key, data):
        recorder.calls.append(Call("_upload_pdf", threading.get_ident(), (object_key, data)))
        stored["pdf"] = data

    def download_pdf(self, object_key):
        recorder.calls.append(Call("_download_pdf", threading.get_ident(), (object_key,)))
        return stored["pdf"]

    monkeypatch.setattr(ReportExportService, "build_pdf", build_pdf)
    monkeypatch.setattr(ReportExportService, "_upload_pdf", upload_pdf)
    monkeypatch.setattr(ReportExportService, "_download_pdf", download_pdf)

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        stock = await setup_report_consumption_stock(
            client, setup["project_id"], setup["op_token"]
        )
        payload = report_payload(setup["project_id"], setup["supervisor_update_id"])
        payload["material_consumption"][0]["material_name"] = stock["item_name"]
        payload["material_consumption"][0]["unit"] = "m2"
        report = (
            await client.post(
                "/api/v1/reports",
                json=payload,
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        await client.post(
            f"/api/v1/reports/{report['id']}/submit",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        approved = (
            await client.post(
                f"/api/v1/reports/{report['id']}/approve",
                json={"comments": "Ready for archive.", "target_covered": True},
                headers={"Authorization": f"Bearer {setup['manager_token']}"},
            )
        ).json()
        response = await client.get(
            f"/api/v1/reports/{approved['id']}/pdf",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert_off_loop(recorder, "build_pdf", loop_thread)
    assert_off_loop(recorder, "_upload_pdf", loop_thread)
    assert_off_loop(recorder, "_download_pdf", loop_thread)

    rendered = recorder.named("build_pdf")[0].args[0]
    assert not hasattr(rendered, "_sa_instance_state"), "an ORM object crossed into the worker"
    assert not isinstance(rendered, AsyncSession), "the session crossed into the worker"

    # The snapshot refactor must not drop any report content from the printed PDF.
    text = pdf_text(response.content)
    for expected in ("Zone A", "Mason", "Excavator", "Concrete", approved["report_number"]):
        assert expected in text, f"{expected!r} missing from the rendered PDF"


async def test_invoice_attachment_write_is_denied_before_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    recorder = Recorder()
    monkeypatch.setattr(FinanceService, "_upload_object", recorder.stub("_upload_object"))
    admin, _ = await create_user("managing_director")
    project, _supplier = await create_project_and_supplier(admin)
    invoice = await add_invoice(project, Decimal("300.00"))

    async with AsyncSessionLocal() as session:
        with pytest.raises(AppException) as excinfo:
            await FinanceService(session).upload_invoice_attachment(
                invoice.id, upload_file("invoice.pdf", pdf_bytes(), "application/pdf"), admin
            )

    assert excinfo.value.status_code == 403
    assert excinfo.value.error_code == "FINANCE_WRITE_FORBIDDEN"
    assert recorder.named("_upload_object") == []


async def test_supplier_tds_upload_offloads_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    await skip_if_database_unavailable()
    loop_thread = threading.get_ident()
    recorder = Recorder()
    monkeypatch.setattr(SupplierService, "_upload_object", recorder.stub("_upload_object"))
    admin, _ = await create_user("managing_director")
    _project, supplier = await create_project_and_supplier(admin)

    async with AsyncSessionLocal() as session:
        updated = await SupplierService(session).upload_tds_document(
            supplier.id, upload_file("tds.pdf", pdf_bytes(), "application/pdf"), admin
        )

    assert updated.tds_document_key
    assert_off_loop(recorder, "_upload_object", loop_thread)


async def test_document_upload_offloads_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    await skip_if_database_unavailable()
    loop_thread = threading.get_ident()
    recorder = Recorder()
    monkeypatch.setattr(DocumentService, "_upload_object", recorder.stub("_upload_object"))
    admin, _ = await create_user("managing_director")

    async with AsyncSessionLocal() as session:
        document = await DocumentService(session).upload_document(
            title=f"Method Statement {threading.get_ident()}",
            document_type="method_statement",
            project_id=None,
            expiry_date=None,
            file=upload_file("method.pdf", pdf_bytes(), "application/pdf"),
            actor=admin,
        )

    assert document.status == "pending_approval"
    assert_off_loop(recorder, "_upload_object", loop_thread)


async def test_management_export_upload_offloads_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    loop_thread = threading.get_ident()
    recorder = Recorder()

    async def project_progress_export(self, actor, **kwargs):
        return b"workbook-bytes"

    monkeypatch.setattr(AnalyticsService, "project_progress_export", project_progress_export)
    monkeypatch.setattr(
        AnalyticsService, "upload_export", recorder.stub("upload_export", "exports/key")
    )
    admin, _ = await create_user("managing_director")

    object_key = await _generate_management_export("project-progress", str(admin.id), {})

    assert object_key == "exports/key"
    assert_off_loop(recorder, "upload_export", loop_thread)
