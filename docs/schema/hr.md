# HR table constraints

[Schema index](README.md) · [SQLAlchemy models](../../backend/app/models/hr.py) · [Alembic revisions](../../backend/alembic/versions/)

This reference records the HR keys and relationships verified against the
production PostgreSQL catalogue at revision `202605310013` on 2026-11-15, plus
pending revision
[`202605310014`](../../backend/alembic/versions/202605310014_hr_recruitment_followups.py)
(`hr_requisitions.rejection_reason` and `hr_offers` validity/versioning
constraints). Revision `202605310013` adds an empty
`hr_project_assignment_requests` table; it does not backfill membership or
employee data. See the linked models and migrations for all column definitions
and the [HR workspace guide](../HR_WORKFORCE.md) for the permission and
feature-policy boundaries.

- Every table below has a UUID primary key named `id`. Requiredness of a foreign
  key is shown where present. The delete rule comes from PostgreSQL.
- Calendar `revision` and HR `record_revision` counters default to 1. Services compare the
  expected revision under a lock for edits and decisions that require it.
  Service request transitions use the row's `updated_at` instead. That
  timestamp defaults to `now()`; SQLAlchemy supplies its updates.
- Employee and candidate records support soft deletion where the model has
  `deleted_at`. Employment history and document versions have their own rows.
  Tables with a soft-delete column are listed below.
- Treat employee, candidate, document and payroll data as restricted.
  Designated HR private values and restricted case details are encrypted by
  the application. Document object keys are storage references. Authorized
  download requests obtain short-lived links.

## Core organization & employee master

Revision `202605310013` adds `hr_project_assignment_requests`. Its required
`employee_id` and `project_id` references use `ON DELETE RESTRICT`. Its
`linked_user_id`, `requested_by_id`, and `decided_by_id` references are nullable
and use `ON DELETE SET NULL`. It has indexes on employee and project, a partial
unique index on `(project_id, employee_id)` for pending rows, and checks for
assign/revoke actions and pending/approved/rejected statuses. It has no
soft-delete column.

| Table | Foreign keys | Additional keys and indexes | Soft-delete column |
| --- | --- | --- | --- |
| `hr_project_assignment_requests` | `employee_id` → `hr_employees.id` (required, RESTRICT)<br>`project_id` → `projects.id` (required, RESTRICT)<br>`linked_user_id` → `users.id` (nullable, SET NULL)<br>`requested_by_id` → `users.id` (nullable, SET NULL)<br>`decided_by_id` → `users.id` (nullable, SET NULL) | `ix_hr_project_assignment_requests_employee_id`<br>`ix_hr_project_assignment_requests_project_id`<br>`uq_hr_project_assignment_pending` (`project_id, employee_id` where `status = 'pending'`)<br>Checks for assign/revoke action and pending/approved/rejected status | No |
| `hr_departments` | `head_employee_id` → `hr_employees.id` (nullable, SET NULL)<br>`parent_department_id` → `hr_departments.id` (nullable, SET NULL)<br>`project_id` → `projects.id` (nullable, SET NULL) | `uq_hr_departments_code` | Yes |
| `hr_positions` | `department_id` → `hr_departments.id` (nullable, SET NULL) | `uq_hr_positions_code` | Yes |
| `hr_employees` | `line_manager_reviewer_id` → `hr_employees.id` (nullable, SET NULL)<br>`created_by_id` → `users.id` (nullable, SET NULL)<br>`department_id` → `hr_departments.id` (nullable, SET NULL)<br>`manager_employee_id` → `hr_employees.id` (nullable, SET NULL)<br>`position_id` → `hr_positions.id` (nullable, SET NULL)<br>`primary_project_id` → `projects.id` (nullable, SET NULL)<br>`updated_by_id` → `users.id` (nullable, SET NULL)<br>`user_id` → `users.id` (nullable, SET NULL)<br>`work_calendar_id` → `hr_work_calendars.id` (nullable, SET NULL) | `uq_hr_employees_employee_code`<br>`uq_hr_employees_user_id`<br>`uq_hr_employees_work_email`<br>`ix_hr_employees_employment_status`<br>`ix_hr_employees_full_name` | Yes |
| `hr_employee_private` | `employee_id` → `hr_employees.id` (required, CASCADE)<br>`updated_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_employee_private_employee_id` | No |
| `hr_employment_history` | `actor_user_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE) | `ix_hr_employment_history_employee_id` | No |
| `hr_access_requests` | `admin_actioned_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`hr_approved_by_id` → `users.id` (nullable, SET NULL)<br>`linked_user_id` → `users.id` (nullable, SET NULL)<br>`requested_by_id` → `users.id` (nullable, SET NULL) | `ix_hr_access_requests_employee_id`<br>`ix_hr_access_requests_status` | No |

## Recruitment & onboarding

