# report_exports

Daily report export status, object-storage keys, and email delivery state.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/report_export.py)

The report export record tracks generation and email outcomes separately. The file itself is stored under `object_key`.

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `report_id` | `uuid` | No | — |
| `generated_by` | `uuid` | Yes | — |
| `file_name` | `varchar(255)` | No | — |
| `object_key` | `varchar(512)` | No | — |
| `content_type` | `varchar(120)` | No | — |
| `status` | `varchar(20)` | No | `'ready'` |
| `error_message` | `text` | Yes | — |
| `email_status` | `varchar(20)` | Yes | — |
| `email_error` | `text` | Yes | — |
| `emailed_at` | `timestamptz` | Yes | — |
| `generated_at` | `timestamptz` | No | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_report_exports` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_report_exports_generated_by_users` | `(generated_by)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_report_exports_report_id_daily_reports` | `(report_id)` | [`daily_reports(id)`](daily_reports.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_report_exports_report` | `btree` | `report_id, created_at` | No | — |
| `idx_report_exports_status` | `btree` | `status` | No | — |
