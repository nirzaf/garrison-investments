from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from app.config import Settings, get_settings
from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.approval import Approval
from app.models.auth import AuthOtpChallenge
from app.models.document import Document, DocumentVersion
from app.models.finance import Invoice
from app.models.hr import HrEmployee, HrOnboardingCase, HrPayrollPolicy
from app.models.inventory import (
    InventoryItem,
    InventoryLocationStock,
    InventoryMovement,
    MaterialRequest,
    StorageLocation,
)
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_milestone import ProjectMilestone
from app.models.project_task import ProjectTask
from app.models.supplier import Supplier
from app.models.support_business_actions import (
    SupportBusinessAction,
    SupportBusinessApproval,
    SupportRecoveryDelivery,
)
from app.models.support_case_actions import SupportCaseProject
from app.models.support_cases import (
    SupportCase,
    SupportCaseMember,
    SupportCaseRequest,
    SupportOperatorGrant,
)
from app.models.support_directory import SupportCaseSubject
from app.models.support_identity import SupportSession
from app.models.support_oversight import SupportBackupReceipt, SupportOversightEvent
from app.models.task_outbox import TaskOutbox
from app.models.user import User
from app.services.email_service import EmailDeliveryError
from app.services.support_overview import suppress_small_cell_buckets
from app.tasks.support_recovery import _portal_origin, dispatch_recovery_deliveries
from app.utils.permissions import ROLE_SITE_SUPERVISOR
from app.utils.recovery_destination import (
    recovery_destination_digest,
    support_recovery_otp,
    support_recovery_otp_digest,
)
from app.utils.security import create_access_token, utc_now
from scripts import garrisonctl
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_custody import login
from tests.test_support_identity import API, client, sign
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool

_OVERSIGHT_CAPS = (
    "overview.company.read",
    "overview.projects.read",
    "overview.workforce.read",
    "overview.inventory.read",
    "overview.suppliers.read",
    "overview.documents.read",
    "overview.finance.read",
    "overview.approvals.read",
    "jobs.read",
    "backups.read",
    "config.read",
    "incidents.read",
    "simulation.start",
)


async def _grant(operator_id: UUID, *capabilities: str) -> None:
    async with AsyncSessionLocal() as session:
        for cap in capabilities:
            session.add(SupportOperatorGrant(operator_id=operator_id, capability=cap))
        await session.commit()


async def _seed_domain_data(operator_id: UUID) -> dict[str, str]:
    now = utc_now()
    today = date.today()
    async with AsyncSessionLocal() as session:
        user = User(
            email=f"oversight-{uuid4().hex[:8]}@example.com",
            full_name="Oversight Seed Director",
            role="managing_director",
            password_hash="synthetic-hash",
        )
        session.add(user)
        await session.flush()

        p_in_case = Project(
            name="Confidential Scoped Project",
            code=f"PRJ-{uuid4().hex[:6]}",
            status="active",
            scope_of_work="Site works",
            target_end_date=today + timedelta(days=30),
            progress_percentage=Decimal("45.00"),
            created_by=user.id,
        )
        p_out_case = Project(
            name="Secret Outside Project",
            code=f"OUT-{uuid4().hex[:6]}",
            status="planning",
            scope_of_work="Other",
            target_end_date=today + timedelta(days=60),
            created_by=user.id,
        )
        session.add_all([p_in_case, p_out_case])
        await session.flush()

        session.add(
            ProjectMilestone(
                project_id=p_in_case.id,
                name="Delayed MS",
                status="in_progress",
                planned_end_date=today - timedelta(days=2),
            )
        )
        session.add(
            ProjectTask(
                project_id=p_in_case.id,
                name="Delayed Task",
                status="in_progress",
                planned_end_date=today - timedelta(days=1),
            )
        )

        # Seed workforce: 6 active on p_in_case + 2 on_probation on p_out_case
        for idx in range(6):
            session.add(
                HrEmployee(
                    employee_code=f"EMP-A-{idx}-{uuid4().hex[:4]}",
                    first_name="Worker",
                    last_name=f"Active{idx}",
                    full_name=f"Worker Active{idx}",
                    employment_status="active",
                    primary_project_id=p_in_case.id,
                )
            )
        for idx in range(2):
            session.add(
                HrEmployee(
                    employee_code=f"EMP-P-{idx}-{uuid4().hex[:4]}",
                    first_name="Worker",
                    last_name=f"Prob{idx}",
                    full_name=f"Worker Prob{idx}",
                    employment_status="on_probation",
                    primary_project_id=p_out_case.id,
                )
            )
        session.add(
            HrOnboardingCase(employee_id=await _first_employee_id(session), start_date=today)
        )
        session.add(
            HrPayrollPolicy(
                code=f"POL-{uuid4().hex[:6]}",
                name="Payroll Policy",
                is_approved=True,
                approved_by_id=user.id,
                second_approved_by_id=None,
            )
        )

        loc = StorageLocation(
            name="Main Site Store",
            code=f"LOC-{uuid4().hex[:4]}",
            location_type="site",
            project_id=p_in_case.id,
            is_active=True,
        )
        item = InventoryItem(
            name="Steel Rebar",
            category="materials",
            item_type="consumable",
            unit="ton",
            minimum_stock=Decimal("10.000"),
            reorder_level=Decimal("15.000"),
            unit_cost=Decimal("98765.43"),
        )
        session.add_all([loc, item])
        await session.flush()
        session.add(
            InventoryLocationStock(
                item_id=item.id,
                location_id=loc.id,
                on_hand_qty=Decimal("5.000"),
                reserved_qty=Decimal("1.000"),
            )
        )
        session.add(
            MaterialRequest(
                request_number=f"MR-{uuid4().hex[:6]}",
                project_id=p_in_case.id,
                requester_id=user.id,
                from_location_id=loc.id,
                status="requested",
                total_estimated_cost=Decimal("55443.21"),
                created_at=now - timedelta(days=10),
            )
        )
        session.add(
            InventoryMovement(
                item_id=item.id,
                movement_type="receipt",
                quantity=Decimal("5.000"),
                to_location_id=loc.id,
                project_id=p_in_case.id,
                handled_by=user.id,
            )
        )

        supplier = Supplier(
            name="Private Steel Co",
            category="materials",
            rating="approved",
            payment_terms="Net 30",
            contact_person="Secret Contact",
            phone="+97455550000",
            email="secret-supplier@example.com",
            address="Doha Industrial",
            tax_registration_number="TIN-SECRET-999",
            tds_expiry_date=today + timedelta(days=10),
            compliance_status="compliant",
            is_active=True,
        )
        session.add(supplier)
        await session.flush()

        doc = Document(
            title="Confidential Method Statement",
            document_type="method_statement",
            project_id=p_in_case.id,
            status="pending_approval",
            metadata_json={},
            expiry_date=today - timedelta(days=3),
            uploaded_by=user.id,
        )
        session.add(doc)
        await session.flush()
        session.add(
            DocumentVersion(
                document_id=doc.id,
                version=1,
                status="pending_approval",
                storage_path="/private/secret-doc-key.pdf",
                original_name="secret-doc.pdf",
                mime_type="application/pdf",
                size_bytes=1234,
                uploaded_by=user.id,
            )
        )

        session.add(
            Invoice(
                invoice_number="INV-SECRET-999",
                project_id=p_in_case.id,
                supplier_id=supplier.id,
                invoice_date=today - timedelta(days=40),
                due_date=today - timedelta(days=5),
                amount=Decimal("43210.00"),
                tax_amount=Decimal("0.00"),
                total_amount=Decimal("43210.00"),
                status="approved",
                payment_status="unpaid",
                created_by=user.id,
            )
        )
        session.add(
            Approval(
                request_type="material_request",
                request_id=uuid4(),
                project_id=p_in_case.id,
                submitter_id=user.id,
                approver_id=user.id,
                status="pending",
                title="Confidential approval comment target",
                submitter_comments="Private approval narrative",
                submitted_at=now - timedelta(days=2),
                due_at=now - timedelta(hours=4),
            )
        )

        case = SupportCase(id=uuid4(), status="investigating")
        req_id = uuid4().hex
        session.add(case)
        await session.flush()
        session.add(SupportCaseMember(case_id=case.id, operator_id=operator_id))
        session.add(SupportCaseProject(case_id=case.id, project_id=p_in_case.id))
        session.add(SupportCaseRequest(case_id=case.id, request_id=req_id))
        session.add(
            ActivityLog(
                request_id=req_id,
                action="http.unhandled_exception",
                event_type="error",
                severity="ERROR",
                entity_type="request",
                status_code=500,
                comments="Secret stack detail",
            )
        )
        session.add(
            ActivityLog(
                request_id=uuid4().hex,
                action="celery.task_failed",
                event_type="error",
                severity="ERROR",
                entity_type="task",
                comments="Secret exception payload token=abc123",
                context_payload={
                    "task_name": "run_database_backup",
                    "args": ["secret-db-arg"],
                    "kwargs": {"secret": "do-not-leak"},
                },
            )
        )
        session.add(
            TaskOutbox(
                dedupe_key=f"outbox-{uuid4().hex}",
                task_name="dispatch_task_outbox",
                args_json=["secret-outbox-arg"],
                kwargs_json={"flag": True},
                status="pending",
                attempts=1,
                created_at=now - timedelta(seconds=90),
            )
        )
        await session.commit()
        return {
            "case_id": str(case.id),
            "project_in": str(p_in_case.id),
            "project_out": str(p_out_case.id),
            "user_id": str(user.id),
        }