| Table | Foreign keys | Additional keys and indexes | Soft-delete column |
| --- | --- | --- | --- |
| `hr_requisitions` | `approved_by_id` → `users.id` (nullable, SET NULL)<br>`department_id` → `hr_departments.id` (nullable, SET NULL)<br>`position_id` → `hr_positions.id` (nullable, SET NULL)<br>`project_id` → `projects.id` (nullable, SET NULL)<br>`requested_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_requisitions_requisition_code`<br>`ix_hr_requisitions_status` | Yes |
| `hr_candidates` | `created_by_id` → `users.id` (nullable, SET NULL)<br>`resume_document_id` → `hr_documents.id` (nullable, SET NULL) | `uq_hr_candidates_candidate_code`<br>`ix_hr_candidates_email`<br>`ix_hr_candidates_full_name` | Yes |
| `hr_applications` | `assigned_recruiter_id` → `users.id` (nullable, SET NULL)<br>`candidate_id` → `hr_candidates.id` (required, CASCADE)<br>`requisition_id` → `hr_requisitions.id` (required, CASCADE) | `uq_hr_application_req_cand`<br>`ix_hr_applications_stage` | No |
| `hr_interviews` | `application_id` → `hr_applications.id` (required, CASCADE)<br>`interviewer_user_id` → `users.id` (nullable, SET NULL) | — | No |
| `hr_offers` | `application_id` → `hr_applications.id` (required, CASCADE)<br>`approved_by_id` → `users.id` (nullable, SET NULL)<br>`converted_employee_id` → `hr_employees.id` (nullable, SET NULL)<br>`proposed_department_id` → `hr_departments.id` (nullable, SET NULL)<br>`proposed_position_id` → `hr_positions.id` (nullable, SET NULL)<br>`superseded_by_id` → `hr_offers.id` (nullable, SET NULL)<br>`supersedes_offer_id` → `hr_offers.id` (nullable, SET NULL) | `uq_hr_offers_offer_code`<br>`ix_hr_offers_status`<br>`ck_hr_offers_version_positive` (`version_number >= 1`) | No |
| `hr_onboarding_cases` | `employee_id` → `hr_employees.id` (required, CASCADE)<br>`offer_id` → `hr_offers.id` (nullable, SET NULL)<br>`owner_user_id` → `users.id` (nullable, SET NULL) | `ix_hr_onboarding_cases_employee_id` | No |
| `hr_onboarding_tasks` | `assigned_user_id` → `users.id` (nullable, SET NULL)<br>`completed_by_id` → `users.id` (nullable, SET NULL)<br>`onboarding_case_id` → `hr_onboarding_cases.id` (required, CASCADE) | — | No |

## HR documents vault & compliance

