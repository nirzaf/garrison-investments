# daily_reports

Defined in `backend/app/models/daily_report.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `approved_at` | TimestampTZ | NULL | — | — | — |
| `approved_by` | UUID | NULL | — | users.id | — |
| `attachment_refs` | JSONB | NOT NULL | — | — | — |
| `delay_notes` | Text | NULL | — | — | — |
| `engineer_id` | UUID | NOT NULL | — | users.id | — |
| `extra_fields` | JSONB | NOT NULL | — | — | — |
| `inspection_status` | String(50) | NOT NULL | — | — | — |
| `manpower_total` | Integer | NOT NULL | 0 | — | — |
| `next_day_plan` | Text | NOT NULL | — | — | — |
| `overtime_hours` | Numeric(5, 2) | NOT NULL | 0 | — | — |
| `photo_refs` | JSONB | NOT NULL | — | — | — |
| `progress_percentage` | Numeric(5, 2) | NOT NULL | — | — | — |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `rejection_comments` | Text | NULL | — | — | — |
| `report_date` | Date | NOT NULL | — | — | — |
| `report_number` | String(60) | NULL | — | — | — |
| `safety_incidents` | Integer | NOT NULL | 0 | — | — |
| `safety_notes` | Text | NULL | — | — | — |
| `status` | String(20) | NOT NULL | draft | — | — |
| `submitted_at` | TimestampTZ | NULL | — | — | — |
| `supervisor_update_ids` | JSONB | NOT NULL | — | — | — |
| `wir_status` | String(50) | NOT NULL | — | — | — |
| `work_completed` | Text | NOT NULL | — | — | — |
| `work_location` | String(255) | NOT NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

