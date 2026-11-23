# HR table constraints

[Schema index](README.md) · [SQLAlchemy models](../../backend/app/models/hr.py) · [Alembic revisions](../../backend/alembic/versions/)

The baseline constraints in this reference were verified against the
production PostgreSQL catalogue at revision `202605310013` on 2026-11-15.
Later schema notes describe the checked-in migrations. For deployed schema
state, use the host release receipt and read back the Alembic head. Revision
[`202605310014`](../../backend/alembic/versions/202605310014_hr_recruitment_followups.py)
(`hr_requisitions.rejection_reason` and `hr_offers` validity/versioning
constraints). Revision `202605310013` adds an empty
`hr_project_assignment_requests` table; it does not backfill membership or
employee data. See the linked models and migrations for all column definitions
and the [HR workspace guide](../HR_WORKFORCE.md) for the permission and
feature-policy boundaries.

Pending revisions [015](../../backend/alembic/versions/202605310015_hr_leave_policy_review.py)
and [016](../../backend/alembic/versions/202605310016_validate_hr_leave_policy.py)
add and validate leave policy review and effective-window constraints. Rows
already present receive the `legacy` status and keep their approval and
entitlement fields. New draft, approved and rejected policies require an
ordered inclusive effective window. The nullable creator reference uses
`SET NULL`, and an orphaned proposal cannot be approved.
A new insert defaults to `draft`, so the old undated write path fails the
effective-window constraint. Coordinate database and application activation
within the production maintenance window.

[Revision 017](../../backend/alembic/versions/202605310017_hr_leave_accrual.py)
adds `hr_leave_accruals`. A receipt references an employee, leave type, dated
policy and a unique ledger entry. The employee/leave type/period start is
unique, and the date window is checked. The receipt and ledger credit commit
together. Existing ledger rows retain their original amounts.

[Revisions 045](../../backend/alembic/versions/202605310045_hr_leave_accrual_proration.py)
and [046](../../backend/alembic/versions/202605310046_validate_hr_leave_proration.py)
add opt-in proration to reviewed policies and optional eligible date bounds
to accrual receipts. Both bounds are present for a prorated credit and must
fall inside its requested period. Older and full-period receipts keep null
bounds.

