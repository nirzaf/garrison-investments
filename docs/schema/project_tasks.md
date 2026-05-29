# project_tasks

Defined in `backend/app/models/project_task.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `milestone_id` | UUID | NULL | — | project_milestones.id | — |
| `dependency_task_id` | UUID | NULL | — | project_tasks.id | — |
| `owner_id` | UUID | NULL | — | users.id | — |
| `name` | String(180) | NOT NULL | — | — | — |
| `baseline_start_date` | Date | NULL | — | — | — |
| `baseline_end_date` | Date | NULL | — | — | — |
| `planned_start_date` | Date | NULL | — | — | — |
| `planned_end_date` | Date | NULL | — | — | — |
| `actual_start_date` | Date | NULL | — | — | — |
| `actual_end_date` | Date | NULL | — | — | — |
| `status` | String(30) | NOT NULL | not_started | — | — |
| `progress_percentage` | Numeric(5, 2) | NOT NULL | 0 | — | — |
| `delay_reason` | Text | NULL | — | — | — |
| `sort_order` | Integer | NOT NULL | 0 | — | — |
