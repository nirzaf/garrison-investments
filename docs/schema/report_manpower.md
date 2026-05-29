# report_manpower

Defined in `backend/app/models/daily_report.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `count` | Integer | NOT NULL | — | — | — |
| `overtime_hours` | Numeric(5, 2) | NOT NULL | 0 | — | — |
| `report_id` | UUID | NOT NULL | — | daily_reports.id | — |
| `trade` | String(100) | NOT NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

