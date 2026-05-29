# project_tasks

Defined in `backend/app/models/project_task.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `actual_end_date` | Date | NULL | — | — | — |
| `actual_start_date` | Date | NULL | — | — | — |
| `baseline_end_date` | Date | NULL | — | — | — |
| `baseline_start_date` | Date | NULL | — | — | — |
| `delay_reason` | Text | NULL | — | — | — |
| `dependency_task_id` | UUID | NULL | — | project_tasks.id | — |
| `milestone_id` | UUID | NULL | — | project_milestones.id | — |
| `name` | String(180) | NOT NULL | — | — | — |
| `owner_id` | UUID | NULL | — | users.id | — |
| `planned_end_date` | Date | NULL | — | — | — |
| `planned_start_date` | Date | NULL | — | — | — |
| `progress_percentage` | Numeric(5, 2) | NOT NULL | 0 | — | — |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `sort_order` | Integer | NOT NULL | 0 | — | — |
| `status` | String(30) | NOT NULL | not_started | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

