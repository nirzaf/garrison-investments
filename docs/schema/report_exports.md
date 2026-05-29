# report_exports

Defined in `backend/app/models/report_export.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `report_id` | UUID | NOT NULL | — | daily_reports.id | — |
| `generated_by` | UUID | NULL | — | users.id | — |
| `file_name` | String(255) | NOT NULL | — | — | — |
| `object_key` | String(512) | NOT NULL | — | — | — |
| `content_type` | String(120) | NOT NULL | — | — | — |
| `status` | String(20) | NOT NULL | ready | — | — |
| `error_message` | Text | NULL | — | — | — |
| `email_status` | String(20) | NULL | — | — | — |
| `email_error` | Text | NULL | — | — | — |
| `emailed_at` | TimestampTZ | NULL | — | — | — |
| `generated_at` | TimestampTZ | NOT NULL | — | — | — |
