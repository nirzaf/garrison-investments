import hashlib
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class HrWorkCalendar(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hr_work_calendars"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'published')", name="hr_calendar_status"
        ),
        CheckConstraint(
            "status = 'draft' OR (effective_from IS NOT NULL AND effective_to IS NOT NULL "
            "AND effective_from <= effective_to AND timezone IS NOT NULL)",
            name="hr_calendar_effective_window",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    work_days_json: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("""'["MON","TUE","WED","THU","FRI"]'::jsonb""")
    )
    standard_start_time: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=text("'08:30:00'")
    )
    standard_end_time: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=text("'17:00:00'")
    )
    daily_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("8.00")
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    project_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'draft'"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    created_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_work_calendar_created_by_id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_work_calendar_submitted_by_id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_work_calendar_approved_by_id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HrDepartment(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hr_departments"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    parent_department_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    head_employee_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey(
            "hr_employees.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_hr_departments_head_employee_id",
        ),
        nullable=True,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrPosition(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hr_positions"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    department_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    grade: Mapped[str | None] = mapped_column(String(40), nullable=True)
    employment_category: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'permanent'")
    )
    headcount_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    approved_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrEmployee(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hr_employees"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    work_email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    work_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    employment_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'draft'"), index=True
    )
    employment_category: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'permanent'")
    )
    join_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    termination_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    department_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    position_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_positions.id", ondelete="SET NULL"),
        nullable=True,
    )
    primary_project_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    manager_employee_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    line_manager_reviewer_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    work_location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    work_calendar_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_work_calendars.id", ondelete="SET NULL"),
        nullable=True,
    )
    record_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class HrEmployeePrivate(TimestampMixin, Base):
    __tablename__ = "hr_employee_private"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    national_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    national_id_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    passport_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    passport_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    marital_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(80), nullable=True)
    personal_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    personal_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    residential_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    emergency_contact_relation: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bank_branch: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bank_account_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_account_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tax_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_id_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    epf_number_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    epf_number_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    etf_number_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    etf_number_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    medical_notes_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class HrEmploymentHistory(TimestampMixin, Base):
    __tablename__ = "hr_employment_history"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    previous_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class HrEmploymentPeriod(Base):
    __tablename__ = "hr_employment_periods"
    __table_args__ = (
        Index(
            "uq_hr_employment_periods_open",
            "employee_id",
            unique=True,
            postgresql_where=text("ended_on IS NULL"),
        ),
        Index("ix_hr_employment_periods_employee_started", "employee_id", "started_on", "id"),
        CheckConstraint(
            "(ended_on IS NULL AND started_on IS NOT NULL AND separation_case_id IS NULL) OR "
            "(ended_on IS NOT NULL AND separation_case_id IS NOT NULL "
            "AND (started_on IS NULL OR started_on <= ended_on))",
            name="employment_period_dates",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("uuid_generate_v4()"))
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr_employees.id", ondelete="RESTRICT"))
    started_on: Mapped[date | None] = mapped_column(Date)
    ended_on: Mapped[date | None] = mapped_column(Date)
    separation_case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hr_offboarding_cases.id", ondelete="RESTRICT"), unique=True
    )
    rehire_change_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hr_employment_changes.id", ondelete="RESTRICT"), unique=True
    )
    onboarding_case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hr_onboarding_cases.id", ondelete="RESTRICT"), unique=True
    )


class HrEmploymentChange(TimestampMixin, Base):
    __tablename__ = "hr_employment_changes"
    __table_args__ = (
        Index("ix_hr_employment_changes_employee_created", "employee_id", "created_at", "id"),
        CheckConstraint(
            "(status = 'proposed' AND decided_by IS NULL AND decided_at IS NULL) OR "
            "(status IN ('approved', 'rejected', 'applied') AND decided_by IS NOT NULL "
            "AND decided_by <> proposed_by AND decided_at IS NOT NULL)",
            name="employment_change_review",
        ),
        CheckConstraint(
            "(status = 'applied' AND applied_by IS NOT NULL AND applied_at IS NOT NULL "
            "AND applied_employee_revision = employee_revision + 1 "
            "AND applied_employee_revision IS NOT NULL) OR "
            "(status <> 'applied' AND applied_by IS NULL AND applied_at IS NULL "
            "AND applied_employee_revision IS NULL)",
            name="employment_change_apply",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("uuid_generate_v4()"))
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr_employees.id", ondelete="RESTRICT"))
    change_type: Mapped[str] = mapped_column(String(20))
    effective_date: Mapped[date] = mapped_column(Date)
    employee_revision: Mapped[int]
    updates: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="proposed")
    proposed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    applied_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_employee_revision: Mapped[int | None]


