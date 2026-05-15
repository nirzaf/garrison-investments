# project_members

Joins users to projects and defines their project-level responsibility.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique assignment identifier. |
| `project_id` | `UUID` | FK | Project assignment. References [projects](projects.md). |
| `user_id` | `UUID` | FK | Assigned employee. References [users](users.md). |
| `role_in_project` | `VARCHAR(50)` |  | Project-specific label such as `lead_engineer`, `supervisor`, or `store_keeper`. |
| `assigned_at` | `TIMESTAMPTZ` |  | Assignment timestamp. |

## Relations

- Belongs to one [project](projects.md).
- Belongs to one [user](users.md).

## Constraints and Indexes

- Unique pair: `(project_id, user_id)`.
- `idx_project_members_project` on `project_id`.
- `idx_project_members_user` on `user_id`.
