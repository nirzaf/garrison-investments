# import_batches

Defined in `backend/app/models/import_batch.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `created_by` | UUID | NULL | — | users.id | — |
| `error_count` | Integer | NOT NULL | 0 | — | — |
| `file_name` | String(255) | NOT NULL | — | — | — |
| `row_count` | Integer | NOT NULL | 0 | — | — |
| `status` | String(30) | NOT NULL | — | — | — |
| `summary` | JSONB | NULL | — | — | — |
| `template_type` | String(40) | NOT NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