class HrAccessRequest(TimestampMixin, Base):
    __tablename__ = "hr_access_requests"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    requested_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    portal_access_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    business_title_source: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'draft'"), index=True
    )
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    hr_decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    hr_approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    hr_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_actioned_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    admin_actioned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    linked_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class HrProjectAssignmentRequest(TimestampMixin, Base):
    __tablename__ = "hr_project_assignment_requests"
    __table_args__ = (
        CheckConstraint("action IN ('assign', 'revoke')", name="hr_assignment_action"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="hr_assignment_status"
        ),
        Index(
            "uq_hr_project_assignment_pending",
            "project_id",
            "employee_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    linked_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'pending'")
    )
    role_in_project: Mapped[str | None] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    decision_note: Mapped[str | None] = mapped_column(String(500))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HrRequisition(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hr_requisitions"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    requisition_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    department_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    position_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_positions.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    employment_category: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'permanent'")
    )
    headcount_requested: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'draft'"), index=True
    )
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_join_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class HrCandidate(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hr_candidates"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    candidate_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    current_organization: Mapped[str | None] = mapped_column(String(160), nullable=True)
    years_experience: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    resume_document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey(
            "hr_documents.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_hr_candidates_resume_document_id",
        ),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'active'"))
    created_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class HrApplication(TimestampMixin, Base):
    __tablename__ = "hr_applications"
    __table_args__ = (
        UniqueConstraint("requisition_id", "candidate_id", name="uq_hr_application_req_cand"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    requisition_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_requisitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'applied'"), index=True
    )
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    screening_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawal_reason: Mapped[str | None] = mapped_column(String(500))
    retention_decision: Mapped[str | None] = mapped_column(String(32))
    retention_review_on: Mapped[date | None] = mapped_column(Date)
    retention_policy_reference: Mapped[str | None] = mapped_column(String(120))
    assigned_recruiter_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class HrCandidateCorrespondence(TimestampMixin, Base):
    __tablename__ = "hr_candidate_correspondence"
    __table_args__ = (
        Index("ix_hr_candidate_correspondence_application", "application_id", "created_at", "id"),
        CheckConstraint(
            "(status = 'draft' AND decided_by IS NULL AND decided_at IS NULL "
            "AND reason_encrypted IS NULL) OR "
            "(status IN ('approved', 'rejected') AND decided_by IS NOT NULL "
            "AND decided_at IS NOT NULL AND decided_by <> prepared_by "
            "AND ((status = 'rejected') = (reason_encrypted IS NOT NULL)))",
            name="candidate_correspondence_decision",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_applications.id", ondelete="RESTRICT")
    )
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_letter_templates.id", ondelete="RESTRICT")
    )
    content_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), server_default="draft")
    prepared_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_encrypted: Mapped[str | None] = mapped_column(Text)


class HrInterview(TimestampMixin, Base):
    __tablename__ = "hr_interviews"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    application_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    interview_type: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'technical'")
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interviewer_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    interviewer_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    recommendation: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'pending'")
    )
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    feedback_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'scheduled'")
    )


