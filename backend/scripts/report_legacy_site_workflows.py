"""Report material requests and site attendance missing staged submission evidence."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import AsyncSessionLocal, engine

MATERIAL_REQUESTS = text("""
    SELECT r.id, r.project_id, r.status, r.revision, r.submission_revision,
           COALESCE(SUM(l.quantity), 0) AS requested_quantity,
           COALESCE(SUM(l.reserved_quantity), 0) AS reserved_quantity,
           COALESCE(SUM(l.issued_quantity), 0) AS issued_quantity,
           'engineer_and_gpm_submission_decisions' AS missing_evidence,
           CASE
               WHEN r.status IN ('issued', 'cancelled') THEN 'historical_only'
               WHEN COALESCE(SUM(l.reserved_quantity), 0) > 0
                   THEN 'requires_reservation_release'
               WHEN COALESCE(SUM(l.issued_quantity), 0) > 0 THEN 'manual_reconciliation'
               WHEN r.status IN ('approved', 'requested') THEN 'eligible_for_resubmission'
               ELSE 'manual_reconciliation'
           END AS disposition
    FROM material_requests r
    LEFT JOIN material_request_lines l ON l.request_id = r.id AND l.deleted_at IS NULL
    WHERE r.deleted_at IS NULL AND r.submission_revision IS NULL AND r.status <> 'draft'
    GROUP BY r.id
    ORDER BY r.id
""")

INCOMPLETE_MATERIAL_VALUATION = text("""
    SELECT r.id, r.project_id, r.status, r.revision, r.submission_revision,
           COALESCE(s.requirements->'approval_stages', '[]'::jsonb) AS approval_stages,
           COALESCE(SUM(l.reserved_quantity), 0) AS reserved_quantity,
           COALESCE(SUM(l.issued_quantity), 0) AS issued_quantity,
           CASE
             WHEN COALESCE(SUM(l.reserved_quantity), 0) > 0
               THEN 'requires_reservation_release'
             WHEN COALESCE(SUM(l.issued_quantity), 0) > 0
               THEN 'manual_reconciliation'
             ELSE 'valuation_review_required'
           END AS disposition
    FROM material_requests r
    LEFT JOIN material_request_submissions s
      ON s.request_id = r.id AND s.submission_revision = r.submission_revision
    LEFT JOIN material_request_lines l ON l.request_id = r.id AND l.deleted_at IS NULL
    WHERE r.deleted_at IS NULL AND r.status <> 'draft'
      AND (
        s.requirements->>'valuation_status' = 'incomplete'
        OR s.requirements->>'valuation_complete' = 'false'
        OR EXISTS (
          SELECT 1 FROM material_request_lines missing
          WHERE missing.request_id = r.id AND missing.deleted_at IS NULL
            AND missing.unit_cost IS NULL
        )
      )
    GROUP BY r.id, s.requirements
    ORDER BY r.id
""")

CURRENT_STOCK_ACTIVITY = text("""
    SELECT r.id, r.project_id, r.status, r.revision, r.submission_revision,
           SUM(l.reserved_quantity) AS reserved_quantity,
           SUM(l.issued_quantity) AS issued_quantity,
           CASE WHEN r.status = 'cancelled' AND SUM(l.reserved_quantity) > 0
                THEN 'requires_reservation_release'
                ELSE 'current_fulfillment' END AS disposition
    FROM material_requests r
    JOIN material_request_lines l ON l.request_id = r.id AND l.deleted_at IS NULL
    WHERE r.deleted_at IS NULL AND r.submission_revision IS NOT NULL
    GROUP BY r.id
    HAVING SUM(l.reserved_quantity) > 0 OR r.status = 'partially_issued'
    ORDER BY r.id
""")

SITE_ATTENDANCE = text("""
    SELECT a.id, a.employee_id, a.project_id, a.status, a.record_revision AS revision,
           a.work_date, a.worked_hours, a.site_submission_revision,
           'current_engineer_and_hr_decisions' AS missing_evidence,
           CASE WHEN a.status = 'historical' THEN 'historical_only'
                WHEN a.status = 'approved'
                 AND EXISTS (SELECT 1 FROM hr_payroll_periods p
                             WHERE a.work_date BETWEEN p.period_start AND p.period_end
                               AND p.status = 'closed')
                 AND NOT EXISTS (SELECT 1 FROM hr_payroll_periods p
                                 WHERE a.work_date BETWEEN p.period_start AND p.period_end
                                   AND p.status <> 'closed') THEN 'historical_only'
                ELSE 'manual_reconciliation' END AS disposition
    FROM hr_attendance_entries a
    WHERE a.project_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM hr_site_attendance_submissions s
        WHERE s.entry_id = a.id AND s.submission_revision = a.site_submission_revision
          AND s.engineer_decision = 'approved' AND s.hr_decision = 'approved'
    )
      AND (a.site_submission_revision IS NULL OR a.status IN ('approved', 'historical'))
    ORDER BY a.id
