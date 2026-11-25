from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.models.hr import HrEmployee, HrEmploymentPeriod


def historical_site_employment(
    work_date: date | ColumnElement[date],
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    periods = select(HrEmploymentPeriod.id).where(HrEmploymentPeriod.employee_id == HrEmployee.id)
    through_day = or_(
        HrEmploymentPeriod.ended_on.is_(None), HrEmploymentPeriod.ended_on >= work_date
    )
    matching_periods = periods.where(
        HrEmploymentPeriod.started_on <= work_date, through_day
    )
    employment_count = (
        select(func.count(HrEmploymentPeriod.id))
        .where(
            HrEmploymentPeriod.employee_id == HrEmployee.id,
            HrEmploymentPeriod.started_on <= work_date,
            through_day,
        )
        .correlate(HrEmployee)
        .scalar_subquery()
    )
    employment = matching_periods.exists() & (employment_count == 1)
    overlapping = employment_count > 1
    ambiguous = periods.where(HrEmploymentPeriod.started_on.is_(None), through_day).exists()
    legacy = ~periods.exists()
    legacy_end = or_(
        HrEmployee.termination_date.is_(None), HrEmployee.termination_date >= work_date
    )
    eligible = employment | (legacy & (HrEmployee.join_date <= work_date) & legacy_end)
    unresolved = overlapping | (
        ~eligible.is_(True)
        & (ambiguous | (legacy & HrEmployee.join_date.is_(None) & legacy_end))
    )
    return eligible, unresolved
