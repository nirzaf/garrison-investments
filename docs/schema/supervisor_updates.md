# supervisor_updates

Defined in `backend/app/models/supervisor_update.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `supervisor_id` | UUID | NOT NULL | — | users.id | — |
| `update_date` | Date | NOT NULL | — | — | — |
| `day_type` | String(20) | NOT NULL | weekday | — | — |
| `work_location` | String(255) | NOT NULL | — | — | — |
| `attendance_count` | Integer | NOT NULL | — | — | — |
| `overtime_hours` | Numeric(5, 2) | NOT NULL | 0 | — | — |
| `progress_notes` | Text | NOT NULL | — | — | — |
| `delay_notes` | Text | NULL | — | — | — |
| `required_notes` | Text | NOT NULL | — | — | — |
| `status` | String(20) | NOT NULL | draft | — | — |
| `submitted_at` | TimestampTZ | NULL | — | — | — |
| `verified_by` | UUID | NULL | — | users.id | — |
| `verified_at` | TimestampTZ | NULL | — | — | — |
| `verification_notes` | Text | NULL | — | — | — |
