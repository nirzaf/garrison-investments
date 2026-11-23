# Database schema

[Documentation index](../README.md) · [Architecture](../ARCHITECTURE.md) · [Operations and deployment](../OPERATIONS_AND_DEPLOYMENT.md)

This reference covers the core operational tables and HR & Workforce Management schema. The HR table-constraint reference uses a historical catalogue check at revision `202605310013` and describes subsequent source migrations. The current repository Alembic head is `202605310100`. The local HR migrations begin at [revision 007](../../backend/alembic/versions/202605310007_hr_workforce_management.py) and currently end at [revision 046](../../backend/alembic/versions/202605310046_validate_hr_leave_proration.py). Each core table page links to its [SQLAlchemy model](../../backend/app/models/) and lists PostgreSQL columns, server defaults, constraints and indexes from its described schema snapshot. Follow [Alembic migrations](../../backend/alembic/versions/) to trace schema changes.

A dash in the default column means the database has no server default. Application-side rules live in the linked model and service code. Many tables use `deleted_at` for soft deletion. Foreign-key delete actions describe physical row deletion.

## Feedback

| Table | Purpose |
| --- | --- |
| [`user_feedback`](user_feedback.md) | Business user reports, optional request summaries, and technical triage status. |

## Identity

| Table | Purpose |
| --- | --- |
| [`users`](users.md) | Portal accounts, roles, profile fields, password hashes, and sign-in lockout state. |
| [`auth_otp_challenges`](auth_otp_challenges.md) | Hashed one-time codes for login and password reset, with expiry, attempts, and consumption state. |
| [`auth_refresh_tokens`](auth_refresh_tokens.md) | Hashed refresh tokens with expiry and revocation timestamps. |
| [Support operators and sessions](support_identity.md) | Separate technical identity, passkey credentials, case evidence access, oversight disclosure audit, and attested backup receipts. |

## Projects and planning

| Table | Purpose |
| --- | --- |
| [`projects`](projects.md) | Project identity, contract and client details, schedule, budget, and progress. |
| [`project_members`](project_members.md) | Project membership and project-specific roles for portal users. |
| [`project_milestones`](project_milestones.md) | Project milestones by discipline, with planned and actual dates and progress. |
| [`project_tasks`](project_tasks.md) | Scheduled work with an optional milestone, predecessor task, and owner. |
| [`boq_items`](boq_items.md) | Project bill of quantities, including planned and approved quantities, units, and rates. |

## Site reporting

| Table | Purpose |
| --- | --- |
| [`daily_reports`](daily_reports.md) | Engineer-authored daily site reports, with workflow status, referenced updates, and approval metadata. |
| [`supervisor_updates`](supervisor_updates.md) | Supervisor site updates with attendance, overtime, progress, and verification metadata. |
| [`report_manpower`](report_manpower.md) | Trade-level manpower counts and overtime for a daily report. |
| [`report_equipment`](report_equipment.md) | Equipment quantities and usage hours recorded in a daily report. |
| [`report_material_consumption`](report_material_consumption.md) | Material usage recorded in a daily report, optionally linked to a bill of quantities item. |
| [`daily_report_approval_history`](daily_report_approval_history.md) | Daily report submission and decision history, including the actor and previous status. |
| [`report_exports`](report_exports.md) | Daily report export status, object-storage keys, and email delivery state. |

## Documents and media

| Table | Purpose |
| --- | --- |
| [`documents`](documents.md) | Document metadata, optional project association, expiry, and active version number. |
| [`document_versions`](document_versions.md) | Version-specific object-storage keys, file metadata, and approval status. |
| [`photos`](photos.md) | Original media and generated renditions for reports, updates, and other supported entities. |

## Inventory

| Table | Purpose |
| --- | --- |
| [`storage_locations`](storage_locations.md) | Storage locations with optional project association and active status. |
| [`inventory_items`](inventory_items.md) | Inventory catalog, units, thresholds, unit cost, and optional supplier. |
| [`inventory_location_stock`](inventory_location_stock.md) | On-hand and reserved balances for each item and storage location. |
| [`inventory_assets`](inventory_assets.md) | Individually tagged assets with location, condition, and status. |
| [`inventory_movements`](inventory_movements.md) | Stock and asset movement history, with references to the source operation where available. |
| [`material_requests`](material_requests.md) | Project material requests, including the source storage location and estimated cost. |
| [`material_request_lines`](material_request_lines.md) | Requested, reserved, and issued quantities for each material request line. |

## Finance and suppliers

| Table | Purpose |
| --- | --- |
| [`suppliers`](suppliers.md) | Supplier contact, commercial terms, and tax compliance information. |
| [`invoices`](invoices.md) | Supplier invoices linked to projects, with amounts, approval state, and payment status. |
| [`payments`](payments.md) | Recorded invoice payments with dates, methods, references, and actors. |

