# Database schema

[Documentation index](../README.md) · [Architecture](../ARCHITECTURE.md) · [Operations and deployment](../OPERATIONS_AND_DEPLOYMENT.md)

This reference covers the core operational tables along with the HR & Workforce Management schema defined in [Alembic revision `202605310007`](../../backend/alembic/versions/202605310007_hr_workforce_management.py) (see also [`backend/app/models/hr.py`](../../backend/app/models/hr.py)). Each core table page links to its [SQLAlchemy model](../../backend/app/models/) and lists PostgreSQL columns, server defaults, constraints, and indexes from the migrated schema. Follow [Alembic migrations](../../backend/alembic/versions/) to trace schema changes.

A dash in the default column means the database has no server default. Application-side rules live in the linked model and service code. Many tables use `deleted_at` for soft deletion. Foreign-key delete actions describe physical row deletion.

## Identity

| Table | Purpose |
| --- | --- |
| [`users`](users.md) | Portal accounts, roles, profile fields, password hashes, and sign-in lockout state. |
| [`auth_otp_challenges`](auth_otp_challenges.md) | Hashed one-time codes for login and password reset, with expiry, attempts, and consumption state. |
| [`auth_refresh_tokens`](auth_refresh_tokens.md) | Hashed refresh tokens with expiry and revocation timestamps. |

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
| [`activity_log`](activity_log.md) | Audit and operational events with actor, request, context, and retention metadata. |
| [`idempotency_records`](idempotency_records.md) | Request keys and resource references used to deduplicate retried writes. |
| [`task_outbox`](task_outbox.md) | Background work recorded in the same database transaction as the operation that schedules it. |

## HR and workforce management (migration `202605310007`)

Defined in [`backend/app/models/hr.py`](../../backend/app/models/hr.py) and [`202605310007_hr_workforce_management.py`](../../backend/alembic/versions/202605310007_hr_workforce_management.py):

| Domain | Tables |
| --- | --- |
| Core organization & employee master | `hr_departments`, `hr_positions`, `hr_employees`, `hr_employee_private` (Fernet-encrypted sensitive fields), `hr_employment_history` (immutable audit ledger), `hr_access_requests` (3-party HR/Admin provisioning queue) |
| Recruitment & onboarding | `hr_requisitions`, `hr_candidates`, `hr_applications`, `hr_interviews`, `hr_offers`, `hr_onboarding_cases`, `hr_onboarding_tasks` |
| HR documents vault & compliance | `hr_documents` (category RBAC: ordinary, confidential, medical, compensation, disciplinary), `hr_document_versions` |
| Time, attendance & leave | `hr_work_calendars`, `hr_holidays`, `hr_shift_assignments`, `hr_attendance_entries`, `hr_attendance_corrections`, `hr_timesheets`, `hr_overtime_requests`, `hr_leave_types`, `hr_leave_policies`, `hr_leave_ledger`, `hr_leave_requests` |
| Policies, letters, requests & offboarding | `hr_policy_documents`, `hr_policy_acknowledgements`, `hr_letter_templates`, `hr_hr_requests`, `hr_offboarding_cases`, `hr_clearance_steps` |
| P2 governance & policy-gated modules | `hr_goals`, `hr_review_cycles`, `hr_reviews`, `hr_training_courses`, `hr_training_enrollments`, `hr_certifications`, `hr_benefit_types`, `hr_employee_benefits`, `hr_reimbursement_claims`, `hr_compensation_terms`, `hr_payroll_policies` (dual-approval gate), `hr_payroll_periods`, `hr_payroll_runs`, `hr_payroll_lines`, `hr_cases` (encrypted restricted case details) |

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