class HrOffer(TimestampMixin, Base):
    __tablename__ = "hr_offers"
    __table_args__ = (CheckConstraint("version_number >= 1", name="version_positive"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    offer_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    application_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    proposed_title: Mapped[str] = mapped_column(String(160), nullable=False)
    proposed_department_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    proposed_position_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_positions.id", ondelete="SET NULL"),
        nullable=True,
    )
    proposed_join_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    proposed_salary_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_salary_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'LKR'"))
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'draft'"), index=True
    )
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    document_version_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey(
            "hr_document_versions.id", name="fk_hr_offer_document_version", ondelete="RESTRICT"
        ),
    )
    supersedes_offer_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("hr_offers.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("hr_offers.id", ondelete="SET NULL"), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_employee_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrOnboardingCase(TimestampMixin, Base):
    __tablename__ = "hr_onboarding_cases"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    offer_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("hr_offers.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'open'"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    probation_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HrOnboardingTask(TimestampMixin, Base):
    __tablename__ = "hr_onboarding_tasks"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    onboarding_case_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_onboarding_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    assignee_role: Mapped[str] = mapped_column(String(40), nullable=False)
    assigned_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'pending'")
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrDocument(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "hr_documents"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_candidates.id", ondelete="CASCADE"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'ordinary'")
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    issuing_authority: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'active'"))
    alert_days_before: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    is_employee_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class HrDocumentVersion(TimestampMixin, Base):
    __tablename__ = "hr_document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_hr_doc_version"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrPolicyDocument(TimestampMixin, Base):
    __tablename__ = "hr_policy_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "document_version_number"],
            ["hr_document_versions.document_id", "hr_document_versions.version_number"],
            name="fk_hr_policy_exact_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "document_version_number IS NULL OR document_id IS NOT NULL",
            name="hr_policy_version_requires_document",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'1.0'"))
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    content_summary: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    requires_acknowledgement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    document_version_number: Mapped[int | None] = mapped_column(Integer)
    supersedes_policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "hr_policy_documents.id", name="fk_hr_policy_preceding_edition", ondelete="RESTRICT"
        )
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    published_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HrPolicyAcknowledgement(TimestampMixin, Base):
    __tablename__ = "hr_policy_acknowledgements"
    __table_args__ = (UniqueConstraint("policy_id", "employee_id", name="uq_hr_policy_ack_emp"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    policy_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_policy_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrLetterTemplate(TimestampMixin, Base):
    __tablename__ = "hr_letter_templates"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    letter_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_template: Mapped[str] = mapped_column(String(255), nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    requires_hr_manager: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class HrIssuedLetter(TimestampMixin, Base):
    __tablename__ = "hr_issued_letters"
    __table_args__ = (
        Index("ix_hr_issued_letters_employee_created", "employee_id", "created_at", "id"),
        CheckConstraint(
            "(status = 'draft' AND decided_by IS NULL AND decided_at IS NULL "
            "AND reason_encrypted IS NULL) OR "
            "(status IN ('issued', 'rejected') AND decided_by IS NOT NULL "
            "AND decided_at IS NOT NULL AND decided_by <> prepared_by "
            "AND ((status = 'rejected') = (reason_encrypted IS NOT NULL)))",
            name="hr_letter_decision",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr_employees.id", ondelete="RESTRICT"))
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_letter_templates.id", ondelete="RESTRICT")
    )
    employee_revision: Mapped[int]
    compensation_term_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "hr_compensation_terms.id", name="fk_hr_letter_compensation_term", ondelete="RESTRICT"
        )
    )
    content_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), server_default="draft")
    prepared_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_encrypted: Mapped[str | None] = mapped_column(Text)


class HrServiceRequest(TimestampMixin, Base):
    __tablename__ = "hr_hr_requests"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    request_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'open'"), index=True
    )
    assigned_to_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_letter_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "hr_issued_letters.id", name="fk_hr_request_generated_letter", ondelete="RESTRICT"
        )
    )
    generated_document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_documents.id", ondelete="SET NULL"),
        nullable=True,
    )


