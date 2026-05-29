# project_milestones

Defined in `backend/app/models/project_milestone.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `name` | String(150) | NOT NULL | — | — | — |
| `discipline` | String(50) | NULL | — | — | — |
| `planned_start_date` | Date | NULL | — | — | — |
| `planned_end_date` | Date | NULL | — | — | — |
| `actual_start_date` | Date | NULL | — | — | — |
| `actual_end_date` | Date | NULL | — | — | — |
| `progress_percentage` | Numeric(5, 2) | NOT NULL | 0 | — | — |
| `status` | String(30) | NOT NULL | not_started | — | — |
| `sort_order` | Integer | NOT NULL | 0 | — | — |
