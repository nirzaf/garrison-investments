"""Add HR and workforce management schema.

Revision ID: 202605310007
Revises: 202605310006
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605310007"
down_revision: str | None = "202605310006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("uuid_generate_v4()"),
    )


def _timestamps() -> tuple[sa.Column[Any], sa.Column[Any]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def _deleted_at() -> sa.Column[Any]:
    return sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    op.create_table(
        "hr_work_calendars",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "work_days_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("""'["MON","TUE","WED","THU","FRI"]'::jsonb"""),
        ),
        sa.Column(
            "standard_start_time",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'08:30:00'"),
        ),
        sa.Column(
            "standard_end_time",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'17:00:00'"),
        ),
        sa.Column(
            "daily_hours", sa.Numeric(5, 2), nullable=False, server_default=sa.text("8.00")
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        _deleted_at(),
    )

    op.create_table(
        "hr_departments",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "parent_department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("head_employee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        _deleted_at(),
    )

    op.create_table(
        "hr_positions",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("grade", sa.String(40), nullable=True),
        sa.Column(
            "employment_category",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'permanent'"),
        ),
        sa.Column("headcount_limit", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("approved_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        _deleted_at(),
    )

    op.create_table(
        "hr_employees",
        _uuid_pk(),
        sa.Column("employee_code", sa.String(40), nullable=False, unique=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("first_name", sa.String(120), nullable=False),
        sa.Column("last_name", sa.String(120), nullable=False),
        sa.Column("preferred_name", sa.String(120), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("work_email", sa.String(255), nullable=True, unique=True),
        sa.Column("work_phone", sa.String(32), nullable=True),
        sa.Column(
            "employment_status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "employment_category",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'permanent'"),
        ),
        sa.Column("join_date", sa.Date(), nullable=True),
        sa.Column("confirmation_date", sa.Date(), nullable=True),
        sa.Column("termination_date", sa.Date(), nullable=True),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_positions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "primary_project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "manager_employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("work_location", sa.String(160), nullable=True),
        sa.Column(
            "work_calendar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_work_calendars.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("record_revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        _deleted_at(),
    )
    op.create_index("ix_hr_employees_full_name", "hr_employees", ["full_name"])
    op.create_index("ix_hr_employees_employment_status", "hr_employees", ["employment_status"])
    op.create_foreign_key(
        "fk_hr_departments_head_employee_id",
        "hr_departments",
        "hr_employees",
        ["head_employee_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "hr_employee_private",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("national_id_encrypted", sa.Text(), nullable=True),
        sa.Column("national_id_masked", sa.String(64), nullable=True),
        sa.Column("passport_encrypted", sa.Text(), nullable=True),
        sa.Column("passport_masked", sa.String(64), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(30), nullable=True),
        sa.Column("marital_status", sa.String(30), nullable=True),
        sa.Column("nationality", sa.String(80), nullable=True),
        sa.Column("personal_email", sa.String(255), nullable=True),
        sa.Column("personal_phone", sa.String(32), nullable=True),
        sa.Column("residential_address", sa.Text(), nullable=True),
        sa.Column("emergency_contact_name", sa.String(160), nullable=True),
        sa.Column("emergency_contact_phone", sa.String(32), nullable=True),
        sa.Column("emergency_contact_relation", sa.String(80), nullable=True),
        sa.Column("bank_name", sa.String(120), nullable=True),
        sa.Column("bank_branch", sa.String(120), nullable=True),
        sa.Column("bank_account_encrypted", sa.Text(), nullable=True),
        sa.Column("bank_account_masked", sa.String(64), nullable=True),
        sa.Column("tax_id_encrypted", sa.Text(), nullable=True),
        sa.Column("tax_id_masked", sa.String(64), nullable=True),
        sa.Column("epf_number_encrypted", sa.Text(), nullable=True),
        sa.Column("epf_number_masked", sa.String(64), nullable=True),
        sa.Column("etf_number_encrypted", sa.Text(), nullable=True),
        sa.Column("etf_number_masked", sa.String(64), nullable=True),
        sa.Column("medical_notes_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
    )

    op.create_table(
        "hr_employment_history",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("change_type", sa.String(40), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column(
            "previous_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("new_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
    )
    op.create_index(
        "ix_hr_employment_history_employee_id",
        "hr_employment_history",
        ["employee_id"],
    )

    op.create_table(
        "hr_access_requests",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_type", sa.String(30), nullable=False),
        sa.Column("requested_role", sa.String(64), nullable=True),
        sa.Column("requested_email", sa.String(255), nullable=True),
        sa.Column(
            "portal_access_required", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("business_title_source", sa.String(160), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("hr_decision_notes", sa.Text(), nullable=True),
        sa.Column("admin_decision_notes", sa.Text(), nullable=True),
        sa.Column(
            "requested_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "hr_approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("hr_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "admin_actioned_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("admin_actioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "linked_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
    )
    op.create_index("ix_hr_access_requests_employee_id", "hr_access_requests", ["employee_id"])
    op.create_index("ix_hr_access_requests_status", "hr_access_requests", ["status"])

    op.create_table(
        "hr_requisitions",
        _uuid_pk(),
        sa.Column("requisition_code", sa.String(40), nullable=False, unique=True),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_positions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "employment_category",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'permanent'"),
        ),
        sa.Column("headcount_requested", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("budget_notes", sa.Text(), nullable=True),
        sa.Column(
            "requested_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_join_date", sa.Date(), nullable=True),
        *_timestamps(),
        _deleted_at(),
    )
    op.create_index("ix_hr_requisitions_status", "hr_requisitions", ["status"])

    op.create_table(
        "hr_candidates",
        _uuid_pk(),
        sa.Column("candidate_code", sa.String(40), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("source", sa.String(80), nullable=True),
        sa.Column("current_organization", sa.String(160), nullable=True),
        sa.Column("years_experience", sa.Numeric(4, 1), nullable=True),
        sa.Column("resume_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'active'")),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        _deleted_at(),
    )
    op.create_index("ix_hr_candidates_full_name", "hr_candidates", ["full_name"])
    op.create_index("ix_hr_candidates_email", "hr_candidates", ["email"])

    op.create_table(
        "hr_applications",
        _uuid_pk(),
        sa.Column(
            "requisition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_requisitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(30), nullable=False, server_default=sa.text("'applied'")),
        sa.Column("overall_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("screening_notes", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "assigned_recruiter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint("requisition_id", "candidate_id", name="uq_hr_application_req_cand"),
    )
    op.create_index("ix_hr_applications_stage", "hr_applications", ["stage"])

    op.create_table(
        "hr_interviews",
        _uuid_pk(),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "interview_type", sa.String(40), nullable=False, server_default=sa.text("'technical'")
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "interviewer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("interviewer_name", sa.String(160), nullable=True),
        sa.Column(
            "recommendation", sa.String(30), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column("feedback_notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'scheduled'")),
        *_timestamps(),
    )

    op.create_table(
        "hr_offers",
        _uuid_pk(),
        sa.Column("offer_code", sa.String(40), nullable=False, unique=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("proposed_title", sa.String(160), nullable=False),
        sa.Column(
            "proposed_department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "proposed_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_positions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("proposed_join_date", sa.Date(), nullable=True),
        sa.Column("proposed_salary_encrypted", sa.Text(), nullable=True),
        sa.Column("proposed_salary_masked", sa.String(64), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default=sa.text("'LKR'")),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'draft'")),
        sa.Column(
            "approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "converted_employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_hr_offers_status", "hr_offers", ["status"])

    op.create_table(
        "hr_onboarding_cases",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "offer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_offers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'open'")),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("probation_end_date", sa.Date(), nullable=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("completion_notes", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_hr_onboarding_cases_employee_id", "hr_onboarding_cases", ["employee_id"])

    op.create_table(
        "hr_onboarding_tasks",
        _uuid_pk(),
        sa.Column(
            "onboarding_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_onboarding_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("assignee_role", sa.String(40), nullable=False),
        sa.Column(
            "assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "completed_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_notes", sa.Text(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_documents",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_candidates.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("category", sa.String(30), nullable=False, server_default=sa.text("'ordinary'")),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("issuing_authority", sa.String(160), nullable=True),
        sa.Column("reference_number", sa.String(80), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'active'")),
        sa.Column("alert_days_before", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column(
            "is_employee_visible", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        _deleted_at(),
    )
    op.create_index("ix_hr_documents_employee_id", "hr_documents", ["employee_id"])
    op.create_index("ix_hr_documents_expiry_date", "hr_documents", ["expiry_date"])
    op.create_foreign_key(
        "fk_hr_candidates_resume_document_id",
        "hr_candidates",
        "hr_documents",
        ["resume_document_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "hr_document_versions",
        _uuid_pk(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256_checksum", sa.String(64), nullable=False),
        sa.Column(
            "uploaded_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("document_id", "version_number", name="uq_hr_doc_version"),
    )

    op.create_table(
        "hr_policy_documents",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("version", sa.String(20), nullable=False, server_default=sa.text("'1.0'")),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("content_summary", sa.Text(), nullable=False),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "requires_acknowledgement", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "published_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_policy_acknowledgements",
        _uuid_pk(),
        sa.Column(
            "policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_policy_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "acknowledged_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("policy_id", "employee_id", name="uq_hr_policy_ack_emp"),
    )

    op.create_table(
        "hr_letter_templates",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("letter_type", sa.String(50), nullable=False),
        sa.Column("subject_template", sa.String(255), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column(
            "requires_hr_manager", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamps(),
    )

    op.create_table(
        "hr_hr_requests",
        _uuid_pk(),
        sa.Column("request_code", sa.String(40), nullable=False, unique=True),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_type", sa.String(50), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'open'")),
        sa.Column(
            "assigned_to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column(
            "resolved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "generated_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
    )
    op.create_index("ix_hr_hr_requests_status", "hr_hr_requests", ["status"])

    op.create_table(
        "hr_holidays",
        _uuid_pk(),
        sa.Column(
            "calendar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_work_calendars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "holiday_type",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'public'"),
        ),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamps(),
        sa.UniqueConstraint("calendar_id", "holiday_date", name="uq_hr_holiday_cal_date"),
    )

    op.create_table(
        "hr_shift_assignments",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "calendar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_work_calendars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("shift_name", sa.String(80), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column(
            "assigned_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
    )

    op.create_table(
        "hr_attendance_entries",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attendance_status", sa.String(30), nullable=False),
        sa.Column("check_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "worked_hours", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0.00")
        ),
        sa.Column("source", sa.String(30), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "recorded_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("employee_id", "work_date", name="uq_hr_attendance_emp_date"),
    )
    op.create_index("ix_hr_attendance_entries_work_date", "hr_attendance_entries", ["work_date"])

    op.create_table(
        "hr_attendance_corrections",
        _uuid_pk(),
        sa.Column(
            "attendance_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_attendance_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("requested_status", sa.String(30), nullable=False),
        sa.Column("requested_check_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_check_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requested_worked_hours",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("8.00"),
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'submitted'")),
        sa.Column(
            "requested_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_timesheets",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "regular_hours", sa.Numeric(6, 2), nullable=False, server_default=sa.text("0.00")
        ),
        sa.Column(
            "overtime_hours", sa.Numeric(6, 2), nullable=False, server_default=sa.text("0.00")
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "employee_id", "period_start", "period_end", name="uq_hr_timesheet_emp_period"
        ),
    )

    op.create_table(
        "hr_overtime_requests",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("requested_hours", sa.Numeric(5, 2), nullable=False),
        sa.Column("approved_hours", sa.Numeric(5, 2), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'submitted'")),
        sa.Column(
            "requested_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_leave_types",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "requires_attachment", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("allow_half_day", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_leave_policies",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "leave_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_leave_types.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("employment_category", sa.String(30), nullable=True),
        sa.Column("annual_entitlement_days", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "accrual_frequency", sa.String(30), nullable=False, server_default=sa.text("'annual'")
        ),
        sa.Column(
            "max_carry_forward_days",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "allow_negative_balance", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_leave_requests",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "leave_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_leave_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("days_requested", sa.Numeric(5, 2), nullable=False),
        sa.Column("is_half_day", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("half_day_period", sa.String(20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "attachment_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'submitted'")),
        sa.Column(
            "requested_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_hr_leave_requests_employee_id", "hr_leave_requests", ["employee_id"])
    op.create_index("ix_hr_leave_requests_status", "hr_leave_requests", ["status"])

    op.create_table(
        "hr_leave_ledger",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "leave_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_leave_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(30), nullable=False),
        sa.Column("days_delta", sa.Numeric(6, 2), nullable=False),
        sa.Column("leave_year", sa.Integer(), nullable=False),
        sa.Column(
            "reference_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_leave_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
    )
    op.create_index("ix_hr_leave_ledger_employee_id", "hr_leave_ledger", ["employee_id"])

    op.create_table(
        "hr_offboarding_cases",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("separation_type", sa.String(40), nullable=False),
        sa.Column("notice_date", sa.Date(), nullable=True),
        sa.Column("last_working_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'initiated'")),
        sa.Column("exit_interview_notes", sa.Text(), nullable=True),
        sa.Column("rehire_eligible", sa.Boolean(), nullable=True),
        sa.Column("access_revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "initiated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "completed_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_hr_offboarding_cases_employee_id", "hr_offboarding_cases", ["employee_id"])

    op.create_table(
        "hr_clearance_steps",
        _uuid_pk(),
        sa.Column(
            "offboarding_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_offboarding_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("department_area", sa.String(40), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column(
            "assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "cleared_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_goals",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cycle_name", sa.String(80), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column(
            "weight_percent", sa.Numeric(5, 2), nullable=False, server_default=sa.text("100.00")
        ),
        sa.Column(
            "progress_percent", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0.00")
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'active'")),
        *_timestamps(),
    )

    op.create_table(
        "hr_review_cycles",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'draft'")),
        *_timestamps(),
    )

    op.create_table(
        "hr_reviews",
        _uuid_pk(),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_review_cycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("self_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("manager_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("final_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("summary_notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'draft'")),
        *_timestamps(),
    )

    op.create_table(
        "hr_training_courses",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("category", sa.String(60), nullable=False, server_default=sa.text("'safety'")),
        sa.Column("provider", sa.String(160), nullable=True),
        sa.Column("duration_hours", sa.Numeric(5, 2), nullable=True),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamps(),
    )

    op.create_table(
        "hr_training_enrollments",
        _uuid_pk(),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_training_courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'enrolled'")),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("completed_date", sa.Date(), nullable=True),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_certifications",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("issuing_body", sa.String(160), nullable=True),
        sa.Column("certificate_number", sa.String(80), nullable=True),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'valid'")),
        *_timestamps(),
    )
    op.create_index("ix_hr_certifications_expiry_date", "hr_certifications", ["expiry_date"])

    op.create_table(
        "hr_benefit_types",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column(
            "requires_policy_approval", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamps(),
    )

    op.create_table(
        "hr_employee_benefits",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "benefit_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_benefit_types.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("coverage_notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'active'")),
        *_timestamps(),
    )

    op.create_table(
        "hr_reimbursement_claims",
        _uuid_pk(),
        sa.Column("claim_code", sa.String(40), nullable=False, unique=True),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("claim_type", sa.String(40), nullable=False),
        sa.Column("claim_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default=sa.text("'LKR'")),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "receipt_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'submitted'")),
        sa.Column(
            "decided_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_compensation_terms",
        _uuid_pk(),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column(
            "pay_frequency", sa.String(30), nullable=False, server_default=sa.text("'monthly'")
        ),
        sa.Column("currency", sa.String(10), nullable=False, server_default=sa.text("'LKR'")),
        sa.Column("base_salary_encrypted", sa.Text(), nullable=False),
        sa.Column("base_salary_masked", sa.String(64), nullable=False),
        sa.Column("allowances_encrypted", sa.Text(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_payroll_policies",
        _uuid_pk(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "rules_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "second_approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_payroll_periods",
        _uuid_pk(),
        sa.Column("period_code", sa.String(40), nullable=False, unique=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("pay_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'open'")),
        *_timestamps(),
    )

    op.create_table(
        "hr_payroll_runs",
        _uuid_pk(),
        sa.Column(
            "payroll_period_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_payroll_periods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_payroll_policies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'draft'")),
        sa.Column(
            "prepared_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hr_payroll_lines",
        _uuid_pk(),
        sa.Column(
            "payroll_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_payroll_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gross_encrypted", sa.Text(), nullable=False),
        sa.Column("deductions_encrypted", sa.Text(), nullable=False),
        sa.Column("net_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "breakdown_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
    )

    op.create_table(
        "hr_cases",
        _uuid_pk(),
        sa.Column("case_code", sa.String(40), nullable=False, unique=True),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("case_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default=sa.text("'medium'")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("details_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'open'")),
        sa.Column(
            "opened_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "closed_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        *_timestamps(),
    )


def downgrade() -> None:
    op.drop_table("hr_cases")
    op.drop_table("hr_payroll_lines")
    op.drop_table("hr_payroll_runs")
    op.drop_table("hr_payroll_periods")
    op.drop_table("hr_payroll_policies")
    op.drop_table("hr_compensation_terms")
    op.drop_table("hr_reimbursement_claims")
    op.drop_table("hr_employee_benefits")
    op.drop_table("hr_benefit_types")
    op.drop_index("ix_hr_certifications_expiry_date", table_name="hr_certifications")
    op.drop_table("hr_certifications")
    op.drop_table("hr_training_enrollments")
    op.drop_table("hr_training_courses")
    op.drop_table("hr_reviews")
    op.drop_table("hr_review_cycles")
    op.drop_table("hr_goals")
    op.drop_table("hr_clearance_steps")
    op.drop_index("ix_hr_offboarding_cases_employee_id", table_name="hr_offboarding_cases")
    op.drop_table("hr_offboarding_cases")
    op.drop_index("ix_hr_leave_ledger_employee_id", table_name="hr_leave_ledger")
    op.drop_table("hr_leave_ledger")
    op.drop_index("ix_hr_leave_requests_status", table_name="hr_leave_requests")
    op.drop_index("ix_hr_leave_requests_employee_id", table_name="hr_leave_requests")
    op.drop_table("hr_leave_requests")
    op.drop_table("hr_leave_policies")
    op.drop_table("hr_leave_types")
    op.drop_table("hr_overtime_requests")
    op.drop_table("hr_timesheets")
    op.drop_table("hr_attendance_corrections")
    op.drop_index("ix_hr_attendance_entries_work_date", table_name="hr_attendance_entries")
    op.drop_table("hr_attendance_entries")
    op.drop_table("hr_shift_assignments")
    op.drop_table("hr_holidays")
    op.drop_index("ix_hr_hr_requests_status", table_name="hr_hr_requests")
    op.drop_table("hr_hr_requests")
    op.drop_table("hr_letter_templates")
    op.drop_table("hr_policy_acknowledgements")
    op.drop_table("hr_policy_documents")
    op.drop_table("hr_document_versions")
    op.drop_constraint(
        "fk_hr_candidates_resume_document_id", "hr_candidates", type_="foreignkey"
    )
    op.drop_index("ix_hr_documents_expiry_date", table_name="hr_documents")
    op.drop_index("ix_hr_documents_employee_id", table_name="hr_documents")
    op.drop_table("hr_documents")
    op.drop_table("hr_onboarding_tasks")
    op.drop_index("ix_hr_onboarding_cases_employee_id", table_name="hr_onboarding_cases")
    op.drop_table("hr_onboarding_cases")
    op.drop_index("ix_hr_offers_status", table_name="hr_offers")
    op.drop_table("hr_offers")
    op.drop_table("hr_interviews")
    op.drop_index("ix_hr_applications_stage", table_name="hr_applications")
    op.drop_table("hr_applications")
    op.drop_index("ix_hr_candidates_email", table_name="hr_candidates")
    op.drop_index("ix_hr_candidates_full_name", table_name="hr_candidates")
    op.drop_table("hr_candidates")
    op.drop_index("ix_hr_requisitions_status", table_name="hr_requisitions")
    op.drop_table("hr_requisitions")
    op.drop_index("ix_hr_access_requests_status", table_name="hr_access_requests")
    op.drop_index("ix_hr_access_requests_employee_id", table_name="hr_access_requests")
    op.drop_table("hr_access_requests")
    op.drop_index("ix_hr_employment_history_employee_id", table_name="hr_employment_history")
    op.drop_table("hr_employment_history")
    op.drop_table("hr_employee_private")
    op.drop_constraint(
        "fk_hr_departments_head_employee_id", "hr_departments", type_="foreignkey"
    )
    op.drop_index("ix_hr_employees_employment_status", table_name="hr_employees")
    op.drop_index("ix_hr_employees_full_name", table_name="hr_employees")
    op.drop_table("hr_employees")
    op.drop_table("hr_positions")
    op.drop_table("hr_departments")
    op.drop_table("hr_work_calendars")
