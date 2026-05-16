# `users`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `email` | `VARCHAR(255)` | No | `` |  |
| `full_name` | `VARCHAR(255)` | No | `` |  |
| `role` | `VARCHAR(64)` | No | `` |  |
| `employee_code` | `VARCHAR(64)` | Yes | `` |  |
| `phone` | `VARCHAR(32)` | Yes | `` |  |
| `designation` | `VARCHAR(100)` | Yes | `` |  |
| `password_hash` | `VARCHAR(255)` | Yes | `` |  |
| `is_active` | `BOOLEAN` | No | `true` |  |
| `must_change_password` | `BOOLEAN` | No | `true` |  |
| `failed_login_attempts` | `INTEGER` | No | `0` |  |
| `locked_until` | `DATETIME` | Yes | `` |  |
| `last_login_at` | `DATETIME` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Referenced By

| Source | Target |
|---|---|
| `activity_log.user_id` | `users.id` |
| `approvals.submitter_id` | `users.id` |
| `approvals.approver_id` | `users.id` |
| `approvals.delegated_to_id` | `users.id` |
| `approvals.escalation_user_id` | `users.id` |
| `auth_otp_challenges.user_id` | `users.id` |
| `auth_refresh_tokens.user_id` | `users.id` |
| `daily_report_approval_history.actor_id` | `users.id` |
| `daily_reports.engineer_id` | `users.id` |
| `daily_reports.approved_by` | `users.id` |
| `document_versions.uploaded_by` | `users.id` |
| `document_versions.approved_by` | `users.id` |
| `documents.uploaded_by` | `users.id` |
| `import_batches.created_by` | `users.id` |
| `inventory_movements.handled_by` | `users.id` |
| `invoices.created_by` | `users.id` |
| `invoices.approved_by` | `users.id` |
| `material_requests.requester_id` | `users.id` |
| `notifications.user_id` | `users.id` |
| `payments.recorded_by` | `users.id` |
| `photos.uploaded_by` | `users.id` |
| `project_members.user_id` | `users.id` |
| `projects.created_by` | `users.id` |
| `report_exports.generated_by` | `users.id` |
| `supervisor_updates.supervisor_id` | `users.id` |
| `supervisor_updates.verified_by` | `users.id` |
