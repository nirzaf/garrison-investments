# report_material_consumption

Material usage recorded in a daily report, optionally linked to a bill of quantities item.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/daily_report.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `report_id` | `uuid` | No | — |
| `boq_item_id` | `uuid` | Yes | — |
| `material_name` | `varchar(160)` | No | — |
| `unit` | `varchar(30)` | No | — |
| `quantity` | `numeric(14, 3)` | No | — |
| `remarks` | `text` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_report_material_consumption` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_report_material_consumption_boq_item_id_boq_items` | `(boq_item_id)` | [`boq_items(id)`](boq_items.md) | `SET NULL` |
| `fk_report_material_consumption_report_id_daily_reports` | `(report_id)` | [`daily_reports(id)`](daily_reports.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_report_material_consumption_report` | `btree` | `report_id` | No | — |