[Revision 018](../../backend/alembic/versions/202605310018_hr_leave_rollover.py)
adds an explicit, default-off expiry flag to leave policies and a rollover
receipt keyed by employee, leave type and source year. Receipts link
source and target transfer entries plus any expiry entry. Ledger writes
and receipt creation share one employee lock and transaction.

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
| `hr_employment_periods` (local revision 029) | `employee_id` → `hr_employees.id` (required, RESTRICT)<br>`separation_case_id` → `hr_offboarding_cases.id`, `rehire_change_id` → `hr_employment_changes.id`, `onboarding_case_id` → `hr_onboarding_cases.id` (each nullable, unique, RESTRICT) | Employee, start date and ID. Partial unique index for one open period per employee | An open period requires a start date. A closed period requires a separation case and end date. A legacy start can remain unknown. |
| `hr_employment_changes` (local revision 022) | `employee_id` → `hr_employees.id` (required, RESTRICT)<br>`proposed_by`, `decided_by`, `applied_by` → `users.id` (RESTRICT) | Employee/created index; independent-review and applied-revision checks. | No |
| `hr_access_requests` | `admin_actioned_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`hr_approved_by_id` → `users.id` (nullable, SET NULL)<br>`linked_user_id` → `users.id` (nullable, SET NULL)<br>`requested_by_id` → `users.id` (nullable, SET NULL) | `ix_hr_access_requests_employee_id`<br>`ix_hr_access_requests_status` | No |

## Recruitment & onboarding

| Table | Foreign keys | Additional keys and indexes | Soft-delete column |
| --- | --- | --- | --- |
| `hr_requisitions` | `approved_by_id` → `users.id` (nullable, SET NULL)<br>`department_id` → `hr_departments.id` (nullable, SET NULL)<br>`position_id` → `hr_positions.id` (nullable, SET NULL)<br>`project_id` → `projects.id` (nullable, SET NULL)<br>`requested_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_requisitions_requisition_code`<br>`ix_hr_requisitions_status` | Yes |
| `hr_candidates` | `created_by_id` → `users.id` (nullable, SET NULL)<br>`resume_document_id` → `hr_documents.id` (nullable, SET NULL) | `uq_hr_candidates_candidate_code`<br>`ix_hr_candidates_email`<br>`ix_hr_candidates_full_name` | Yes |
| `hr_applications` | `assigned_recruiter_id` → `users.id` (nullable, SET NULL)<br>`candidate_id` → `hr_candidates.id` (required, CASCADE)<br>`requisition_id` → `hr_requisitions.id` (required, CASCADE) | `uq_hr_application_req_cand`<br>`ix_hr_applications_stage` | No |
| `hr_interviews` | `application_id` → `hr_applications.id` (required, CASCADE)<br>`interviewer_user_id` → `users.id` (nullable, SET NULL) | — | No |
| `hr_offers` | `document_version_id` → `hr_document_versions.id` (nullable, RESTRICT)<br>`application_id` → `hr_applications.id` (required, CASCADE)<br>`approved_by_id` → `users.id` (nullable, SET NULL)<br>`converted_employee_id` → `hr_employees.id` (nullable, SET NULL)<br>`proposed_department_id` → `hr_departments.id` (nullable, SET NULL)<br>`proposed_position_id` → `hr_positions.id` (nullable, SET NULL)<br>`superseded_by_id` → `hr_offers.id` (nullable, SET NULL)<br>`supersedes_offer_id` → `hr_offers.id` (nullable, SET NULL) | `uq_hr_offers_offer_code`<br>`ix_hr_offers_status`<br>`ck_hr_offers_version_positive` (`version_number >= 1`) | No |
| `hr_onboarding_cases` | `employee_id` → `hr_employees.id` (required, CASCADE)<br>`offer_id` → `hr_offers.id` (nullable, SET NULL)<br>`owner_user_id` → `users.id` (nullable, SET NULL) | `ix_hr_onboarding_cases_employee_id` | No |
| `hr_onboarding_tasks` | `assigned_user_id` → `users.id` (nullable, SET NULL)<br>`completed_by_id` → `users.id` (nullable, SET NULL)<br>`onboarding_case_id` → `hr_onboarding_cases.id` (required, CASCADE) | — | No |

## HR documents vault & compliance

| Table | Foreign keys | Additional keys and indexes | Soft-delete column |
| --- | --- | --- | --- |
| `hr_documents` | `candidate_id` → `hr_candidates.id` (nullable, CASCADE)<br>`created_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (nullable, CASCADE) | `ix_hr_documents_employee_id`<br>`ix_hr_documents_expiry_date` | Yes |
| `hr_document_versions` | `document_id` → `hr_documents.id` (required, CASCADE)<br>`uploaded_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_doc_version` | No |

Pending [revision 038](../../backend/alembic/versions/202605310038_hr_application_withdrawal.py)
adds nullable withdrawal date, reason, retention decision, policy reference,
and review date to `hr_applications`. Existing applications retain their
current stage. Previously withdrawn applications have no retroactively
inferred decision. Related application, interview, and offer mutations
serialize on the application row. The downgrade rejects recorded withdrawals.

Pending [revision 039](../../backend/alembic/versions/202605310039_hr_candidate_correspondence.py)
adds `hr_candidate_correspondence`, linked to its application, template,
preparer and optional reviewer by restrictive foreign keys. Its decision
constraint requires a reviewer distinct from the preparer and retains the
time and encrypted reason for a rejected draft. The rendered subject and
body are stored as encrypted text. The application/date index supports
history queries. The downgrade rejects a populated correspondence ledger.

Pending [revision 040](../../backend/alembic/versions/202605310040_index_hr_application_activity.py)
adds a concurrent partial index on retained application events in
`activity_log`. It indexes entity ID, event timestamp and event ID in
history order. Application stages reuse the existing text column.
The migration writes no new stage values and leaves historical events intact.

## Time, attendance & leave

