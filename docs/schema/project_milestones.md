# project_milestones

Project milestones by discipline, with planned and actual dates and progress.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/project_milestone.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `project_id` | `uuid` | No | — |
| `name` | `varchar(150)` | No | — |
| `discipline` | `varchar(50)` | Yes | — |
| `planned_start_date` | `date` | Yes | — |
| `planned_end_date` | `date` | Yes | — |
| `actual_start_date` | `date` | Yes | — |
| `actual_end_date` | `date` | Yes | — |
| `progress_percentage` | `numeric(5, 2)` | No | `0` |
| `status` | `varchar(30)` | No | `'not_started'` |
| `sort_order` | `integer` | No | `0` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_project_milestones` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_project_milestones_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_project_milestones_project` | `btree` | `project_id, sort_order` | No | — |
| `idx_project_milestones_status` | `btree` | `status` | No | `(deleted_at IS NULL)` |