async def _first_employee_id(session) -> UUID:
    return UUID(str(await session.scalar(select(HrEmployee.id).limit(1))))


async def _oversight_baselines() -> tuple[dict[str, int], dict[str, int]]:
    now = utc_now()
    async with AsyncSessionLocal() as session:
        active_projects = int(
            await session.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.status == "active", Project.deleted_at.is_(None))
            )
            or 0
        )
        total_projects = int(
            await session.scalar(
                select(func.count()).select_from(Project).where(Project.deleted_at.is_(None))
            )
            or 0
        )
        overdue_approvals = int(
            await session.scalar(
                select(func.count())
                .select_from(Approval)
                .where(
                    Approval.status == "pending",
                    Approval.due_at < now,
                    Approval.deleted_at.is_(None),
                )
            )
            or 0
        )
        status_rows = (
            await session.execute(
                select(HrEmployee.employment_status, func.count().label("cnt"))
                .where(HrEmployee.deleted_at.is_(None))
                .group_by(HrEmployee.employment_status)
            )
        ).all()
        status_counts = {str(row.employment_status): int(row.cnt) for row in status_rows}
        open_onboarding = int(
            await session.scalar(
                select(func.count())
                .select_from(HrOnboardingCase)
                .where(HrOnboardingCase.status != "completed")
            )
            or 0
        )
        return (
            {
                "active_projects": active_projects,
                "total_projects": total_projects,
                "overdue_approvals": overdue_approvals,
                "open_onboarding": open_onboarding,
            },
            status_counts,
        )