Pending [revision 037](../../backend/alembic/versions/202605310037_hr_roster_allocations.py)
adds `hr_roster_allocations`. The employee, project, and calendar are required
foreign keys, and an optional shift references the schedule override. Those
references use `ON DELETE RESTRICT`. Creator and cancellation actors use
`ON DELETE SET NULL`. The cancellation reason and time are stored together.
Range reads use the work-date index and allocation mutations serialize on the
employee row before checking active overlaps with the employee/start index.
The migration creates an empty table and the downgrade rejects retained rows.

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
| `hr_leave_policies` | `approved_by_id` and `created_by_id` → `users.id` (nullable, SET NULL)<br>`leave_type_id` → `hr_leave_types.id` (required, CASCADE) | `uq_hr_leave_policies_code` | No |
| `hr_leave_ledger` | `actor_user_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`leave_type_id` → `hr_leave_types.id` (required, RESTRICT)<br>`reference_request_id` → `hr_leave_requests.id` (nullable, SET NULL) | `ix_hr_leave_ledger_employee_id` | No |
| `hr_leave_requests` | `attachment_document_id` → `hr_documents.id` (nullable, SET NULL)<br>`decided_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`leave_type_id` → `hr_leave_types.id` (required, RESTRICT)<br>`manager_recommended_by_id` → `users.id` (nullable, SET NULL)<br>`requested_by_id` → `users.id` (nullable, SET NULL) | `ix_hr_leave_requests_employee_id`<br>`ix_hr_leave_requests_status` | No |

Revision `202605310047` adds nullable `scheduled_work_dates` (`date[]`) to
`hr_leave_requests`. New submissions retain the resolved work dates. Approval
verifies the dates, and payroll splits the approved leave on those dates.
Existing approvals keep a null snapshot. The downgrade refuses to discard
recorded dates.

## Policies, letters, requests & offboarding

