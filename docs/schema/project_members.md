# project_members

Project membership and project-specific roles for portal users.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/project_member.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `project_id` | `uuid` | No | — |
| `user_id` | `uuid` | No | — |
| `role_in_project` | `varchar(50)` | Yes | — |
| `assigned_at` | `timestamptz` | No | `now()` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_project_members` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_project_members_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `CASCADE` |
| `fk_project_members_user_id_users` | `(user_id)` | [`users(id)`](users.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_project_members_project` | `btree` | `project_id` | No | — |
| `idx_project_members_user` | `btree` | `user_id` | No | — |
| `uq_project_members_active` | `btree` | `project_id, user_id` | Yes | `(deleted_at IS NULL)` |
