from csv import writer
from datetime import timedelta
from io import BytesIO, StringIO
from typing import Literal
from uuid import UUID
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.hr import (
    HrAccessRequest,
    HrAttendanceEntry,
    HrCertification,
    HrDepartment,
    HrDocument,
    HrEmployee,
    HrLeaveRequest,
    HrOffboardingCase,
    HrOnboardingCase,
    HrRequisition,
    HrServiceRequest,
    HrTrainingEnrollment,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.hr import (
    HrReportFilters,
    HrReportSiteListResponse,
    HrReportSiteResponse,
    HrReportWindow,
    HrSummaryReportResponse,
)
from app.services.analytics_service import build_xlsx
from app.utils.permissions import PERMISSION_HR_TRAINING_MANAGE, has_permission
from app.utils.time import business_today

HrReportFormat = Literal["xlsx", "csv", "pdf"]
HR_REPORT_MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "pdf": "application/pdf",
}
SEPARATED_STATUSES = ("resigned", "terminated", "archived")


async def list_hr_report_sites(
    session: AsyncSession, *, offset: int, limit: int
) -> HrReportSiteListResponse:
    employee_sites = select(HrEmployee.primary_project_id).where(HrEmployee.deleted_at.is_(None))
    requisition_sites = select(HrRequisition.project_id).where(HrRequisition.deleted_at.is_(None))
    rows = (
        await session.execute(
            select(Project.id, Project.name)
            .where(or_(Project.id.in_(employee_sites), Project.id.in_(requisition_sites)))
            .order_by(Project.name, Project.id)
            .offset(offset)
            .limit(limit + 1)
        )
    ).all()
    return HrReportSiteListResponse(
        items=[HrReportSiteResponse(id=project_id, name=name) for project_id, name in rows[:limit]],
        has_more=len(rows) > limit,
    )


async def count_report_credentials(
    session: AsyncSession, employee_ids: Select[UUID], window: HrReportWindow
) -> int:
    # Shared reporting counts exclude confidential documents and certifications linked to them.
    ordinary_documents = select(HrDocument.id).where(
        HrDocument.category == "ordinary",
        HrDocument.deleted_at.is_(None),
        HrDocument.status == "active",
    )
    documents = select(func.count(HrDocument.id)).where(
        HrDocument.id.in_(ordinary_documents),
        HrDocument.employee_id.in_(employee_ids),
        HrDocument.expiry_date.between(window.date_from, window.date_to),
    )
    certifications = select(func.count(HrCertification.id)).where(
        HrCertification.employee_id.in_(employee_ids),
        HrCertification.status.in_(("valid", "expiring")),
        HrCertification.expiry_date.between(window.date_from, window.date_to),
        or_(
            HrCertification.document_id.is_(None),
            HrCertification.document_id.in_(ordinary_documents),
        ),
    )
    return int(
        await session.scalar(select(documents.scalar_subquery() + certifications.scalar_subquery()))
        or 0
    )


