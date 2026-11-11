# supervisor_updates

Defined in `backend/app/models/supervisor_update.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `attachment_refs` | JSONB | NOT NULL | — | — | — |
| `attendance_count` | Integer | NOT NULL | — | — | — |
| `day_type` | String(20) | NOT NULL | weekday | — | — |
| `delay_notes` | Text | NULL | — | — | — |
| `overtime_hours` | Numeric(5, 2) | NOT NULL | 0 | — | — |
| `progress_notes` | Text | NOT NULL | — | — | — |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `required_notes` | Text | NOT NULL | — | — | — |
| `status` | String(20) | NOT NULL | draft | — | — |
| `submitted_at` | TimestampTZ | NULL | — | — | — |
| `supervisor_id` | UUID | NOT NULL | — | users.id | — |
| `update_date` | Date | NOT NULL | — | — | — |
| `verification_notes` | Text | NULL | — | — | — |
| `verified_at` | TimestampTZ | NULL | — | — | — |
| `verified_by` | UUID | NULL | — | users.id | — |
| `work_location` | String(255) | NOT NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