class HrHoliday(TimestampMixin, Base):
    __tablename__ = "hr_holidays"
    __table_args__ = (
        UniqueConstraint("calendar_id", "holiday_date", name="uq_hr_holiday_cal_date"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    calendar_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_work_calendars.id", ondelete="CASCADE"),
        nullable=False,
    )
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    holiday_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'public'")
    )
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class HrShiftAssignment(TimestampMixin, Base):
    __tablename__ = "hr_shift_assignments"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    calendar_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_work_calendars.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    shift_name: Mapped[str] = mapped_column(String(80), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    assigned_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class HrRosterAllocation(TimestampMixin, Base):
    __tablename__ = "hr_roster_allocations"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at AND planned_hours > 0", name="hr_roster_interval"),
        CheckConstraint(
            "(cancelled_at IS NULL AND cancellation_reason IS NULL) OR "
            "(cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)",
            name="hr_roster_cancellation",
        ),
        Index("ix_hr_roster_date_id", "work_date", "id"),
        Index(
            "ix_hr_roster_active_employee_start",
            "employee_id",
            "starts_at",
            postgresql_where=text("cancelled_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr_employees.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    calendar_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_work_calendars.id", ondelete="RESTRICT")
    )
    shift_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hr_shift_assignments.id", ondelete="RESTRICT")
    )
    employee_name: Mapped[str] = mapped_column(String(255))
    project_name: Mapped[str] = mapped_column(String(200))
    work_date: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    planned_hours: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))


class HrManagerRecommendationMixin:
    record_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    requires_manager_recommendation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    manager_recommendation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    manager_recommended_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    manager_recommended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HrAttendanceEntry(HrManagerRecommendationMixin, TimestampMixin, Base):
    __tablename__ = "hr_attendance_entries"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_hr_attendance_emp_date"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    calendar_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey(
            "hr_work_calendars.id", name="fk_hr_attendance_schedule_calendar", ondelete="RESTRICT"
        ),
        nullable=True,
    )
    shift_assignment_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey(
            "hr_shift_assignments.id", name="fk_hr_attendance_schedule_shift", ondelete="RESTRICT"
        ),
        nullable=True,
    )
    scheduled_workday: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    attendance_status: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'submitted'")
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worked_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0.00")
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'manual'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    site_submission_revision: Mapped[int | None] = mapped_column(Integer)


class HrSiteAttendanceSubmission(TimestampMixin, Base):
    __tablename__ = "hr_site_attendance_submissions"

    entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_attendance_entries.id", ondelete="RESTRICT"), primary_key=True
    )
    submission_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    submitted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    engineer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    requirements: Mapped[dict] = mapped_column(JSONB, nullable=False)
    engineer_decision: Mapped[str | None] = mapped_column(String(20))
    engineer_comments: Mapped[str | None] = mapped_column(Text)
    engineer_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hr_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    hr_decision: Mapped[str | None] = mapped_column(String(20))
    hr_comments: Mapped[str | None] = mapped_column(Text)
    hr_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HrAttendanceCorrection(TimestampMixin, Base):
    __tablename__ = "hr_attendance_corrections"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    attendance_entry_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_attendance_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    entry_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_status: Mapped[str] = mapped_column(String(30), nullable=False)
    requested_check_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_check_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_worked_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("8.00")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'submitted'")
    )
    requested_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrTimesheet(HrManagerRecommendationMixin, TimestampMixin, Base):
    __tablename__ = "hr_timesheets"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "period_start", "period_end", name="uq_hr_timesheet_emp_period"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    regular_hours: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default=text("0.00")
    )
    overtime_hours: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default=text("0.00")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'draft'"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrOvertimeRequest(HrManagerRecommendationMixin, TimestampMixin, Base):
    __tablename__ = "hr_overtime_requests"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    approved_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'submitted'")
    )
    requested_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrLeaveType(TimestampMixin, Base):
    __tablename__ = "hr_leave_types"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    requires_attachment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    allow_half_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrLeavePolicy(TimestampMixin, Base):
    __tablename__ = "hr_leave_policies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('legacy', 'draft', 'approved', 'rejected')",
            name="hr_leave_policy_status",
        ),
        CheckConstraint(
            "status = 'legacy' OR (effective_from IS NOT NULL AND effective_to IS NOT NULL "
            "AND effective_from <= effective_to)",
            name="hr_leave_policy_effective_window",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    leave_type_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_leave_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    employment_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    annual_entitlement_days: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    accrual_frequency: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'annual'")
    )
    prorate_by_calendar_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    max_carry_forward_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0.00")
    )
    expire_excess_on_rollover: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    allow_negative_balance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_hr_leave_policy_creator", ondelete="SET NULL"),
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500))


