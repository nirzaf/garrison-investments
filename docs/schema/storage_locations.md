# storage_locations

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `address` | Text | NULL | — | — | — |
| `code` | String(40) | NOT NULL | — | — | — |
| `is_active` | Boolean | NOT NULL | true | — | — |
| `location_type` | String(30) | NOT NULL | — | — | — |
| `name` | String(160) | NOT NULL | — | — | — |
| `project_id` | UUID | NULL | — | projects.id | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

