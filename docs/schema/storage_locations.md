# storage_locations

Storage locations with optional project association and active status.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/inventory.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `name` | `varchar(160)` | No | — |
| `code` | `varchar(40)` | No | — |
| `location_type` | `varchar(30)` | No | — |
| `project_id` | `uuid` | Yes | — |
| `address` | `text` | Yes | — |
| `is_active` | `boolean` | No | `true` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_storage_locations` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_storage_locations_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_storage_locations_type` | `btree` | `location_type` | No | — |
| `uq_storage_locations_code_active` | `btree` | `code` | Yes | — |
