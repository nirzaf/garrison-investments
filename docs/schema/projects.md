# projects

Project identity, contract and client details, schedule, budget, and progress.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/project.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `name` | `varchar(200)` | No | — |
| `code` | `varchar(20)` | No | — |
| `location` | `text` | Yes | — |
| `description` | `text` | Yes | — |
| `scope_of_work` | `text` | No | — |
| `status` | `varchar(30)` | No | `'planning'` |
| `budget_amount` | `numeric(15, 2)` | Yes | — |
| `start_date` | `date` | Yes | — |
| `target_end_date` | `date` | No | — |
| `actual_end_date` | `date` | Yes | — |
| `client_name` | `varchar(200)` | Yes | — |
| `contract_number` | `varchar(50)` | Yes | — |
| `progress_percentage` | `numeric(5, 2)` | No | `0` |
| `created_by` | `uuid` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |
| `revision` | `integer` | No | `1` |

Project metadata and team changes advance the revision under a project row lock. The project editor sends the revision it opened and receives a conflict if another edit committed first.

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_projects` | `PRIMARY KEY (id)` |
| `ck_projects_ck_projects_status_valid` | `CHECK ((status IN ('planning', 'active', 'on_hold', 'completed', 'cancelled')))` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_projects_created_by_users` | `(created_by)` | [`users(id)`](users.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_projects_code` | `btree` | `code` | No | — |
| `idx_projects_status` | `btree` | `status` | No | `(deleted_at IS NULL)` |
| `uq_projects_code_active` | `btree` | `code` | Yes | `(deleted_at IS NULL)` |