class HrLeaveRequest(HrManagerRecommendationMixin, TimestampMixin, Base):
    __tablename__ = "hr_leave_requests"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    leave_type_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_leave_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_requested: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    scheduled_work_dates: Mapped[list[date] | None] = mapped_column(ARRAY(Date), nullable=True)
    is_half_day: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    half_day_period: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'submitted'"), index=True
    )
    requested_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrLeaveDateEvidence(Base):
    __tablename__ = "hr_leave_date_evidence"
    __table_args__ = (
        Index("ix_hr_leave_date_evidence_request_created", "request_id", "created_at", "id"),
        CheckConstraint(
            "(status = 'submitted' AND decided_by_id IS NULL AND decided_at IS NULL) OR "
            "(status IN ('approved', 'rejected') AND decided_by_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND decided_by_id <> submitted_by_id)",
            name="leave_date_evidence_decision",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_leave_requests.id", ondelete="RESTRICT")
    )
    ledger_id: Mapped[UUID] = mapped_column(ForeignKey("hr_leave_ledger.id", ondelete="RESTRICT"))
    request_revision: Mapped[int] = mapped_column(Integer)
    detail_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="submitted")
    submitted_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HrLeaveLedger(TimestampMixin, Base):
    __tablename__ = "hr_leave_ledger"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    leave_type_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_leave_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    entry_type: Mapped[str] = mapped_column(String(30), nullable=False)
    days_delta: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    leave_year: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_request_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_leave_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class HrLeaveAccrual(TimestampMixin, Base):
    __tablename__ = "hr_leave_accruals"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "leave_type_id", "period_start", name="uq_hr_leave_accrual_period"
        ),
        CheckConstraint("period_start <= period_end", name="leave_accrual_dates"),
        CheckConstraint(
            "(eligible_from IS NULL AND eligible_through IS NULL) OR "
            "(eligible_from IS NOT NULL AND eligible_through IS NOT NULL AND "
            "period_start <= eligible_from AND eligible_from <= eligible_through "
            "AND eligible_through <= period_end)",
            name="leave_accrual_eligible_dates",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr_employees.id", ondelete="RESTRICT"))
    leave_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_leave_types.id", ondelete="RESTRICT")
    )
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("hr_leave_policies.id", ondelete="RESTRICT"))
    ledger_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_leave_ledger.id", ondelete="RESTRICT"), unique=True
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    eligible_from: Mapped[date | None] = mapped_column(Date)
    eligible_through: Mapped[date | None] = mapped_column(Date)
    plan_digest: Mapped[str] = mapped_column(String(64))


class HrLeaveRollover(TimestampMixin, Base):
    __tablename__ = "hr_leave_rollovers"
    __table_args__ = (
        UniqueConstraint("employee_id", "leave_type_id", "source_year"),
        CheckConstraint("carried_days >= 0 AND expired_days >= 0", name="nonnegative_days"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr_employees.id", ondelete="RESTRICT"))
    leave_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_leave_types.id", ondelete="RESTRICT")
    )
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("hr_leave_policies.id", ondelete="RESTRICT"))
    source_year: Mapped[int] = mapped_column(Integer)
    carried_days: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    expired_days: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    transferred_out_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hr_leave_ledger.id", ondelete="RESTRICT"), unique=True
    )
    transferred_in_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hr_leave_ledger.id", ondelete="RESTRICT"), unique=True
    )
    expiry_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hr_leave_ledger.id", ondelete="RESTRICT"), unique=True
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    plan_digest: Mapped[str] = mapped_column(String(64))


