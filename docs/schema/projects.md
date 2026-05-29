# projects

Defined in `backend/app/models/project.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `name` | String(200) | NOT NULL | — | — | — |
| `code` | String(20) | NOT NULL | — | — | — |
| `location` | Text | NULL | — | — | — |
| `description` | Text | NULL | — | — | — |
| `scope_of_work` | Text | NOT NULL | — | — | — |
| `status` | String(30) | NOT NULL | planning | — | — |
| `budget_amount` | Numeric(15, 2) | NULL | — | — | — |
| `start_date` | Date | NULL | — | — | — |
| `target_end_date` | Date | NOT NULL | — | — | — |
| `actual_end_date` | Date | NULL | — | — | — |
| `client_name` | String(200) | NULL | — | — | — |
| `contract_number` | String(50) | NULL | — | — | — |
| `progress_percentage` | Numeric(5, 2) | NOT NULL | 0 | — | — |
| `created_by` | UUID | NULL | — | users.id | — |
