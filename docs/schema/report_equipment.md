# report_equipment

Defined in `backend/app/models/daily_report.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `report_id` | UUID | NOT NULL | — | daily_reports.id | — |
| `equipment_name` | String(120) | NOT NULL | — | — | — |
| `quantity` | Integer | NOT NULL | — | — | — |
| `hours_used` | Numeric(6, 2) | NOT NULL | 0 | — | — |
| `remarks` | Text | NULL | — | — | — |