class HrOffboardingCase(TimestampMixin, Base):
    __tablename__ = "hr_offboarding_cases"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    separation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    notice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_working_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'initiated'")
    )
    exit_interview_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rehire_eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    access_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    initiated_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HrClearanceStep(TimestampMixin, Base):
    __tablename__ = "hr_clearance_steps"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    offboarding_case_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_offboarding_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_area: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    assigned_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'pending'")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleared_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HrOffboardingCustody(Base):
    __tablename__ = "hr_offboarding_custody"
    __table_args__ = (
        Index("ix_hr_offboarding_custody_case_recorded", "case_id", "recorded_at", "id"),
        UniqueConstraint("case_id", "evidence_reference"),
        CheckConstraint(
            "(area = 'store_inventory' AND device_reference IS NULL AND "
            "((kind = 'returned' AND movement_id IS NOT NULL) OR "
            "(kind IN ('cleared', 'waived', 'flagged') AND movement_id IS NULL))) OR "
            "(area = 'it_admin' AND movement_id IS NULL AND "
            "((kind = 'cleared' AND device_reference IS NULL) OR "
            "(kind IN ('returned', 'waived', 'flagged') AND device_reference IS NOT NULL)))",
            name="hr_custody_area_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_offboarding_cases.id", ondelete="RESTRICT")
    )
    area: Mapped[str] = mapped_column(String(16), server_default=text("'store_inventory'"))
    device_reference: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(12))
    movement_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_movements.id", ondelete="RESTRICT"), unique=True
    )
    evidence_reference: Mapped[str] = mapped_column(String(100))
    recorded_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HrSeparationSettlement(Base):
    __tablename__ = "hr_separation_settlements"
    __table_args__ = (
        Index("ix_hr_separation_settlements_case_created", "case_id", "created_at", "id"),
        Index(
            "uq_hr_separation_settlements_open",
            "case_id",
            unique=True,
            postgresql_where=text("status = 'proposed'"),
        ),
        UniqueConstraint("case_id", "evidence_reference"),
        CheckConstraint(
            "outcome IN ('outstanding', 'settled', 'nothing_due')",
            name="separation_settlement_outcome",
        ),
        CheckConstraint(
            "(status = 'proposed' AND reviewed_by_id IS NULL AND reviewed_at IS NULL "
            "AND review_reference IS NULL) OR "
            "(status IN ('approved', 'rejected') AND reviewed_by_id IS NOT NULL "
            "AND reviewed_by_id <> proposed_by_id AND reviewed_at IS NOT NULL "
            "AND review_reference IS NOT NULL)",
            name="separation_settlement_review",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_offboarding_cases.id", ondelete="RESTRICT")
    )
    outcome: Mapped[str] = mapped_column(String(16))
    evidence_reference: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'proposed'"))
    proposed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reference: Mapped[str | None] = mapped_column(String(100))


# --- Policy-Gated P2 Models (HR-019 to HR-024) ---


class HrGoal(TimestampMixin, Base):
    __tablename__ = "hr_goals"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    cycle_name: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    weight_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("100.00")
    )
    progress_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0.00")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'active'"))


class HrReviewCycle(TimestampMixin, Base):
    __tablename__ = "hr_review_cycles"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    rating_scale: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'draft'"))


class HrReview(TimestampMixin, Base):
    __tablename__ = "hr_reviews"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    cycle_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_review_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_employee_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    self_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    manager_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    final_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    summary_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'draft'"))


class HrPerformanceEvent(Base):
    __tablename__ = "hr_performance_events"
    __table_args__ = (UniqueConstraint("review_id", "revision"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    review_id: Mapped[UUID] = mapped_column(ForeignKey("hr_reviews.id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32))
    participant: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    notes: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[str | None] = mapped_column(String(60))
    previous_reviewer_id: Mapped[UUID | None] = mapped_column()
    replacement_reviewer_id: Mapped[UUID | None] = mapped_column()
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HrTrainingCourse(TimestampMixin, Base):
    __tablename__ = "hr_training_courses"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        String(60), nullable=False, server_default=text("'safety'")
    )
    provider: Mapped[str | None] = mapped_column(String(160), nullable=True)
    duration_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class HrTrainingRequirement(TimestampMixin, Base):
    __tablename__ = "hr_training_requirements"
    __table_args__ = (
        CheckConstraint(
            "position_id IS NOT NULL OR project_id IS NOT NULL", name="training_rule_scope"
        ),
        UniqueConstraint(
            "course_id", "position_id", "project_id", postgresql_nulls_not_distinct=True
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("uuid_generate_v4()"))
    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_training_courses.id", ondelete="RESTRICT")
    )
    position_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hr_positions.id", ondelete="RESTRICT")
    )
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class HrTrainingEnrollment(TimestampMixin, Base):
    __tablename__ = "hr_training_enrollments"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_training_courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'enrolled'")
    )
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)


