# projects

Defined in `backend/app/models/project.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `actual_end_date` | Date | NULL | — | — | — |
| `budget_amount` | Numeric(15, 2) | NULL | — | — | — |
| `client_name` | String(200) | NULL | — | — | — |
| `code` | String(20) | NOT NULL | — | — | — |
| `contract_number` | String(50) | NULL | — | — | — |
| `created_by` | UUID | NULL | — | users.id | — |
| `description` | Text | NULL | — | — | — |
| `location` | Text | NULL | — | — | — |
| `name` | String(200) | NOT NULL | — | — | — |
| `progress_percentage` | Numeric(5, 2) | NOT NULL | 0 | — | — |
| `scope_of_work` | Text | NOT NULL | — | — | — |
| `start_date` | Date | NULL | — | — | — |
| `status` | String(30) | NOT NULL | planning | — | — |
| `target_end_date` | Date | NOT NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

