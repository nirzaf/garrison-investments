# material_requests

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `from_location_id` | UUID | NULL | — | storage_locations.id | — |
| `notes` | Text | NULL | — | — | — |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `request_number` | String(60) | NOT NULL | — | — | — |
| `requester_id` | UUID | NULL | — | users.id | — |
| `status` | String(30) | NOT NULL | requested | — | — |
| `total_estimated_cost` | Numeric(14, 2) | NOT NULL | 0 | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