class HrCertification(TimestampMixin, Base):
    __tablename__ = "hr_certifications"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    issuing_body: Mapped[str | None] = mapped_column(String(160), nullable=True)
    certificate_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'valid'"))


class HrTrainingCompletion(Base):
    __tablename__ = "hr_training_completions"

    enrollment_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_training_enrollments.id", ondelete="RESTRICT"), primary_key=True
    )
    certificate_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_certifications.id", ondelete="RESTRICT"), unique=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_document_versions.id", ondelete="RESTRICT"), unique=True
    )
    verified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HrBenefitType(TimestampMixin, Base):
    __tablename__ = "hr_benefit_types"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    requires_policy_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    reimbursement_ceiling: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    reimbursement_currency: Mapped[str | None] = mapped_column(String(3))
    allows_advances: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    proposed_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_hr_benefit_policy_proposer", ondelete="SET NULL")
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_hr_benefit_policy_approver", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HrEmployeeBenefit(TimestampMixin, Base):
    __tablename__ = "hr_employee_benefits"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    benefit_type_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_benefit_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    coverage_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'active'"))


class HrReimbursementClaim(TimestampMixin, Base):
    __tablename__ = "hr_reimbursement_claims"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    claim_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_type: Mapped[str] = mapped_column(String(40), nullable=False)
    benefit_assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "hr_employee_benefits.id", name="fk_hr_claim_benefit_assignment", ondelete="RESTRICT"
        )
    )
    claim_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'LKR'"))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    receipt_version_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey(
            "hr_document_versions.id", name="fk_hr_claim_receipt_version", ondelete="RESTRICT"
        ),
    )
    submitted_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_hr_claim_submitter", ondelete="SET NULL"),
    )
    settlement_reference: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'submitted'")
    )
    decided_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HrEmployeeAdvance(TimestampMixin, Base):
    __tablename__ = "hr_employee_advances"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("uuid_generate_v4()"))
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr_employees.id", ondelete="RESTRICT"))
    benefit_assignment_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_employee_benefits.id", ondelete="RESTRICT"), index=True
    )
    submitted_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    requested_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'submitted'"))
    decided_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disbursement_reference: Mapped[str | None] = mapped_column(String(100))
    disbursed_on: Mapped[date | None] = mapped_column(Date)


class HrAdvanceRecovery(TimestampMixin, Base):
    __tablename__ = "hr_advance_recoveries"
    __table_args__ = (
        UniqueConstraint("advance_id", "reference", name="uq_hr_advance_recovery_reference"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("uuid_generate_v4()"))
    advance_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_employee_advances.id", ondelete="RESTRICT")
    )
    recorded_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reference: Mapped[str] = mapped_column(String(100))
    occurred_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))


class HrCompensationTerm(TimestampMixin, Base):
    __tablename__ = "hr_compensation_terms"
    __table_args__ = (
        CheckConstraint(
            "approval_status IN ('proposed', 'approved', 'rejected')",
            name="hr_compensation_approval_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    pay_frequency: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'monthly'")
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'LKR'"))
    base_salary_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    base_salary_masked: Mapped[str] = mapped_column(String(64), nullable=False)
    allowances_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'approved'")
    )
    rejection_reason_encrypted: Mapped[str | None] = mapped_column(Text)
    proposed_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_hr_compensation_proposer", ondelete="SET NULL"),
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HrPayrollPolicy(TimestampMixin, Base):
    __tablename__ = "hr_payroll_policies"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    rules_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    controlled_record: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    second_approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HrPayrollPeriod(TimestampMixin, Base):
    __tablename__ = "hr_payroll_periods"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    period_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    pay_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'open'"))


