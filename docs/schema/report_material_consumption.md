# report_material_consumption

Defined in `backend/app/models/daily_report.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `report_id` | UUID | NOT NULL | — | daily_reports.id | — |
| `boq_item_id` | UUID | NULL | — | boq_items.id | — |
| `material_name` | String(160) | NOT NULL | — | — | — |
| `unit` | String(30) | NOT NULL | — | — | — |
| `quantity` | Numeric(14, 3) | NOT NULL | — | — | — |
| `remarks` | Text | NULL | — | — | — |
