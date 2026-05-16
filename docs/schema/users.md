# users

Stores employee accounts, fixed MVP role, authentication state, and lifecycle status.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique user identifier. |
| `email` | `VARCHAR(255)` | Unique | Login email; indexed for authentication lookup. |
| `password_hash` | `VARCHAR(255)` |  | Bcrypt/argon hash of the password. Never store plaintext. |
| `full_name` | `VARCHAR(150)` |  | Display name used across reports, approvals, and audit views. |
| `phone` | `VARCHAR(20)` |  | Optional contact number for operational follow-up. |
| `employee_code` | `VARCHAR(20)` | Unique | Internal employee identifier. |
| `role` | `VARCHAR(50)` |  | Fixed MVP role: `admin`, `operation_manager`, `project_manager`, `civil_engineer`, `civil_supervisor`, `store_keeper`, `accounts`. |
| `designation` | `VARCHAR(100)` |  | HR/job title text shown in admin screens. |
| `is_active` | `BOOLEAN` |  | Deactivated users cannot log in, but historical records remain linked. |
| `last_login_at` | `TIMESTAMPTZ` |  | Last successful login timestamp. |
| `refresh_token_hash` | `VARCHAR(255)` |  | Hash of current refresh token for session rotation. |
| `created_at` | `TIMESTAMPTZ` |  | Account creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last account metadata update. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. Prefer deactivation for historical identity. |

## Relations

- Creates [projects](projects.md) through `projects.created_by`.
- Assigned to [project_members](project_members.md) through `project_members.user_id`.
- Submits and approves [daily_reports](daily_reports.md).
- Uploads [documents](documents.md), [document_versions](document_versions.md), and [photos](photos.md).
- Requests or decides [approvals](approvals.md).
- Receives [notifications](notifications.md).
- Performs [inventory_movements](inventory_movements.md).
- Performs auditable actions in [activity_log](activity_log.md).

## Indexes

- `idx_users_email` on `email` where `deleted_at IS NULL`.
- `idx_users_role` on `role` where `deleted_at IS NULL`.