def test_suppress_small_cell_buckets_primary_and_complementary() -> None:
    total, total_state, buckets = suppress_small_cell_buckets({"active": 6, "on_probation": 2})
    assert total is None and total_state == "suppressed"
    assert buckets["active"] == (6, "observed")
    assert buckets["on_probation"] == (None, "suppressed")

    total_two, total_two_state, buckets_two = suppress_small_cell_buckets(
        {"active": 6, "on_probation": 2, "suspended": 3}
    )
    assert total_two == 11 and total_two_state == "observed"
    assert buckets_two["on_probation"] == (None, "suppressed")
    assert buckets_two["suspended"] == (None, "suppressed")

    total_exact, total_exact_state, _ = suppress_small_cell_buckets(
        {"active": 5, "on_probation": 0}
    )
    assert total_exact == 5 and total_exact_state == "observed"


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_oversight_authorization_suppression_redaction_and_degraded_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    async with client() as actor, client() as ordinary:
        operator_id, _, _ = await login(actor, custodian=False)
        await login(ordinary, custodian=False)
        baselines, base_status_counts = await _oversight_baselines()
        seeded = await _seed_domain_data(operator_id)
        await _grant(operator_id, *_OVERSIGHT_CAPS)

        # Business user token and unauthenticated caller are denied on support endpoints.
        business_token = create_access_token(UUID(seeded["user_id"]), "managing_director")
        async with client() as biz:
            assert (
                await biz.get(
                    f"{API}/overview",
                    headers={"Authorization": f"Bearer {business_token}"},
                )
            ).status_code == 401
        assert (await ordinary.get(f"{API}/overview")).status_code == 403
        assert (await ordinary.get(f"{API}/overview/finance")).status_code == 403
        assert (await ordinary.get(f"{API}/monitor/jobs")).status_code == 403
        assert (await ordinary.get(f"{API}/monitor/backups")).status_code == 403
        assert (await ordinary.get(f"{API}/config/status")).status_code == 403
        assert (await ordinary.get(f"{API}/incidents/summary")).status_code == 403
        assert (
            await ordinary.get(
                f"{API}/policy/explain",
                params={"role_key": "hr_executive_reader", "permission_key": "reports:view"},
            )
        ).status_code == 403

        # 1. Company overview (delta-checked against shared DB baseline)
        base_active_wf = base_status_counts.get("active", 0) + base_status_counts.get(
            "on_probation", 0
        )
        company = await actor.get(f"{API}/overview")
        assert company.status_code == 200, company.text
        assert company.headers["cache-control"] == "no-store"
        company_metrics = {m["key"]: m for m in company.json()["metrics"]}
        assert company_metrics["active_projects"]["value"] == baselines["active_projects"] + 1
        assert company_metrics["total_projects"]["value"] == baselines["total_projects"] + 2
        assert company_metrics["overdue_approvals"]["value"] == baselines["overdue_approvals"] + 1
        assert company_metrics["active_workforce"]["value"] == base_active_wf + 8

        # 2. Projects overview (company & case scope + negative non-disclosing 404 probing)
        proj = await actor.get(f"{API}/overview/projects")
        assert proj.status_code == 200
        assert "Confidential Scoped Project" not in proj.text
        scoped_proj = await actor.get(
            f"{API}/overview/projects",
            params={"case_id": seeded["case_id"], "project_id": seeded["project_in"]},
        )
        assert scoped_proj.status_code == 200
        assert scoped_proj.json()["case_projects"][0]["label"] == "Project 01"
        assert (
            await actor.get(
                f"{API}/overview/projects",
                params={"case_id": seeded["case_id"], "project_id": seeded["project_out"]},
            )
        ).status_code == 404
        assert (
            await actor.get(
                f"{API}/overview/projects", params={"project_id": seeded["project_in"]}
            )
        ).status_code == 404

        # 3. Workforce strict suppression (<5 primary + single-complement total suppression)
        wf = await actor.get(f"{API}/overview/workforce")
        assert wf.status_code == 200
        wf_body = wf.json()
        wf_metrics = {m["key"]: m for m in wf_body["metrics"]}
        statuses = {row["status"]: row for row in wf_body["by_status"]}
        after_statuses = dict(base_status_counts)
        after_statuses["active"] = after_statuses.get("active", 0) + 6
        after_statuses["on_probation"] = after_statuses.get("on_probation", 0) + 2
        exp_total, exp_total_state, exp_buckets = suppress_small_cell_buckets(after_statuses)
        for status_key, (exp_val, exp_state) in exp_buckets.items():
            assert statuses[status_key] == {
                "status": status_key,
                "count": exp_val,
                "state": exp_state,
            }
        assert wf_metrics["total_employees"]["state"] == exp_total_state
        assert wf_metrics["total_employees"]["value"] == exp_total
        assert any(row["state"] == "suppressed" for row in wf_body["by_project"])
        after_onboarding = baselines["open_onboarding"] + 1
        if 0 < after_onboarding < 5:
            assert wf_metrics["open_onboarding_cases"]["state"] == "suppressed"
        else:
            assert wf_metrics["open_onboarding_cases"]["value"] == after_onboarding
        assert wf_metrics["payroll_access_policy"]["value"] == "blocked"
        assert "Worker Active0" not in wf.text

        # 4. Inventory, suppliers, documents, finance, approvals: no prices/secrets/amounts
        inv = await actor.get(
            f"{API}/overview/inventory", params={"case_id": seeded["case_id"]}
        )
        assert inv.status_code == 200
        assert "98765" not in inv.text and "55443" not in inv.text

        sup = await actor.get(f"{API}/overview/suppliers")
        assert sup.status_code == 200
        assert "TIN-SECRET" not in sup.text and "secret-supplier" not in sup.text

        docs = await actor.get(f"{API}/overview/documents")
        assert docs.status_code == 200
        assert "secret-doc" not in docs.text and "/private/" not in docs.text

        fin = await actor.get(f"{API}/overview/finance")
        assert fin.status_code == 200
        assert fin.json()["finance_writes_policy"] == "blocked"
        assert "43210" not in fin.text and "INV-SECRET" not in fin.text

        appr = await actor.get(f"{API}/overview/approvals")
        assert appr.status_code == 200
        appr_workflows = {row["request_type"]: row for row in appr.json()["by_workflow"]}
        assert appr_workflows["material_request"]["pending"] >= 1
        assert appr_workflows["material_request"]["overdue"] >= 1
        assert "Private approval narrative" not in appr.text

        # 5. Pure static policy explainer (rejects retired hr_executive key)
        explain = await actor.get(
            f"{API}/policy/explain",
            params={"role_key": "hr_executive_reader", "permission_key": "reports:view"},
        )
        assert explain.status_code == 200
        assert explain.json()["allowed"] is False and explain.json()["is_business_role"] is True
        assert (
            await actor.get(
                f"{API}/policy/explain",
                params={"role_key": "hr_executive", "permission_key": "reports:view"},
            )
        ).status_code == 422
        sa_explain = await actor.get(
            f"{API}/policy/explain",
            params={"role_key": "super_admin", "permission_key": "financial:view"},
        )
        assert sa_explain.status_code == 200 and sa_explain.json()["is_business_role"] is False

        # 6. Jobs, Config, Incidents
        async def unavailable_broker(_: object) -> str:
            return "unavailable"

        monkeypatch.setattr("app.services.support_monitors._ping_broker", unavailable_broker)
        jobs = await actor.get(f"{API}/monitor/jobs")
        assert jobs.status_code == 200
        jobs_body = jobs.json()
        assert jobs_body["broker_status"] == "unavailable"
        assert jobs_body["source_status"] == "degraded"
        assert jobs_body["outbox_pending"] >= 1
        assert any(
            evt["task_name"] == "run_database_backup" and evt["event"] == "failed"
            for evt in jobs_body["recent_events"]
        )
        assert "secret-db-arg" not in jobs.text and "do-not-leak" not in jobs.text
        assert "secret-outbox-arg" not in jobs.text

        cfg = await actor.get(f"{API}/config/status")
        assert cfg.status_code == 200
        assert cfg.json()["audit_purge_disabled"] is True
        assert "postgresql" not in cfg.text and "password" not in cfg.text.lower()

        inc = await actor.get(
            f"{API}/incidents/summary", params={"case_id": seeded["case_id"]}
        )
        assert inc.status_code == 200
        inc_metrics = {m["key"]: m for m in inc.json()["metrics"]}
        assert inc_metrics["case_linked_error_events"]["value"] == 1
        assert "Secret stack detail" not in inc.text

        # 7. Simulated DB timeout inside oversight read returns explicit unavailable state
        from app.services import support_overview as so

        orig_exec = so.execute_oversight_read

        async def timeout_query(session, token, **kwargs):
            async def slow_fn(*_args):
                raise TimeoutError("simulated timeout")

            kwargs["query_fn"] = slow_fn
            return await orig_exec(session, token, **kwargs)

        monkeypatch.setattr("app.services.support_overview.execute_oversight_read", timeout_query)
        degraded = await actor.get(f"{API}/overview")
        assert degraded.status_code == 200
        assert degraded.json()["source_status"] == "unavailable"
        assert degraded.json()["metrics"][0]["state"] == "unavailable"
        monkeypatch.setattr("app.services.support_overview.execute_oversight_read", orig_exec)

        # 8. Mid-flight revocation cancels response with 401 and append-only audit persists
        async with AsyncSessionLocal() as session:
            count_before = await session.scalar(
                select(func.count()).select_from(SupportOversightEvent)
            )
            assert count_before is not None and count_before > 0
            await session.execute(
                update(SupportSession)
                .where(SupportSession.operator_id == operator_id)
                .values(revoked_at=utc_now())
            )
            await session.commit()
        assert (await actor.get(f"{API}/overview")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_backup_provenance_distinguishes_db_only_offhost_and_restore_drill() -> None:
    await skip_if_database_unavailable()
    async with client() as actor:
        operator_id, _, _ = await login(actor, custodian=False)
        await _grant(operator_id, "backups.read")

        # Empty receipts -> unverified (never recoverable)
        empty = await actor.get(f"{API}/monitor/backups")
        assert empty.status_code == 200
        assert empty.json()["overall_recovery_posture"] == "unverified"
        assert empty.json()["database_backup_status"] == "unverified"

        # DB-only scheduled attempt -> partial_db_only (still not complete_verified)
        now = utc_now()
        async with AsyncSessionLocal() as session:
            rec_db = SupportBackupReceipt(
                id=uuid4(),
                receipt_kind="scheduled_db_attempt",
                target_domain="local_host",
                covers_database=True,
                covers_objects=False,
                outcome="pass",
                captured_at=now - timedelta(hours=1),
                recorded_by="scheduled-backup-task",
                created_at=now,
            )
            session.add(rec_db)
            await session.commit()

            # Trigger must block mutation/deletion on support_backup_receipts
            with pytest.raises(DBAPIError):
                await session.execute(delete(SupportBackupReceipt))
            await session.rollback()

        partial = await actor.get(f"{API}/monitor/backups")
        assert partial.status_code == 200
        assert partial.json()["database_backup_status"] == "current"
        assert partial.json()["overall_recovery_posture"] == "partial_db_only"

        # Add authenticated off-host DB+object backup set + isolated restore drill
        async with AsyncSessionLocal() as session:
            session.add_all([
                SupportBackupReceipt(
                    id=uuid4(),
                    receipt_kind="authenticated_backup_set",
                    backup_set_id="set-20261117-01",
                    manifest_sha256="a" * 64,
                    target_domain="independent_offhost",
                    covers_database=True,
                    covers_objects=True,
                    outcome="pass",
                    rpo_minutes=60,
                    captured_at=now - timedelta(minutes=30),
                    signer_key_id="recovery-key-01",
                    recorded_by="garrisonctl-backup-attestation",
                    created_at=now,
                ),
                SupportBackupReceipt(
                    id=uuid4(),
                    receipt_kind="restore_drill",
                    backup_set_id="set-20261117-01",
                    manifest_sha256="a" * 64,
                    target_domain="isolated_restore",
                    covers_database=True,
                    covers_objects=True,
                    outcome="pass",
                    rto_minutes=18,
                    captured_at=now - timedelta(minutes=15),
                    verified_at=now - timedelta(minutes=10),
                    signer_key_id="recovery-key-01",
                    recorded_by="qa-restore-drill",
                    created_at=now,
                ),
            ])
            await session.commit()

        verified = await actor.get(f"{API}/monitor/backups")
        assert verified.status_code == 200
        v_body = verified.json()
        assert v_body["authenticated_backup_set_status"] == "verified"
        assert v_body["isolated_restore_status"] == "verified"
        assert v_body["overall_recovery_posture"] == "complete_verified"
        assert v_body["receipts"][0]["manifest_digest_prefix"] == "a" * 12


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_backup_monitor_reads_ingested_signed_receipts_end_to_end(tmp_path) -> None:
    await skip_if_database_unavailable()
    import hashlib
    from pathlib import Path

    from app.services.backup_receipt_ingestion import (
        ingest_publication_receipt,
        ingest_restore_drill_receipt,
        record_local_scheduled_db_attempt,
    )
    from scripts.backup_set_contract import (
        DestinationIdentity,
        FailureDomains,
        PublicationReceipt,
        RecoveryPolicy,
        RestoreDrillReceipt,
        RetentionRules,
        canonical_bytes,
        sign_publication_receipt,
        sign_restore_drill,
    )

    now = utc_now()
    key = bytes(range(32))
    key_file = Path(tmp_path) / "key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    policy = RecoveryPolicy(
        decision_id="D-29-RECOVERY",
        policy_id="e2e-policy",
        revision="v1",
        rpo_minutes=120,
        rto_minutes=120,
        backup_interval_minutes=30,
        maximum_capture_pause_seconds=60,
        maximum_publication_delay_minutes=15,
        minimum_spool_free_bytes=1024,
        retention_rules=RetentionRules(
            daily_days=2, monthly_months=2, keep_last_good=1, held_set_ids=set()
        ),
        destination_identity=DestinationIdentity(
            endpoint="localhost:9020", bucket="independent-e2e", prefix="app/test", secure=False
        ),
        failure_domains=FailureDomains(source="primary", destination="offhost"),
        key_custodians=["Custodian 1", "Custodian 2"],
        operator="Op 1",
        substitute_operator="Op 2",
        exercise_interval="monthly",
        required_artifact_categories={"application_database", "objects", "configuration"},
        required_configuration_paths={"compose.yml"},
        source_environment="test",
        approval_ref="test-approval",
        approved_at=now - timedelta(days=1),
    )
    policy_path = Path(tmp_path) / "policy.json"
    policy_path.write_bytes(canonical_bytes(policy))
    policy_sha = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    set_id = hashlib.sha256(str(now.timestamp()).encode()).hexdigest()[:32]
    manifest_sha = "f" * 64

    async with AsyncSessionLocal() as session:
        await record_local_scheduled_db_attempt(
            session, outcome="pass", captured_at=now - timedelta(seconds=5)
        )
        await ingest_publication_receipt(
            session,
            sign_publication_receipt(
                PublicationReceipt(
                    backup_set_id=set_id,
                    manifest_sha256=manifest_sha,
                    snapshot_at_utc=now - timedelta(seconds=4),
                    remote_verified_at_utc=now - timedelta(seconds=3),
                    source_sha="a" * 40,
                    source_environment="test",
                    policy_revision="v1",
                    policy_sha256=policy_sha,
                    configuration_sha256="b" * 64,
                    destination_identity=policy.destination_identity,
                    object_count=2,
                ),
                key=key,
                key_id="k1",
            ),
            policy_path=policy_path,
            expected_policy_sha256=policy_sha,
            key_file=key_file,
            key_id="k1",
        )
        await ingest_restore_drill_receipt(
            session,
            sign_restore_drill(
                RestoreDrillReceipt(
                    backup_set_id=set_id,
                    manifest_sha256=manifest_sha,
                    source_sha="a" * 40,
                    source_environment="test",
                    policy_revision="v1",
                    policy_sha256=policy_sha,
                    covers_database=True,
                    covers_objects=True,
                    outcome="pass",
                    rto_minutes=9,
                    started_at_utc=now - timedelta(seconds=2),
                    verified_at_utc=now - timedelta(seconds=1),
                ),
                key=key,
                key_id="k1",
            ),
            policy_path=policy_path,
            expected_policy_sha256=policy_sha,
            key_file=key_file,
            key_id="k1",
        )
        await session.commit()

    async with client() as actor:
        operator_id, _, _ = await login(actor, custodian=False)
        await _grant(operator_id, "backups.read")
        res = await actor.get(f"{API}/monitor/backups")
        assert res.status_code == 200
        body = res.json()
        assert body["overall_recovery_posture"] == "complete_verified"
        assert body["authenticated_backup_set_status"] == "verified"
        assert body["isolated_restore_status"] == "verified"
        assert body["database_backup_status"] == "current"


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_backup_monitor_selects_per_kind_latest_and_flags_partial_restore() -> None:
    await skip_if_database_unavailable()
    async with client() as actor:
        operator_id, _, _ = await login(actor, custodian=False)
        await _grant(operator_id, "backups.read")

        base = utc_now()
        set_older = f"set-old-{uuid4().hex[:8]}"
        set_latest = f"set-new-{uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            # Record an off-host full set + partial DB-only restore, buried under 25 DB attempts.
            session.add(
                SupportBackupReceipt(
                    id=uuid4(),
                    receipt_kind="authenticated_backup_set",
                    backup_set_id=set_latest,
                    manifest_sha256="b" * 64,
                    target_domain="independent_offhost",
                    covers_database=True,
                    covers_objects=True,
                    outcome="pass",
                    rpo_minutes=60,
                    captured_at=base + timedelta(seconds=1),
                    signer_key_id="k1",
                    recorded_by="offhost-test",
                    created_at=base + timedelta(seconds=1),
                )
            )
            session.add(
                SupportBackupReceipt(
                    id=uuid4(),
                    receipt_kind="restore_drill",
                    backup_set_id=set_latest,
                    manifest_sha256="b" * 64,
                    target_domain="isolated_restore",
                    covers_database=True,
                    covers_objects=False,
                    outcome="pass",
                    rto_minutes=12,
                    captured_at=base + timedelta(seconds=2),
                    verified_at=base + timedelta(seconds=2),
                    signer_key_id="k1",
                    recorded_by="partial-restore-test",
                    created_at=base + timedelta(seconds=2),
                )
            )
            for idx in range(25):
                ts = base + timedelta(seconds=10 + idx)
                session.add(
                    SupportBackupReceipt(
                        id=uuid4(),
                        receipt_kind="scheduled_db_attempt",
                        target_domain="local_host",
                        covers_database=True,
                        covers_objects=False,
                        outcome="pass",
                        captured_at=ts,
                        recorded_by="scheduled-backup-task",
                        created_at=ts,
                    )
                )
            await session.commit()

        partial = await actor.get(f"{API}/monitor/backups")
        assert partial.status_code == 200
        p_body = partial.json()
        assert p_body["authenticated_backup_set_status"] == "verified"
        assert p_body["isolated_restore_status"] == "partial"
        assert p_body["overall_recovery_posture"] == "partial_restore_coverage"
        assert p_body["latest_restore_covers_database"] is True
        assert p_body["latest_restore_covers_objects"] is False
        assert p_body["latest_backup_set_id"] == set_latest

        # Periodic full DB+objects restore against an older set verifies coverage without
        # falsely matching the newer set.
        async with AsyncSessionLocal() as session:
            ts_periodic = base + timedelta(seconds=40)
            session.add(
                SupportBackupReceipt(
                    id=uuid4(),
                    receipt_kind="restore_drill",
                    backup_set_id=set_older,
                    manifest_sha256="c" * 64,
                    target_domain="isolated_restore",
                    covers_database=True,
                    covers_objects=True,
                    outcome="pass",
                    rto_minutes=15,
                    captured_at=ts_periodic,
                    verified_at=ts_periodic,
                    signer_key_id="k1",
                    recorded_by="full-periodic-drill",
                    created_at=ts_periodic,
                )
            )
            await session.commit()

        verified = await actor.get(f"{API}/monitor/backups")
        assert verified.status_code == 200
        v_body = verified.json()
        assert v_body["isolated_restore_status"] == "verified"
        assert v_body["overall_recovery_posture"] == "complete_verified"
        assert v_body["latest_restore_covers_database"] is True
        assert v_body["latest_restore_covers_objects"] is True
        assert v_body["latest_restore_matches_latest_set"] is False
        assert v_body["latest_backup_set_id"] == set_latest
        assert v_body["latest_restore_backup_set_id"] == set_older


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_production_recovery_delivery_gate_and_nonsecret_outcome_notices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()

    disabled_prod = Settings(
        app_env="production",
        support_portal_enabled=True,
        support_recovery_delivery_enabled=False,
        frontend_base_url="https://portal.garrisons.lk",
        support_recovery_key=SecretStr("recovery-key-at-least-thirty-two-bytes-long"),
        support_recovery_allowed_origins="https://portal.garrisons.lk",
    )
    assert _portal_origin(disabled_prod) is None

    unlisted_origin = Settings(
        app_env="production",
        support_portal_enabled=True,
        support_recovery_delivery_enabled=True,
        frontend_base_url="https://evil.example.com",
        support_recovery_key=SecretStr("recovery-key-at-least-thirty-two-bytes-long"),
        support_recovery_allowed_origins="https://portal.garrisons.lk",
    )
    assert _portal_origin(unlisted_origin) is None

    approved_prod = Settings(
        app_env="production",
        support_portal_enabled=True,
        support_recovery_delivery_enabled=True,
        frontend_base_url="https://portal.garrisons.lk/",
        support_recovery_key=SecretStr("recovery-key-at-least-thirty-two-bytes-long"),
        support_recovery_allowed_origins="https://portal.garrisons.lk",
        exception_email_enabled=True,
        exception_email_recipients="ops-alert@example.com",
    )
    assert _portal_origin(approved_prod) == "https://portal.garrisons.lk"

    async def seed_pending_delivery(target_email: str) -> tuple[UUID, UUID, str]:
        req_op = await client().__aenter__()
        rev_op = await client().__aenter__()
        try:
            r_id, _, _ = await login(req_op, custodian=False)
            v_id, _, _ = await login(rev_op, custodian=True)
            await _grant(r_id, "account.request")
            await _grant(v_id, "account.request")
        finally:
            await req_op.aclose()
            await rev_op.aclose()

        target_id, case_id, action_id, ch_id = uuid4(), uuid4(), uuid4(), uuid4()
        now = utc_now()
        binding = recovery_destination_digest(approved_prod, target_id, target_email)
        otp = support_recovery_otp(approved_prod, ch_id)
        assert binding is not None and otp is not None
        otp_hash = support_recovery_otp_digest(approved_prod, ch_id, otp)
        assert otp_hash is not None
        async with AsyncSessionLocal() as session:
            session.add(
                User(
                    id=target_id,
                    full_name="Prod Recovery Target",
                    email=target_email,
                    role=ROLE_SITE_SUPERVISOR,
                    password_hash="synthetic-hash",
                    is_active=True,
                    access_revision=1,
                    recovery_email_digest=binding,
                    recovery_email_verified_at=now,
                )
            )
            session.add(SupportCase(id=case_id, status="open", revision=1))
            await session.flush()
            session.add(SupportCaseMember(case_id=case_id, operator_id=r_id))
            session.add(SupportCaseMember(case_id=case_id, operator_id=v_id))
            session.add(SupportCaseSubject(case_id=case_id, user_id=target_id))
            session.add(
                AuthOtpChallenge(
                    id=ch_id,
                    user_id=target_id,
                    purpose="support_password_reset",
                    otp_hash=otp_hash,
                    expires_at=now + timedelta(minutes=10),
                )
            )
            await session.flush()
            session.add(
                SupportBusinessAction(
                    id=action_id,
                    case_id=case_id,
                    requester_id=r_id,
                    requester_epoch=1,
                    user_id=target_id,
                    user_revision=0,
                    case_revision=1,
                    command_key=uuid4(),
                    kind="recover",
                    recovery_destination_digest=binding,
                    reason_code="access",
                    reason="Production delivery check.",
                    digest="a" * 64,
                    expires_at=now + timedelta(minutes=15),
                    applied_at=now,
                )
            )
            await session.flush()
            session.add(
                SupportBusinessApproval(
                    action_id=action_id,
                    reviewer_id=v_id,
                    reviewer_epoch=1,
                    occurred_at=now,
                    request_id=uuid4().hex,
                )
            )
            session.add(
                SupportRecoveryDelivery(
                    action_id=action_id,
                    challenge_id=ch_id,
                    status="pending",
                    created_at=now,
                )
            )
            await session.commit()
        return target_id, action_id, otp

    sent_calls: list[tuple[list[str], str]] = []

    def fake_send(_self, *, recipients, subject, body, allow_fallback=True) -> int:
        sent_calls.append((recipients, subject))
        return 1

    monkeypatch.setattr("app.tasks.support_recovery.EmailService.send", fake_send)

    # Case A: disabled in production dispatches 0; enabling approved_prod accepts `a_a` cleanly.
    t_a, a_a, otp_a = await seed_pending_delivery(f"user-a-{uuid4().hex[:6]}@example.com")
    monkeypatch.setattr("app.tasks.support_recovery.get_settings", lambda: disabled_prod)
    monkeypatch.setattr("app.services.support_business_actions.get_settings", lambda: approved_prod)
    assert await dispatch_recovery_deliveries() == 0
    monkeypatch.setattr("app.tasks.support_recovery.get_settings", lambda: approved_prod)
    assert await dispatch_recovery_deliveries() == 1
    async with AsyncSessionLocal() as session:
        deliv_a = await session.get(SupportRecoveryDelivery, a_a)
        assert deliv_a is not None and deliv_a.status == "accepted"
        notices = list(
            await session.scalars(select(Notification).where(Notification.user_id == t_a))
        )
        assert len(notices) == 1
        assert otp_a not in notices[0].body
        assert str(a_a) not in notices[0].body
        await session.execute(delete(Notification).where(Notification.user_id == t_a))
        await session.commit()

    # Case B: custodian mailbox overlap must cancel rather than dispatch.
    custodian_conflict_email = f"custodian-{uuid4().hex[:6]}@example.com"
    t_b, a_b, _ = await seed_pending_delivery(custodian_conflict_email)
    conflict_settings = Settings(
        app_env="production",
        support_portal_enabled=True,
        support_recovery_delivery_enabled=True,
        frontend_base_url="https://portal.garrisons.lk",
        support_recovery_key=SecretStr("recovery-key-at-least-thirty-two-bytes-long"),
        support_recovery_allowed_origins="https://portal.garrisons.lk",
        support_email_otp_recipients={uuid4(): custodian_conflict_email},
    )
    monkeypatch.setattr("app.tasks.support_recovery.get_settings", lambda: conflict_settings)
    monkeypatch.setattr(
        "app.services.support_business_actions.get_settings", lambda: conflict_settings
    )
    before_conflict_calls = len(sent_calls)
    await dispatch_recovery_deliveries()
    async with AsyncSessionLocal() as session:
        deliv_b = await session.get(SupportRecoveryDelivery, a_b)
        assert deliv_b is not None and deliv_b.status == "cancelled"
    assert len(sent_calls) == before_conflict_calls
    monkeypatch.setattr("app.tasks.support_recovery.get_settings", lambda: approved_prod)
    monkeypatch.setattr("app.services.support_business_actions.get_settings", lambda: approved_prod)

    # Case C: unknown transport outcome sends sanitized ops alert without code/email
    t_c, a_c, otp_c = await seed_pending_delivery(f"user-c-{uuid4().hex[:6]}@example.com")
    alert_calls: list[tuple[list[str], str, str]] = []

    def failing_then_alert(
        _self, *, recipients, subject, body, allow_fallback=True
    ) -> int:
        if "unknown outcome" in subject or subject == "Support recovery delivery outcome unknown":
            alert_calls.append((recipients, subject, body))
            return 1
        raise EmailDeliveryError("SMTP timeout")

    monkeypatch.setattr("app.tasks.support_recovery.EmailService.send", failing_then_alert)
    await dispatch_recovery_deliveries()
    async with AsyncSessionLocal() as session:
        deliv_c = await session.get(SupportRecoveryDelivery, a_c)
        assert deliv_c is not None and deliv_c.status == "unknown"
        notice_c = await session.scalar(select(Notification).where(Notification.user_id == t_c))
        assert notice_c is not None and notice_c.email_status == "unknown"
    assert len(alert_calls) == 1
    assert alert_calls[0][0] == ["ops-alert@example.com"]
    assert str(a_c) in alert_calls[0][2] and otp_c not in alert_calls[0][2]
    assert t_b != t_a


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_custody_grant_change_supports_new_oversight_capabilities() -> None:
    await skip_if_database_unavailable()
    async with client() as first, client() as second, client() as target_cli:
        cust_a = await login(first)
        cust_b = await login(second)
        target = await login(target_cli, custodian=False)

        proposal = await first.post(
            f"{API}/custody/grant-changes",
            json={
                "target_id": str(target[0]),
                "capability": "overview.company.read",
                "enable": True,
            },
        )
        assert proposal.status_code == 201, proposal.text
        grant_id = proposal.json()["grant_change_id"]

        rev_opts = await second.post(f"{API}/custody/grant-changes/{grant_id}/review/options")
        assert rev_opts.status_code == 200
        assert (
            await second.post(
                f"{API}/custody/grant-changes/{grant_id}/review",
                json=sign(rev_opts.json(), *cust_b, counter=2),
            )
        ).status_code == 204

        exe_opts = await first.post(f"{API}/custody/grant-changes/{grant_id}/execute/options")
        assert exe_opts.status_code == 200
        assert (
            await first.post(
                f"{API}/custody/grant-changes/{grant_id}/execute",
                json=sign(exe_opts.json(), *cust_a, counter=2),
            )
        ).status_code == 204

        # Target's previous session was revoked on grant epoch advance.
        assert (await target_cli.get(f"{API}/overview")).status_code == 401
        async with AsyncSessionLocal() as session:
            assert (
                await session.get(SupportOperatorGrant, (target[0], "overview.company.read"))
                is not None
            )


