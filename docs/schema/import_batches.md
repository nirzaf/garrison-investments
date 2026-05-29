# import_batches

Defined in `backend/app/models/import_batch.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `template_type` | String(40) | NOT NULL | — | — | — |
| `file_name` | String(255) | NOT NULL | — | — | — |
| `status` | String(30) | NOT NULL | — | — | — |
| `created_by` | UUID | NULL | — | users.id | — |
| `row_count` | Integer | NOT NULL | 0 | — | — |
| `error_count` | Integer | NOT NULL | 0 | — | — |
| `summary` | JSONB | NULL | — | — | — |