| Table | Foreign keys | Additional keys and indexes | Soft-delete column |
| --- | --- | --- | --- |
| `hr_policy_documents` | `document_id` → `hr_documents.id` (nullable, SET NULL)<br>`published_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_policy_documents_code` | No |
| `hr_policy_acknowledgements` | `acknowledged_by_user_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`policy_id` → `hr_policy_documents.id` (required, CASCADE) | `uq_hr_policy_ack_emp` | No |

[Revision 041](../../backend/alembic/versions/202605310041_hr_policy_edition_binding.py)
adds nullable document-version and preceding-edition references.
The composite foreign key binds the document and version number to one vault
record. [Revision 042](../../backend/alembic/versions/202605310042_validate_hr_policy_edition.py)
validates both foreign keys and the version check. Existing links and
receipts keep their original values. HR reviews previously unpinned
file references before publishing a replacement.
| `hr_letter_templates` | — | `uq_hr_letter_templates_code` | No |
| `hr_issued_letters` (local revisions 019, 059–060) | `employee_id` → `hr_employees.id` (required, RESTRICT)<br>`template_id` → `hr_letter_templates.id` (required, RESTRICT)<br>`prepared_by` → `users.id` (required, RESTRICT)<br>`decided_by` → `users.id` (nullable until decision, RESTRICT)<br>`compensation_term_id` → `hr_compensation_terms.id` (salary confirmations only, RESTRICT) | `ix_hr_issued_letters_employee_created`<br>Check requires distinct reviewer and decision timestamp for terminal states. | No |
| `hr_hr_requests` | `assigned_to_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`generated_document_id` → `hr_documents.id` (nullable, SET NULL)<br>`generated_letter_id` → `hr_issued_letters.id` (nullable, RESTRICT, local revisions 020/021)<br>`resolved_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_hr_requests_request_code`<br>`ix_hr_hr_requests_status` | No |
| `hr_offboarding_cases` | `completed_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`initiated_by_id` → `users.id` (nullable, SET NULL) | `ix_hr_offboarding_cases_employee_id` | No |
| `hr_clearance_steps` | `assigned_user_id` → `users.id` (nullable, SET NULL)<br>`cleared_by_id` → `users.id` (nullable, SET NULL)<br>`offboarding_case_id` → `hr_offboarding_cases.id` (required, CASCADE) | — | No |
| `hr_offboarding_custody` (local revisions 028, 030 and 031) | `case_id` → `hr_offboarding_cases.id` (required, RESTRICT)<br>`movement_id` → `inventory_movements.id` (nullable, unique, RESTRICT)<br>`recorded_by_id` → `users.id` (required, RESTRICT) | `ix_hr_offboarding_custody_case_recorded` on case, timestamp and ID | Unique case and opaque evidence reference. Store return events require a movement. IT device events require a device reference. IT sign-off is case-wide and omits the device reference. |
| `hr_separation_settlements` (local revision 032) | `case_id` → `hr_offboarding_cases.id` (required, RESTRICT)<br>`proposed_by_id` and `reviewed_by_id` → `users.id` (RESTRICT) | Case, timestamp and ID. Partial unique index for one proposed outcome per case | Unique case and opaque evidence reference. A final review requires a separate actor, timestamp and reference. |

## P2 governance & policy-gated modules

| Table | Foreign keys | Additional keys and indexes | Soft-delete column |
| --- | --- | --- | --- |
| `hr_goals` | `employee_id` → `hr_employees.id` (required, CASCADE) | — | No |
| `hr_review_cycles` | — | `uq_hr_review_cycles_code` | No |
| `hr_reviews` | `cycle_id` → `hr_review_cycles.id` (required, CASCADE)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`reviewer_employee_id` → `hr_employees.id` (nullable, SET NULL) | — | No |
| `hr_performance_events` (local revision 035) | `review_id` and `actor_id` (required, RESTRICT) | Unique review and revision | Retained actions, narrative notes, optional rating labels and former/replacement reviewer IDs (revision 036). Corrections append an event. |
| `hr_training_courses` | — | `uq_hr_training_courses_code` | No |
| `hr_training_enrollments` | `course_id` → `hr_training_courses.id` (required, CASCADE)<br>`employee_id` → `hr_employees.id` (required, CASCADE) | — | No |
| `hr_certifications` | `document_id` → `hr_documents.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE) | `ix_hr_certifications_expiry_date` | No |
| `hr_training_completions` (local revision 033) | `enrollment_id` → `hr_training_enrollments.id`, `certificate_id` → `hr_certifications.id`, `document_version_id` → `hr_document_versions.id`, `verified_by_id` → `users.id` (all required, RESTRICT) | Primary key on enrollment | Certificate and document version are independently unique. |
| `hr_training_requirements` (local revision 034) | Course (required), HR position and project site (at least one required), all RESTRICT | Unique tuple across course, position and project. Null scopes compare equal | A combined rule matches both assignments. Deactivation retains the rule record. |
| `hr_benefit_types` | `proposed_by_id` and `approved_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_benefit_types_code` | No |
| `hr_employee_benefits` | `benefit_type_id` → `hr_benefit_types.id` (required, CASCADE)<br>`employee_id` → `hr_employees.id` (required, CASCADE) | — | No |
| `hr_reimbursement_claims` | `decided_by_id` and `submitted_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE)<br>`receipt_document_id` → `hr_documents.id` (nullable, SET NULL)<br>`receipt_version_id` → `hr_document_versions.id` (nullable, RESTRICT)<br>`benefit_assignment_id` → `hr_employee_benefits.id` (nullable, RESTRICT) | `uq_hr_reimbursement_claims_claim_code` | No |
| `hr_compensation_terms` | `approved_by_id` and `proposed_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (required, CASCADE) | Revisions 050–051 add and validate approval status. | No |
| `hr_payroll_policies` | `approved_by_id` → `users.id` (nullable, SET NULL)<br>`second_approved_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_payroll_policies_code` | No |
| `hr_payroll_periods` | — | `uq_hr_payroll_periods_period_code` | No |
| `hr_payroll_runs` | `approved_by_id` → `users.id` (nullable, SET NULL)<br>`payroll_period_id` → `hr_payroll_periods.id` (required, CASCADE)<br>`policy_id` → `hr_payroll_policies.id` (nullable, SET NULL)<br>`prepared_by_id` → `users.id` (nullable, SET NULL) | Local revision 023 adds nullable `snapshot_encrypted`. | No |
| `hr_payroll_lines` | `employee_id` → `hr_employees.id` (required, CASCADE)<br>`payroll_run_id` → `hr_payroll_runs.id` (required, CASCADE) | Local revision 025 adds `ix_hr_payroll_lines_run_employee`. | No |
| `hr_payslip_publications` (local revision 024) | `run_id` → `hr_payroll_runs.id` (required, RESTRICT)<br>`published_by_id` → `users.id` (required, RESTRICT) | One receipt per run. Contains the approved snapshot digest and publication timestamp. | No |
| `hr_payroll_exports` (local revision 026) | `run_id` → `hr_payroll_runs.id` (required, RESTRICT)<br>`exported_by_id` → `users.id` (required, RESTRICT) | One receipt per run. Stores snapshot digest, exact file SHA-256, format version, actor and export timestamp. | No |
| `hr_payroll_settlement_events` (local revision 027) | `run_id` → `hr_payroll_exports.run_id`<br>`payment_reference` → `hr_payroll_lines.id`<br>`reverses_event_id` → the original event<br>`recorded_by_id` → `users.id` (all RESTRICT) | Unique event UUID and keyed evidence digest. Encrypted amount and evidence. Index on run and recorded timestamp. | No |
| `hr_cases` | `closed_by_id` → `users.id` (nullable, SET NULL)<br>`employee_id` → `hr_employees.id` (nullable, SET NULL)<br>`opened_by_id` → `users.id` (nullable, SET NULL) | `uq_hr_cases_case_code` | No |