async def get_hr_summary(
    session: AsyncSession, actor: User, filters: HrReportFilters
) -> HrSummaryReportResponse:
    timezone = get_settings().business_timezone
    today = business_today()
    attendance = HrReportWindow(
        date_from=filters.date_from or today - timedelta(days=29), date_to=filters.date_to or today
    )
    due = HrReportWindow(
        date_from=filters.date_from or today, date_to=filters.date_to or today + timedelta(days=30)
    )

    employee_query = select(HrEmployee).where(HrEmployee.deleted_at.is_(None))
    requisitions = select(func.count(HrRequisition.id)).where(
        HrRequisition.deleted_at.is_(None),
        HrRequisition.status.in_(("draft", "submitted", "approved", "open")),
    )
    if filters.project_id is not None:
        employee_query = employee_query.where(HrEmployee.primary_project_id == filters.project_id)
        requisitions = requisitions.where(HrRequisition.project_id == filters.project_id)
    if filters.department_id is not None:
        employee_query = employee_query.where(HrEmployee.department_id == filters.department_id)
        requisitions = requisitions.where(HrRequisition.department_id == filters.department_id)
    employees = employee_query.with_only_columns(
        HrEmployee.id, HrEmployee.department_id, HrEmployee.employment_status
    ).cte("hr_report_employees")
    employee_ids = select(employees.c.id)

    async def count(query: Select[int]) -> int:
        return int(await session.scalar(query) or 0)

    status_counts = await session.execute(
        select(employees.c.employment_status, func.count())
        .group_by(employees.c.employment_status)
        .order_by(employees.c.employment_status)
    )
    by_status = {status: count for status, count in status_counts}
    department_label = func.coalesce(HrDepartment.name, "Unassigned")
    department_counts = await session.execute(
        select(department_label, func.count())
        .select_from(employees)
        .outerjoin(HrDepartment, HrDepartment.id == employees.c.department_id)
        .group_by(department_label)
        .order_by(department_label)
    )
    by_department = {department: count for department, count in department_counts}

    soon = HrReportWindow(date_from=today, date_to=today + timedelta(days=30))
    credentials_soon = await count_report_credentials(session, employee_ids, soon)
    credentials_due = credentials_soon
    if due != soon:
        credentials_due = await count_report_credentials(session, employee_ids, due)

    return HrSummaryReportResponse(
        as_of=today,
        timezone=timezone,
        filters=filters,
        attendance_window=attendance,
        due_window=due,
        total_employees=sum(by_status.values()),
        active_employees=by_status.get("active", 0),
        probation_employees=by_status.get("on_probation", 0),
        draft_employees=by_status.get("draft", 0),
        separated_employees=sum(by_status.get(status, 0) for status in SEPARATED_STATUSES),
        open_requisitions=await count(requisitions),
        pending_access_requests=await count(
            select(func.count(HrAccessRequest.id)).where(
                HrAccessRequest.employee_id.in_(employee_ids),
                HrAccessRequest.status.in_(("draft", "submitted", "hr_approved")),
            )
        ),
        pending_leave_requests=await count(
            select(func.count(HrLeaveRequest.id)).where(
                HrLeaveRequest.employee_id.in_(employee_ids), HrLeaveRequest.status == "submitted"
            )
        ),
        open_onboarding_cases=await count(
            select(func.count(HrOnboardingCase.id)).where(
                HrOnboardingCase.employee_id.in_(employee_ids),
                HrOnboardingCase.status.in_(("open", "in_progress")),
            )
        ),
        open_offboarding_cases=await count(
            select(func.count(HrOffboardingCase.id)).where(
                HrOffboardingCase.employee_id.in_(employee_ids),
                HrOffboardingCase.status.in_(("initiated", "clearance_in_progress")),
            )
        ),
        open_hr_service_requests=await count(
            select(func.count(HrServiceRequest.id)).where(
                HrServiceRequest.employee_id.in_(employee_ids),
                HrServiceRequest.status.in_(("open", "in_review")),
            )
        ),
        expiring_within_30_days=credentials_soon,
        credentials_due=credentials_due,
        attendance_exceptions=await count(
            select(func.count(HrAttendanceEntry.id)).where(
                HrAttendanceEntry.employee_id.in_(employee_ids),
                HrAttendanceEntry.attendance_status.in_(("absent", "half_day")),
                HrAttendanceEntry.scheduled_workday.is_not(False),
                HrAttendanceEntry.work_date.between(attendance.date_from, attendance.date_to),
            )
        ),
        probation_reviews_due=await count(
            select(func.count(func.distinct(HrOnboardingCase.employee_id)))
            .join(employees, HrOnboardingCase.employee_id == employees.c.id)
            .where(
                employees.c.employment_status == "on_probation",
                HrOnboardingCase.probation_end_date.between(due.date_from, due.date_to),
            )
        ),
        training_sessions_due=(
            await count(
                select(func.count(HrTrainingEnrollment.id)).where(
                    HrTrainingEnrollment.employee_id.in_(employee_ids),
                    HrTrainingEnrollment.status == "enrolled",
                    HrTrainingEnrollment.scheduled_date.between(due.date_from, due.date_to),
                )
            )
            if has_permission(actor, PERMISSION_HR_TRAINING_MANAGE)
            else None
        ),
        by_department=by_department,
        by_employment_status=by_status,
    )


def build_hr_summary_export(
    summary: HrSummaryReportResponse, output_format: HrReportFormat
) -> bytes:
    counts = {
        "Total employees": summary.total_employees,
        "Active employees": summary.active_employees,
        "On probation": summary.probation_employees,
        "Draft employees": summary.draft_employees,
        "Separated employees": summary.separated_employees,
        "Open requisitions": summary.open_requisitions,
        "Pending access requests": summary.pending_access_requests,
        "Pending leave requests": summary.pending_leave_requests,
        "Open onboarding cases": summary.open_onboarding_cases,
        "Open offboarding cases": summary.open_offboarding_cases,
        "Open HR service requests": summary.open_hr_service_requests,
        "Credentials due": summary.credentials_due,
        "Attendance exceptions": summary.attendance_exceptions,
        "Probation reviews due": summary.probation_reviews_due,
        "Training sessions due": summary.training_sessions_due,
    }
    rows = [
        ["Metric", "Count"],
        *([label, str(total)] for label, total in counts.items() if total is not None),
    ]
    site = "Selected primary site" if summary.filters.project_id else "All primary sites"
    department = "Selected department" if summary.filters.department_id else "All departments"
    context = (
        f"{site} / {department} | Current records as of {summary.as_of} ({summary.timezone})\n"
        f"Attendance: {summary.attendance_window.date_from} "
        f"to {summary.attendance_window.date_to}\n"
        f"Due dates: {summary.due_window.date_from} to {summary.due_window.date_to}"
    )
    if output_format == "xlsx":
        return build_xlsx("HR summary", rows, context=context)
    if output_format == "csv":
        output = StringIO(newline="")
        csv = writer(output)
        csv.writerows(rows)
        csv.writerows([[], *([line] for line in context.splitlines())])
        return output.getvalue().encode("utf-8")
    output_pdf = BytesIO()
    styles = getSampleStyleSheet()
    document = SimpleDocTemplate(output_pdf, pagesize=A4, title="HR summary")
    document.build(
        [
            Paragraph("HR summary", styles["Title"]),
            *(Paragraph(escape(line), styles["BodyText"]) for line in context.splitlines()),
            Spacer(1, 12),
            Table(rows, repeatRows=1),
        ]
    )
    return output_pdf.getvalue()
