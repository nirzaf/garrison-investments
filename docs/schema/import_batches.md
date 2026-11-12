# import_batches

Spreadsheet import status, row counts, validation errors, and results.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/import_batch.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `template_type` | `varchar(40)` | No | — |
| `file_name` | `varchar(255)` | No | — |
| `status` | `varchar(30)` | No | — |
| `created_by` | `uuid` | Yes | — |
| `row_count` | `integer` | No | `0` |
| `error_count` | `integer` | No | `0` |
| `summary` | `jsonb` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_import_batches` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_import_batches_created_by_users` | `(created_by)` | [`users(id)`](users.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_import_batches_type` | `btree` | `template_type, created_at` | No | — |
