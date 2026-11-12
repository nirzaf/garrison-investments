# Database schema

[Documentation index](../README.md) · [Architecture](../ARCHITECTURE.md) · [Operations and deployment](../OPERATIONS_AND_DEPLOYMENT.md)

This reference covers the 34 application tables at [Alembic head `202605300003`](../../backend/alembic/versions/202605300003_repair_inventory_reservations.py). Each page links to its [SQLAlchemy model](../../backend/app/models/) and lists PostgreSQL columns, server defaults, constraints, and indexes from the migrated schema. Follow [Alembic migrations](../../backend/alembic/versions/) to trace schema changes.

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
