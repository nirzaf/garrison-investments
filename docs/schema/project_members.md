# project_members

Defined in `backend/app/models/project_member.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `user_id` | UUID | NOT NULL | — | users.id | — |
| `role_in_project` | String(50) | NULL | — | — | — |
| `assigned_at` | TimestampTZ | NOT NULL | now() | — | — |
