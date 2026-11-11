# report_exports

Defined in `backend/app/models/report_export.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `content_type` | String(120) | NOT NULL | — | — | — |
| `email_error` | Text | NULL | — | — | — |
| `email_status` | String(20) | NULL | — | — | — |
| `emailed_at` | TimestampTZ | NULL | — | — | — |
| `error_message` | Text | NULL | — | — | — |
| `file_name` | String(255) | NOT NULL | — | — | — |
| `generated_at` | TimestampTZ | NOT NULL | — | — | — |
| `generated_by` | UUID | NULL | — | users.id | — |
| `object_key` | String(512) | NOT NULL | — | — | — |
| `report_id` | UUID | NOT NULL | — | daily_reports.id | — |
| `status` | String(20) | NOT NULL | ready | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

