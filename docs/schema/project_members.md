# project_members

Defined in `backend/app/models/project_member.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `assigned_at` | TimestampTZ | NOT NULL | now() | — | — |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `role_in_project` | String(50) | NULL | — | — | — |
| `user_id` | UUID | NOT NULL | — | users.id | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