| Table | Foreign keys | Additional keys and indexes | Soft-delete column |
| --- | --- | --- | --- |
| `hr_documents` | `candidate_id` → `hr_candidates.id` (nullable, CASCADE)<br>`created_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (nullable, CASCADE) | `ix_hr_documents_employee_id`<br>`ix_hr_documents_expiry_date` | Yes |
| `hr_document_versions` | `document_id` → `hr_documents.id` (required, CASCADE)<br>`uploaded_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_doc_version` | No |

## Time, attendance & leave

| Table | Foreign keys | Additional keys and indexes | Soft-delete column |
| --- | --- | --- | --- |
| `hr_work_calendars` | `project_id` → `projects.id` (nullable, SET NULL)<br>`approved_by_id` → `users.id` (nullable, SET NULL)<br>`created_by_id` → `users.id` (nullable, SET NULL)<br>`submitted_by_id` → `users.id` (nullable, SET NULL) | `ck_hr_work_calendars_hr_calendar_effective_window`<br>`ck_hr_work_calendars_hr_calendar_status`<br>`uq_hr_work_calendars_code` | Yes |
| `hr_holidays` | `calendar_id` → `hr_work_calendars.id` (required, CASCADE) | `uq_hr_holiday_cal_date` | No |
| `hr_shift_assignments` | `assigned_by_id` → `users.id` (nullable, SET NULL)<br>`calendar_id` → `hr_work_calendars.id` (required, CASCADE)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`project_id` → `projects.id` (nullable, SET NULL) | — | No |
| `hr_attendance_entries` | `approved_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`project_id` → `projects.id` (nullable, SET NULL)<br>`recorded_by_id` → `users.id` (nullable, SET NULL)<br>`manager_recommended_by_id` → `users.id` (nullable, SET NULL)<br>`calendar_id` → `hr_work_calendars.id` (nullable, RESTRICT)<br>`shift_assignment_id` → `hr_shift_assignments.id` (nullable, RESTRICT) | `uq_hr_attendance_emp_date`<br>`ix_hr_attendance_entries_work_date` | No |
| `hr_attendance_corrections` | `attendance_entry_id` → `hr_attendance_entries.id` (nullable, SET NULL)<br>`decided_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`requested_by_id` → `users.id` (nullable, SET NULL) | — | No |
| `hr_timesheets` | `approved_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`manager_recommended_by_id` → `users.id` (nullable, SET NULL)<br>`project_id` → `projects.id` (nullable, SET NULL)<br>`submitted_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_timesheet_emp_period` | No |
| `hr_overtime_requests` | `decided_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`manager_recommended_by_id` → `users.id` (nullable, SET NULL)<br>`project_id` → `projects.id` (nullable, SET NULL)<br>`requested_by_id` → `users.id` (nullable, SET NULL) | — | No |
| `hr_leave_types` | — | `uq_hr_leave_types_code` | No |
| `hr_leave_policies` | `approved_by_id` → `users.id` (nullable, SET NULL)<br>`leave_type_id` → `hr_leave_types.id` (required, CASCADE) | `uq_hr_leave_policies_code` | No |
| `hr_leave_ledger` | `actor_user_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`leave_type_id` → `hr_leave_types.id` (required, RESTRICT)<br>`reference_request_id` → `hr_leave_requests.id` (nullable, SET NULL) | `ix_hr_leave_ledger_employee_id` | No |
| `hr_leave_requests` | `attachment_document_id` → `hr_documents.id` (nullable, SET NULL)<br>`decided_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`leave_type_id` → `hr_leave_types.id` (required, RESTRICT)<br>`manager_recommended_by_id` → `users.id` (nullable, SET NULL)<br>`requested_by_id` → `users.id` (nullable, SET NULL) | `ix_hr_leave_requests_employee_id`<br>`ix_hr_leave_requests_status` | No |

## Policies, letters, requests & offboarding

| Table | Foreign keys | Additional keys and indexes | Soft-delete column |
| --- | --- | --- | --- |
| `hr_policy_documents` | `document_id` → `hr_documents.id` (nullable, SET NULL)<br>`published_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_policy_documents_code` | No |
| `hr_policy_acknowledgements` | `acknowledged_by_user_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`policy_id` → `hr_policy_documents.id` (required, CASCADE) | `uq_hr_policy_ack_emp` | No |
| `hr_letter_templates` | — | `uq_hr_letter_templates_code` | No |
| `hr_hr_requests` | `assigned_to_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`generated_document_id` → `hr_documents.id` (nullable, SET NULL)<br>`resolved_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_hr_requests_request_code`<br>`ix_hr_hr_requests_status` | No |
| `hr_offboarding_cases` | `completed_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`initiated_by_id` → `users.id` (nullable, SET NULL) | `ix_hr_offboarding_cases_employee_id` | No |
| `hr_clearance_steps` | `assigned_user_id` → `users.id` (nullable, SET NULL)<br>`cleared_by_id` → `users.id` (nullable, SET NULL)<br>`offboarding_case_id` → `hr_offboarding_cases.id` (required, CASCADE) | — | No |

## P2 governance & policy-gated modules

| Table | Foreign keys | Additional keys and indexes | Soft-delete column |
| --- | --- | --- | --- |
| `hr_goals` | `employee_id` → `hr_employees.id` (required, CASCADE) | — | No |
| `hr_review_cycles` | — | `uq_hr_review_cycles_code` | No |
| `hr_reviews` | `cycle_id` → `hr_review_cycles.id` (required, CASCADE)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`reviewer_employee_id` → `hr_employees.id` (nullable, SET NULL) | — | No |
| `hr_training_courses` | — | `uq_hr_training_courses_code` | No |
| `hr_training_enrollments` | `course_id` → `hr_training_courses.id` (required, CASCADE)<br>`employee_id` → `hr_employees.id` (required, CASCADE) | — | No |
| `hr_certifications` | `document_id` → `hr_documents.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE) | `ix_hr_certifications_expiry_date` | No |
| `hr_benefit_types` | — | `uq_hr_benefit_types_code` | No |
| `hr_employee_benefits` | `benefit_type_id` → `hr_benefit_types.id` (required, CASCADE)<br>`employee_id` → `hr_employees.id` (required, CASCADE) | — | No |
| `hr_reimbursement_claims` | `decided_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`receipt_document_id` → `hr_documents.id` (nullable, SET NULL) | `uq_hr_reimbursement_claims_claim_code` | No |
| `hr_compensation_terms` | `approved_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE) | — | No |
| `hr_payroll_policies` | `approved_by_id` → `users.id` (nullable, SET NULL)<br>`second_approved_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_payroll_policies_code` | No |
| `hr_payroll_periods` | — | `uq_hr_payroll_periods_period_code` | No |
| `hr_payroll_runs` | `approved_by_id` → `users.id` (nullable, SET NULL)<br>`payroll_period_id` → `hr_payroll_periods.id` (required, CASCADE)<br>`policy_id` → `hr_payroll_policies.id` (nullable, SET NULL)<br>`prepared_by_id` → `users.id` (nullable, SET NULL) | — | No |
| `hr_payroll_lines` | `employee_id` → `hr_employees.id` (required, CASCADE)<br>`payroll_run_id` → `hr_payroll_runs.id` (required, CASCADE) | — | No |
| `hr_cases` | `closed_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (nullable, SET NULL)<br>`opened_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_cases_case_code` | No |