""")

HISTORICAL_ATTENDANCE_ELIGIBILITY = text("""
    WITH evidence AS (
      SELECT a.id, a.employee_id, a.project_id, a.work_date, a.status,
             a.record_revision AS revision, e.join_date, e.termination_date,
             (SELECT count(*) FROM hr_employment_periods ep
              WHERE ep.employee_id = a.employee_id) AS employment_period_count,
             (SELECT count(*) FROM hr_employment_periods ep
              WHERE ep.employee_id = a.employee_id
                AND ep.started_on <= a.work_date
                AND (ep.ended_on IS NULL OR ep.ended_on >= a.work_date))
                AS matching_employment_count,
             (SELECT count(*) FROM hr_roster_allocations ra
              WHERE ra.employee_id = a.employee_id AND ra.work_date = a.work_date
                AND ra.cancelled_at IS NULL) AS roster_count,
             COALESCE((SELECT bool_or(ra.project_id = a.project_id)
              FROM hr_roster_allocations ra
              WHERE ra.employee_id = a.employee_id AND ra.work_date = a.work_date
                AND ra.cancelled_at IS NULL), false) AS roster_matches_project,
             (SELECT count(*) FROM hr_shift_assignments sa
              WHERE sa.employee_id = a.employee_id AND sa.project_id IS NOT NULL
                AND sa.effective_from <= a.work_date
                AND (sa.effective_to IS NULL OR sa.effective_to >= a.work_date)) AS shift_count,
             COALESCE((SELECT bool_or(sa.project_id = a.project_id)
              FROM hr_shift_assignments sa
              WHERE sa.employee_id = a.employee_id AND sa.project_id IS NOT NULL
                AND sa.effective_from <= a.work_date
                AND (sa.effective_to IS NULL OR sa.effective_to >= a.work_date)), false)
                AS shift_matches_project,
             EXISTS (SELECT 1 FROM hr_payroll_periods p
                     WHERE a.work_date BETWEEN p.period_start AND p.period_end
                       AND p.status = 'closed') AS has_closed_period,
             EXISTS (SELECT 1 FROM hr_payroll_periods p
                     WHERE a.work_date BETWEEN p.period_start AND p.period_end
                       AND p.status <> 'closed') AS has_open_period
      FROM hr_attendance_entries a
      JOIN hr_employees e ON e.id = a.employee_id
      WHERE a.source = 'site' AND a.project_id IS NOT NULL
    ), classified AS (
      SELECT *,
        CASE
          WHEN employment_period_count > 0 AND matching_employment_count > 1
            THEN 'employment_period_overlap'
          WHEN employment_period_count > 0 AND matching_employment_count = 0
            THEN 'employment_period_unresolved'
          WHEN employment_period_count = 0 AND join_date IS NULL
            THEN 'legacy_employment_start_unresolved'
          WHEN employment_period_count = 0
            AND (join_date > work_date OR termination_date < work_date)
            THEN 'legacy_employment_date_conflict'
          ELSE NULL
        END AS employment_reason,
        CASE
          WHEN roster_count > 1 THEN 'daily_roster_overlap'
          WHEN roster_count = 1 AND NOT roster_matches_project
            THEN 'daily_roster_project_conflict'
          WHEN roster_count = 0 AND shift_count > 1 THEN 'project_shift_overlap'
          WHEN roster_count = 0 AND shift_count = 1 AND NOT shift_matches_project
            THEN 'project_shift_conflict'
          WHEN roster_count = 0 AND shift_count = 0
            THEN 'assignment_evidence_missing'
          ELSE NULL
        END AS assignment_reason
      FROM evidence
    )
    SELECT id, employee_id, project_id, work_date, status, revision,
           concat_ws(',', employment_reason, assignment_reason) AS reason_code,
           CASE WHEN status = 'approved' AND has_closed_period AND NOT has_open_period
                  THEN 'historical_only'
                WHEN has_closed_period AND NOT has_open_period
                  THEN 'locked_period_review'
                ELSE 'manual_reconciliation'
           END AS disposition
    FROM classified
    WHERE employment_reason IS NOT NULL OR assignment_reason IS NOT NULL
    ORDER BY work_date, id
""")

UNCLASSIFIED_EVIDENCE = text("""
    SELECT 'document' AS evidence_type, d.id AS evidence_id, d.project_id,
           NULL::varchar AS entity_type, NULL::uuid AS entity_id,
           d.created_at, 'manual_classification_review' AS disposition
    FROM documents d
    WHERE d.classification = 'unclassified'
    UNION ALL
    SELECT 'photo' AS evidence_type, p.id AS evidence_id,
           CASE p.entity_type
             WHEN 'daily_report' THEN
               (SELECT r.project_id FROM daily_reports r WHERE r.id = p.entity_id)
             WHEN 'supervisor_update' THEN
               (SELECT u.project_id FROM supervisor_updates u WHERE u.id = p.entity_id)
             WHEN 'inventory_registration' THEN
               (SELECT i.project_id FROM inventory_registrations i WHERE i.id = p.entity_id)
             WHEN 'material_request' THEN
               (SELECT m.project_id FROM material_requests m WHERE m.id = p.entity_id)
             ELSE NULL
           END AS project_id,
           p.entity_type, p.entity_id, p.created_at,
           'manual_classification_review' AS disposition
    FROM photos p
    WHERE p.classification = 'unclassified'
    ORDER BY evidence_type, evidence_id
""")


async def report() -> None:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            await session.execute(text("SET LOCAL statement_timeout = '30s'"))
            for category, query in (
                ("legacy_material_request", MATERIAL_REQUESTS),
                ("incomplete_material_valuation", INCOMPLETE_MATERIAL_VALUATION),
                ("current_material_stock_activity", CURRENT_STOCK_ACTIVITY),
                ("legacy_site_attendance", SITE_ATTENDANCE),
                ("historical_attendance_eligibility", HISTORICAL_ATTENDANCE_ELIGIBILITY),
                ("unclassified_evidence", UNCLASSIFIED_EVIDENCE),
            ):
                async for row in await session.stream(query):
                    print(json.dumps({"finding": category, **row._mapping}, default=str))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-understand", action="store_true")
    args = parser.parse_args()
    if get_settings().app_env.lower() == "production" and not args.i_understand:
        parser.error("Authorized production operators must pass --i-understand.")
    asyncio.run(report())


if __name__ == "__main__":
    main()
