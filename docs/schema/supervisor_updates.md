# `supervisor_updates`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `supervisor_id` | `UUID` | No | `` | users.id |
| `update_date` | `DATE` | No | `` |  |
| `day_type` | `VARCHAR(20)` | No | `'weekday'` |  |
| `work_location` | `VARCHAR(255)` | No | `` |  |
| `attendance_count` | `INTEGER` | No | `` |  |
| `overtime_hours` | `NUMERIC(5, 2)` | No | `0` |  |
| `progress_notes` | `TEXT` | No | `` |  |
| `delay_notes` | `TEXT` | Yes | `` |  |
| `required_notes` | `TEXT` | No | `` |  |
| `attachment_refs` | `JSONB` | No | `` |  |
| `status` | `VARCHAR(20)` | No | `'draft'` |  |
| `submitted_at` | `DATETIME` | Yes | `` |  |
| `verified_by` | `UUID` | Yes | `` | users.id |
| `verified_at` | `DATETIME` | Yes | `` |  |
| `verification_notes` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `project_id` | `projects.id` |
| `supervisor_id` | `users.id` |
| `verified_by` | `users.id` |