class HrPayrollRun(TimestampMixin, Base):
    __tablename__ = "hr_payroll_runs"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    payroll_period_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_payroll_periods.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_payroll_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'draft'"))
    prepared_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_encrypted: Mapped[str | None] = mapped_column(Text)

    @property
    def snapshot_digest(self) -> str | None:
        if self.snapshot_encrypted is None:
            return None
        return hashlib.sha256(self.snapshot_encrypted.encode()).hexdigest()


class HrPayrollAdjustment(TimestampMixin, Base):
    __tablename__ = "hr_payroll_adjustments"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_payroll_runs.id", ondelete="RESTRICT"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT")
    )
    submitted_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), server_default="submitted")
    detail_encrypted: Mapped[str] = mapped_column(Text)


class HrPayslipPublication(Base):
    __tablename__ = "hr_payslip_publications"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_payroll_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    published_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    snapshot_digest: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HrPayrollExport(Base):
    __tablename__ = "hr_payroll_exports"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_payroll_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    exported_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    snapshot_digest: Mapped[str] = mapped_column(String(64))
    csv_sha256: Mapped[str] = mapped_column(String(64))
    format_version: Mapped[int]
    exported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HrPayrollLine(TimestampMixin, Base):
    __tablename__ = "hr_payroll_lines"
    __table_args__ = (Index("ix_hr_payroll_lines_run_employee", "payroll_run_id", "employee_id"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    payroll_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_payroll_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    gross_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    deductions_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    net_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    breakdown_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class HrPayrollClosure(Base):
    __tablename__ = "hr_payroll_closures"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_payroll_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    closed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    snapshot_digest: Mapped[str] = mapped_column(String(64))
    csv_sha256: Mapped[str] = mapped_column(String(64))
    settlement_digest: Mapped[str] = mapped_column(String(64))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HrPayrollCorrection(Base):
    __tablename__ = "hr_payroll_corrections"
    __table_args__ = (
        Index("ix_hr_payroll_corrections_line_created", "line_id", "created_at", "id"),
        CheckConstraint(
            "(status = 'submitted' AND decided_by_id IS NULL AND decided_at IS NULL) OR "
            "(status IN ('approved', 'rejected') AND decided_by_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND decided_by_id <> submitted_by_id)",
            name="payroll_correction_decision",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    line_id: Mapped[UUID] = mapped_column(ForeignKey("hr_payroll_lines.id", ondelete="RESTRICT"))
    previous_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hr_payroll_corrections.id", ondelete="RESTRICT")
    )
    snapshot_digest: Mapped[str] = mapped_column(String(64))
    detail_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="submitted")
    submitted_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HrPayrollSettlementEvent(Base):
    __tablename__ = "hr_payroll_settlement_events"
    __table_args__ = (
        Index("ix_hr_payroll_settlement_run_recorded", "run_id", "recorded_at", "id"),
        CheckConstraint(
            "(kind IN ('paid', 'failed') AND reverses_event_id IS NULL) OR "
            "(kind = 'reversed' AND reverses_event_id IS NOT NULL)",
            name="payroll_settlement_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("hr_payroll_exports.run_id", ondelete="RESTRICT")
    )
    payment_reference: Mapped[UUID] = mapped_column(
        ForeignKey("hr_payroll_lines.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(12))
    amount_encrypted: Mapped[str] = mapped_column(Text)
    reverses_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hr_payroll_settlement_events.id", ondelete="RESTRICT")
    )
    occurred_on: Mapped[date] = mapped_column(Date)
    evidence_encrypted: Mapped[str] = mapped_column(Text)
    evidence_digest: Mapped[str] = mapped_column(String(64), unique=True)
    recorded_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HrCase(TimestampMixin, Base):
    __tablename__ = "hr_cases"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    case_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    employee_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("hr_employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    case_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'medium'")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    details_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'open'"))
    opened_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_by_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