Revisions `202605310048` and `202605310049` add and validate reimbursement
evidence references. The nullable fields preserve legacy claims. New claims
record the submitter and protect the exact private receipt version. External
settlement confirmation adds a reference and retains the approval actor and
timestamp.

Compensation reviews retain the proposer, approval status and encrypted
rejection reason. Existing terms keep their original approval metadata
and encrypted payload. Payroll still requires valid existing approval
metadata before selecting those terms.

Revisions `202605310052` and `202605310053` add a nullable ceiling and
currency, independent approval metadata on the benefit type, and a
coverage reference on reimbursement claims. Existing rows keep their
history. A new claim uses an explicitly approved ceiling and a dated
assignment for its employee.

Revision `202605310054` adds the opt-in `allows_advances` flag to benefit
types and adds `hr_employee_advances` and `hr_advance_recoveries`. An
advance protects its employee, coverage assignment, submitter and reviewer
references. Recovery rows protect the advance and recorder references and
are unique by advance and external reference. The downgrade refuses to
discard any retained advance or enabled policy.

Revision `202605310055` adds `hr_payroll_adjustments` as an empty table.
Each row links the draft run and employee to its submitter and optional
decision actor. The adjustment kind, decimal amount and opaque evidence
reference are encrypted together. The payroll snapshot copies approved
inputs into its encrypted payload. Existing snapshots remain readable
without the new adjustment field. Keep the additive table during an
application rollback so that review decisions are retained.

Revision `202605310056` adds `hr_payroll_closures`, keyed by the approved
run ID. Closure adds an actor, timestamp, snapshot digest, CSV checksum
and settlement digest. The associated period remains locked. Keep closure
receipts when rolling back application code; a compatible rollback must
continue blocking new settlement events against closed runs.

Revision `202605310057` adds `hr_payroll_corrections`. Each correction
references an immutable closed payroll line, the original snapshot
digest and the preceding approved correction when present. Proposed and
baseline amounts and the evidence reference are encrypted. A separate
actor records the terminal review decision. The base payroll run, payout
CSV, settlement history and payslip continue to reference the original
approved snapshot. Preserve the correction table during rollback.

Revision `202605310058` adds `hr_leave_date_evidence` for separately
reviewed historical dates. A proposal binds the request revision and
existing ledger debit. Its exact dates and evidence reference are
encrypted. Approval writes the reviewed dates to the existing leave
request and advances its revision. It preserves the original leave
approval and debit. The migration performs no historical backfill.

Revisions `202605310059` and `202605310060` add and validate the nullable
salary-confirmation source foreign key. New salary drafts bind an independently
approved compensation term from the same employee. The service verifies that
the term is still current before issuing the exact encrypted letter. Existing
ordinary letter rows and their encrypted content remain intact.

Revision `202605310061` adds the nullable `hr_payroll_policies.controlled_record`
JSONB field. It contains the opaque document reference, version,
effective-from date, external approval reference and synthetic worked
calculation examples. New payroll snapshots copy the selected record
into the existing encrypted snapshot. Existing policy rows need no backfill.
