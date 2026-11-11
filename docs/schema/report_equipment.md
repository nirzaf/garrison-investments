# report_equipment

Defined in `backend/app/models/daily_report.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `equipment_name` | String(120) | NOT NULL | — | — | — |
| `hours_used` | Numeric(6, 2) | NOT NULL | 0 | — | — |
| `quantity` | Integer | NOT NULL | — | — | — |
| `remarks` | Text | NULL | — | — | — |
| `report_id` | UUID | NOT NULL | — | daily_reports.id | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