def test_support_cli_oversight_commands_and_guardrails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    session_file = tmp_path / "support-session.json"
    session_file.chmod(0o600) if session_file.exists() else None
    token, csrf = "S" * 43, "C" * 43
    session_file.write_text(
        json.dumps(
            {
                "origin": "https://superadmin.garrisons.lk",
                "support_token": token,
                "support_csrf": csrf,
            }
        )
    )
    session_file.chmod(0o600)
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        assert request.headers["X-Support-CSRF"] == csrf
        return httpx.Response(
            200,
            json={"observed_at": datetime.now(UTC).isoformat(), "ok": True},
            headers={"X-Request-ID": "cli-test"},
        )

    transport = httpx.MockTransport(handler)
    import io

    for idx, argv in enumerate([
        ["support", "overview", "show", "--domain", "company"],
        ["support", "overview", "show", "--domain", "finance"],
        ["support", "monitor", "jobs", "--hours", "24", "--queue", "backup"],
        ["support", "monitor", "backups"],
        ["support", "config", "show"],
        ["support", "incidents", "show", "--hours", "6"],
        [
            "support",
            "policy",
            "explain",
            "--role",
            "hr_executive_reader",
            "--permission",
            "reports:view",
        ],
    ]):
        out_file = tmp_path / f"out-{idx}.json"
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = garrisonctl.run(
            [*argv, "--output", str(out_file), "--session-file", str(session_file), "--json"],
            transport=transport,
            stdout=stdout,
            stderr=stderr,
        )
        assert rc == 0 and not stderr.getvalue()
        assert json.loads(out_file.read_text())["ok"] is True

    assert seen_paths == [
        "/api/v1/support/overview",
        "/api/v1/support/overview/finance",
        "/api/v1/support/monitor/jobs",
        "/api/v1/support/monitor/backups",
        "/api/v1/support/config/status",
        "/api/v1/support/incidents/summary",
        "/api/v1/support/policy/explain",
    ]
    # Reject invalid case scoping on non-case domain
    bad_out = tmp_path / "bad.json"
    rc_bad = garrisonctl.run(
        [
            "support",
            "overview",
            "show",
            "--domain",
            "company",
            "--case",
            str(uuid4()),
            "--output",
            str(bad_out),
            "--session-file",
            str(session_file),
            "--json",
        ],
        transport=transport,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert rc_bad != 0 and not bad_out.exists()


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_jobs_monitor_exposes_worker_heartbeat_stale_outbox_and_honest_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    from app.models.task_outbox import TaskOutbox
    from app.tasks.worker_heartbeat import read_worker_heartbeats

    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(TaskOutbox).where(
                TaskOutbox.status.in_(["failed", "dispatched", "manual_review"])
            )
        )
        await session.execute(
            delete(SupportRecoveryDelivery).where(SupportRecoveryDelivery.status == "unknown")
        )
        await session.commit()

    stale_key = f"report-pdf:{uuid4()}"
    manual_review_key = f"notification-email:{uuid4()}"
    try:
        async with client() as actor:
            operator_id, _, _ = await login(actor, custodian=False)
            await _grant(operator_id, "jobs.read")

            # 1. Healthy broker without worker heartbeat must stay partial / freshness unknown.
            async def ok_broker(_: object) -> str:
                return "operational"

            async def missing_worker(
                _settings: object, _now: object
            ) -> tuple[str, int | None, int]:
                return "unknown", None, 0

            monkeypatch.setattr("app.services.support_monitors._ping_broker", ok_broker)
            monkeypatch.setattr(
                "app.services.support_monitors.read_worker_heartbeats", missing_worker
            )
            res = await actor.get(f"{API}/monitor/jobs")
            assert res.status_code == 200
            body = res.json()
            assert body["broker_status"] == "operational"
            assert body["worker_status"] == "unknown"
            assert body["source_status"] == "partial"
            assert body["freshness"] == "unknown"
            assert "activity_log" in body["history_coverage"]
            assert any(item["task_name"] == "post_hr_leave_accruals" for item in body["schedules"])
            assert any(
                item["task_name"] == "check_late_reports" and item["queue"] == "maintenance"
                for item in body["schedules"]
            )

            # 2. Active worker heartbeat + no failed/stale outbox -> operational / current
            async def live_worker(_settings: object, _now: object) -> tuple[str, int | None, int]:
                return "operational", 4, 1

            monkeypatch.setattr("app.services.support_monitors.read_worker_heartbeats", live_worker)
            ok_res = await actor.get(f"{API}/monitor/jobs")
            assert ok_res.status_code == 200
            ok_body = ok_res.json()
            assert ok_body["worker_status"] == "operational"
            assert ok_body["worker_heartbeat_age_seconds"] == 4
            assert ok_body["source_status"] == "operational"
            assert ok_body["freshness"] == "current"

            # 3. Stale dispatched outbox entry -> degraded / stale
            async with AsyncSessionLocal() as session:
                session.add(
                    TaskOutbox(
                        dedupe_key=stale_key,
                        task_name="generate_report_pdf",
                        args_json=[str(uuid4()), None],
                        kwargs_json={"email_after": False},
                        status="dispatched",
                        attempts=1,
                        dispatched_at=utc_now() - timedelta(minutes=15),
                    )
                )
                await session.commit()

            stale_res = await actor.get(f"{API}/monitor/jobs")
            assert stale_res.status_code == 200
            stale_body = stale_res.json()
            assert stale_body["outbox_stale_dispatched"] >= 1
            assert stale_body["source_status"] == "degraded"
            assert stale_body["freshness"] == "stale"

            async with AsyncSessionLocal() as session:
                session.add(
                    TaskOutbox(
                        dedupe_key=manual_review_key,
                        task_name="send_email_notification",
                        args_json=[str(uuid4())],
                        kwargs_json={},
                        status="manual_review",
                        attempts=1,
                    )
                )
                await session.commit()
            review_res = await actor.get(f"{API}/monitor/jobs")
            assert review_res.status_code == 200
            assert review_res.json()["outbox_manual_review"] >= 1
            assert review_res.json()["source_status"] == "degraded"

            # 4. Also exercise real read_worker_heartbeats against configured Redis safely
            _ = await read_worker_heartbeats(get_settings(), utc_now())
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(TaskOutbox).where(TaskOutbox.dedupe_key.in_((stale_key, manual_review_key)))
            )
            await session.commit()


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_material_request_and_approval_oversight_reconciliation() -> None:
    await skip_if_database_unavailable()
    async with client() as actor:
        operator_id, _, _ = await login(actor, custodian=False)
        await _grant(
            operator_id,
            "overview.company.read",
            "overview.inventory.read",
            "overview.approvals.read",
        )

        # Measure shared-DB baseline counts first.
        company_before = {
            m["key"]: m["value"] for m in (await actor.get(f"{API}/overview")).json()["metrics"]
        }
        inv_before = {
            m["key"]: m["value"]
            for m in (await actor.get(f"{API}/overview/inventory")).json()["metrics"]
        }
        appr_before = {
            row["request_type"]: row
            for row in (await actor.get(f"{API}/overview/approvals")).json()["by_workflow"]
        }

        now = utc_now()
        today = date.today()
        suffix = uuid4().hex[:6]
        async with AsyncSessionLocal() as session:
            requester = User(
                email=f"mr-req-{suffix}@example.com",
                full_name="MR Oversight User",
                role="quantity_surveyor",
                password_hash="synthetic-hash",
            )
            proj = Project(
                name=f"Oversight MR Proj {suffix}",
                code=f"OMP-{suffix}",
                status="active",
                scope_of_work="Works",
                target_end_date=today + timedelta(days=30),
            )
            session.add_all([requester, proj])
            await session.flush()
            loc = StorageLocation(
                name=f"MR Store {suffix}",
                code=f"MRS-{suffix}",
                location_type="site",
                project_id=proj.id,
                is_active=True,
            )
            session.add(loc)
            await session.flush()

            # 5 open modern/active statuses + 2 legacy open + 2 closed terminal (issued, cancelled)
            for idx, (status_val, age_days) in enumerate(
                [
                    ("submitted", 10),
                    ("approved", 8),
                    ("partially_reserved", 2),
                    ("reserved", 9),
                    ("partially_issued", 1),
                    ("requested", 12),
                    ("partially_fulfilled", 0),
                    ("issued", 15),
                    ("cancelled", 20),
                ]
            ):
                session.add(
                    MaterialRequest(
                        request_number=f"MR-REC-{suffix}-{idx}",
                        project_id=proj.id,
                        requester_id=requester.id,
                        from_location_id=loc.id,
                        status=status_val,
                        total_estimated_cost=Decimal("10.00"),
                        created_at=now - timedelta(days=age_days),
                    )
                )

            # Approvals: 1 pending + 1 delegated overdue + 1 escalated overdue
            session.add_all(
                [
                    Approval(
                        request_type="material_request",
                        request_id=uuid4(),
                        project_id=proj.id,
                        submitter_id=requester.id,
                        approver_id=requester.id,
                        status="pending",
                        title=f"Pending {suffix}",
                        submitted_at=now - timedelta(hours=2),
                        due_at=now + timedelta(hours=22),
                    ),
                    Approval(
                        request_type="material_request",
                        request_id=uuid4(),
                        project_id=proj.id,
                        submitter_id=requester.id,
                        approver_id=requester.id,
                        delegated_to_id=requester.id,
                        status="delegated",
                        title=f"Delegated {suffix}",
                        submitted_at=now - timedelta(days=2),
                        due_at=now - timedelta(hours=3),
                    ),
                    Approval(
                        request_type="material_request",
                        request_id=uuid4(),
                        project_id=proj.id,
                        submitter_id=requester.id,
                        approver_id=requester.id,
                        status="escalated",
                        title=f"Escalated {suffix}",
                        submitted_at=now - timedelta(days=3),
                        due_at=now - timedelta(hours=5),
                        escalated_at=now - timedelta(hours=1),
                    ),
                ]
            )
            await session.commit()

        company_after = {
            m["key"]: m["value"] for m in (await actor.get(f"{API}/overview")).json()["metrics"]
        }
        inv_after = {
            m["key"]: m["value"]
            for m in (await actor.get(f"{API}/overview/inventory")).json()["metrics"]
        }
        appr_after = {
            row["request_type"]: row
            for row in (await actor.get(f"{API}/overview/approvals")).json()["by_workflow"]
        }

        assert (
            company_after["open_material_requests"]
            == company_before["open_material_requests"] + 7
        )
        assert inv_after["open_material_requests"] == inv_before["open_material_requests"] + 7
        assert (
            inv_after["overdue_material_requests"]
            == inv_before["overdue_material_requests"] + 4
        )

        mr_before = appr_before.get(
            "material_request", {"pending": 0, "overdue": 0, "escalated": 0, "rejected": 0}
        )
        mr_after = appr_after["material_request"]
        assert mr_after["pending"] == mr_before["pending"] + 2
        assert mr_after["overdue"] == mr_before["overdue"] + 2
        assert mr_after["escalated"] == mr_before["escalated"] + 1
        assert company_after["open_approvals"] == company_before["open_approvals"] + 2
        assert company_after["overdue_approvals"] == company_before["overdue_approvals"] + 1
