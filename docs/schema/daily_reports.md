# daily_reports

Defined in `backend/app/models/daily_report.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `engineer_id` | UUID | NOT NULL | — | users.id | — |
| `report_number` | String(60) | NULL | — | — | — |
| `report_date` | Date | NOT NULL | — | — | — |
| `work_location` | String(255) | NOT NULL | — | — | — |
| `manpower_total` | Integer | NOT NULL | 0 | — | — |
| `overtime_hours` | Numeric(5, 2) | NOT NULL | 0 | — | — |
| `work_completed` | Text | NOT NULL | — | — | — |
| `progress_percentage` | Numeric(5, 2) | NOT NULL | — | — | — |
| `safety_incidents` | Integer | NOT NULL | 0 | — | — |
| `safety_notes` | Text | NULL | — | — | — |
| `wir_status` | String(50) | NOT NULL | — | — | — |
| `inspection_status` | String(50) | NOT NULL | — | — | — |
| `delay_notes` | Text | NULL | — | — | — |
| `next_day_plan` | Text | NOT NULL | — | — | — |
| `status` | String(20) | NOT NULL | draft | — | — |
| `submitted_at` | TimestampTZ | NULL | — | — | — |
| `approved_by` | UUID | NULL | — | users.id | — |
| `approved_at` | TimestampTZ | NULL | — | — | — |
| `rejection_comments` | Text | NULL | — | — | — |
| `extra_fields` | JSONB | NOT NULL | — | — | — |
