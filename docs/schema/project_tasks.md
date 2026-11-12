# project_tasks

Scheduled work with an optional milestone, predecessor task, and owner.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/project_task.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `project_id` | `uuid` | No | — |
| `milestone_id` | `uuid` | Yes | — |
| `dependency_task_id` | `uuid` | Yes | — |
| `owner_id` | `uuid` | Yes | — |
| `name` | `varchar(180)` | No | — |
| `baseline_start_date` | `date` | Yes | — |
| `baseline_end_date` | `date` | Yes | — |
| `planned_start_date` | `date` | Yes | — |
| `planned_end_date` | `date` | Yes | — |
| `actual_start_date` | `date` | Yes | — |
| `actual_end_date` | `date` | Yes | — |
| `status` | `varchar(30)` | No | `'not_started'` |
| `progress_percentage` | `numeric(5, 2)` | No | `0` |
| `delay_reason` | `text` | Yes | — |
| `sort_order` | `integer` | No | `0` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_project_tasks` | `PRIMARY KEY (id)` |
| `ck_project_tasks_ck_project_tasks_progress_valid` | `CHECK (((progress_percentage >= 0) AND (progress_percentage <= 100)))` |
| `ck_project_tasks_ck_project_tasks_status_valid` | `CHECK ((status IN ('not_started', 'in_progress', 'blocked', 'completed', 'cancelled')))` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_project_tasks_dependency_task_id_project_tasks` | `(dependency_task_id)` | [`project_tasks(id)`](project_tasks.md) | `SET NULL` |
| `fk_project_tasks_milestone_id_project_milestones` | `(milestone_id)` | [`project_milestones(id)`](project_milestones.md) | `SET NULL` |
| `fk_project_tasks_owner_id_users` | `(owner_id)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_project_tasks_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_project_tasks_dependency` | `btree` | `dependency_task_id` | No | — |
| `idx_project_tasks_owner` | `btree` | `owner_id` | No | — |
| `idx_project_tasks_project` | `btree` | `project_id, status` | No | — |