## Workflow and operations

| Table | Purpose |
| --- | --- |
| [`approvals`](approvals.md) | Approval inbox items with submitter, approver, delegation, escalation, and decision state. |
| [`notifications`](notifications.md) | User notifications with read, mute, and email delivery state. |
| [`import_batches`](import_batches.md) | Spreadsheet import status, row counts, validation errors, and results. |
| [`activity_log`](activity_log.md) | Audit and operational events with actor, request, context, retention metadata, and [immutability trigger](../../backend/alembic/versions/202605310094_activity_log_immutability.py). |
| [`business_log_streams`](activity_log.md#business-audit-streams) | Open and close timestamps for bounded business audit streams. |
| [`idempotency_records`](idempotency_records.md) | Request keys and resource references used to deduplicate retried writes. |
| [`task_outbox`](task_outbox.md) | Background work recorded in the same database transaction as the operation that schedules it. |

## HR and workforce management

See [HR table constraints](hr.md) for the primary keys, foreign keys, named
indexes and soft-delete columns. The initial schema is defined in
[`backend/app/models/hr.py`](../../backend/app/models/hr.py) and
[`202605310007_hr_workforce_management.py`](../../backend/alembic/versions/202605310007_hr_workforce_management.py).

| Domain | Tables |
| --- | --- |
| Core organization & employee master | `hr_departments`, `hr_positions`, `hr_employees`, `hr_employee_private` (Fernet-encrypted sensitive fields), `hr_employment_history` (employment change history), `hr_employment_periods` (separation and rehire periods), `hr_access_requests` (HR request, separate HR review and director fulfillment), `hr_project_assignment_requests` (pending requests only change membership after authorized approval) |
| Recruitment & onboarding | `hr_requisitions`, `hr_candidates`, `hr_applications`, `hr_interviews`, `hr_offers`, `hr_onboarding_cases`, `hr_onboarding_tasks` |
| HR documents vault & compliance | `hr_documents` (categories: ordinary, confidential, medical, identity, compensation, disciplinary), `hr_document_versions` |
| Time, attendance & leave | `hr_work_calendars`, `hr_holidays`, `hr_shift_assignments`, `hr_attendance_entries`, `hr_attendance_corrections`, `hr_timesheets`, `hr_overtime_requests`, `hr_leave_types`, `hr_leave_policies`, `hr_leave_ledger`, `hr_leave_requests` |
| Policies, letters, requests & offboarding | `hr_policy_documents`, `hr_policy_acknowledgements`, `hr_letter_templates`, `hr_issued_letters`, `hr_hr_requests`, `hr_offboarding_cases`, `hr_clearance_steps`, `hr_offboarding_custody`, `hr_separation_settlements` |
| P2 governance & policy-gated modules | `hr_goals`, `hr_review_cycles`, `hr_reviews`, `hr_performance_events`, `hr_training_courses`, `hr_training_enrollments`, `hr_certifications`, `hr_training_completions`, `hr_training_requirements`, `hr_benefit_types`, `hr_employee_benefits`, `hr_reimbursement_claims`, `hr_compensation_terms`, `hr_payroll_policies` (dual-approval gate), `hr_payroll_periods`, `hr_payroll_runs`, `hr_payroll_lines`, `hr_payslip_publications`, `hr_payroll_exports`, `hr_payroll_settlement_events`, `hr_cases` (encrypted restricted case details) |

[202605310008](../../backend/alembic/versions/202605310008_hr_calendar_publication.py)
adds dates, timezone, review state and revision to work calendars.
[202605310009](../../backend/alembic/versions/202605310009_hr_attendance_schedule.py)
records the immutable calendar and shift associations used by new attendance entries.
[202605310010](../../backend/alembic/versions/202605310010_hr_line_manager_review.py)
adds direct-manager authorizations and records recommendations and revisions on
leave, timesheet and overtime requests.
[202605310011](../../backend/alembic/versions/202605310011_retire_hr_executive.py)
checks that no active account holds the retired HR Executive role.
[202605310012](../../backend/alembic/versions/202605310012_hr_attendance_review.py)
adds approval state, independent review and revision tracking to attendance entries
and records the base revision on correction requests.
[202605310013](../../backend/alembic/versions/202605310013_hr_project_assignment.py)
adds the project assignment request and decision table. Existing memberships
are preserved. Membership changes use the existing project service only after
an authorized reviewer approves a request.
[202605310014](../../backend/alembic/versions/202605310014_hr_recruitment_followups.py)
adds `hr_requisitions.rejection_reason` plus offer validity, versioning, and
supersession columns (`valid_until`, `version_number`, `supersedes_offer_id`,
`superseded_by_id`, `superseded_at`), self-referential foreign keys, and
`ck_hr_offers_version_positive` on `hr_offers`.
[202605310015](../../backend/alembic/versions/202605310015_hr_leave_policy_review.py)
adds dated leave policies and review state while preserving legacy approvals.
[202605310016](../../backend/alembic/versions/202605310016_validate_hr_leave_policy.py)
validates the new creator foreign key, status and date-window constraints.
[202605310017](../../backend/alembic/versions/202605310017_hr_leave_accrual.py)
adds one-to-one policy accrual receipts for leave ledger entries.
[202605310018](../../backend/alembic/versions/202605310018_hr_leave_rollover.py)
adds reviewed year-end rollover receipts and explicit authority for expiry.
[202605310019](../../backend/alembic/versions/202605310019_hr_issued_letters.py)
adds encrypted letter snapshots and independent issue or reject decisions.
[202605310020](../../backend/alembic/versions/202605310020_hr_service_request_letter.py)
adds an optional response letter on service requests with a foreign key.
[202605310021](../../backend/alembic/versions/202605310021_validate_hr_request_letter_fk.py)
validates that foreign key.
[202605310022](../../backend/alembic/versions/202605310022_hr_employment_changes.py)
adds effective-dated employee change proposals and independent decisions.
[202605310023](../../backend/alembic/versions/202605310023_hr_payroll_snapshot.py)
adds an encrypted snapshot to payroll runs. Existing runs are untouched.
[202605310024](../../backend/alembic/versions/202605310024_hr_payslip_publication.py)
adds the publication receipt for an approved run and its snapshot digest.
[202605310025](../../backend/alembic/versions/202605310025_index_hr_payroll_run_lines.py)
adds a concurrent index for run and employee line lookups. Retry reuses a valid index with the expected definition.
[202605310026](../../backend/alembic/versions/202605310026_hr_payroll_exports.py)
adds the Finance export receipt and its reproducible CSV digest.
[202605310027](../../backend/alembic/versions/202605310027_hr_payroll_settlements.py)
adds retained external settlement events tied to the registered export.
[202605310028](../../backend/alembic/versions/202605310028_hr_offboarding_custody.py)
adds retained inventory custody receipts for offboarding.
[202605310029](../../backend/alembic/versions/202605310029_hr_employment_periods.py)
adds retained employment period records for separation and rehire.
[202605310030](../../backend/alembic/versions/202605310030_hr_it_custody.py)
adds a custody area and opaque device references while preserving existing store events.
[202605310031](../../backend/alembic/versions/202605310031_validate_hr_it_custody.py)
validates the area-specific custody constraint.
[202605310032](../../backend/alembic/versions/202605310032_hr_separation_settlements.py)
adds independently reviewed separation settlement receipts.
[202605310033](../../backend/alembic/versions/202605310033_hr_training_completions.py)
adds one verified certificate receipt per enrollment and retains its exact document version.
[202605310034](../../backend/alembic/versions/202605310034_hr_training_requirements.py)
adds mandatory course rules by job position, project site, or both.
[202605310035](../../backend/alembic/versions/202605310035_hr_performance_events.py)
retains participant decisions and finalized review addenda.
[202605310036](../../backend/alembic/versions/202605310036_hr_performance_scale_handoff.py)
adds optional cycle rating labels and preserves authorized reviewer handoffs.
[202605310037](../../backend/alembic/versions/202605310037_hr_roster_allocations.py)
adds a roster ledger with snapshot schedule intervals and retained cancellations.
[202605310038](../../backend/alembic/versions/202605310038_hr_application_withdrawal.py)
adds the recorded withdrawal and retention review fields to applications.
[202605310039](../../backend/alembic/versions/202605310039_hr_candidate_correspondence.py)
adds encrypted candidate correspondence and its independent decision record.
[202605310040](../../backend/alembic/versions/202605310040_index_hr_application_activity.py)
indexes recruitment stage history in the application audit trail.
[202605310041](../../backend/alembic/versions/202605310041_hr_policy_edition_binding.py)
adds the exact document version and preceding edition for published HR policies.
[202605310042](../../backend/alembic/versions/202605310042_validate_hr_policy_edition.py)
validates the policy edition constraints.
[202605310043](../../backend/alembic/versions/202605310043_hr_offer_document_version.py)
adds the nullable reference to an exact offer PDF version, and
[202605310044](../../backend/alembic/versions/202605310044_validate_hr_offer_document_version.py)
validates the reference. Existing offers retain their terms without a file link.
[202605310045](../../backend/alembic/versions/202605310045_hr_leave_accrual_proration.py)
adds opt-in calendar-day proration and receipt bounds.
[202605310046](../../backend/alembic/versions/202605310046_validate_hr_leave_proration.py)
validates those bounds.
