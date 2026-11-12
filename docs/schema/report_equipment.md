# report_equipment

Equipment quantities and usage hours recorded in a daily report.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/daily_report.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `report_id` | `uuid` | No | — |
| `equipment_name` | `varchar(120)` | No | — |
| `quantity` | `integer` | No | — |
| `hours_used` | `numeric(6, 2)` | No | `0` |
| `remarks` | `text` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_report_equipment` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_report_equipment_report_id_daily_reports` | `(report_id)` | [`daily_reports(id)`](daily_reports.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_report_equipment_report` | `btree` | `report_id` | No | — |
