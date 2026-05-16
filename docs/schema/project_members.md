# `project_members`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `user_id` | `UUID` | No | `` | users.id |
| `role_in_project` | `VARCHAR(50)` | Yes | `` |  |
| `assigned_at` | `DATETIME` | No | `now()` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `project_id` | `projects.id` |
| `user_id` | `users.id` |
