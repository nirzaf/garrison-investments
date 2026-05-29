# material_requests

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `request_number` | String(60) | NOT NULL | — | — | — |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `requester_id` | UUID | NULL | — | users.id | — |
| `from_location_id` | UUID | NULL | — | storage_locations.id | — |
| `status` | String(30) | NOT NULL | requested | — | — |
| `total_estimated_cost` | Numeric(14, 2) | NOT NULL | 0 | — | — |
| `notes` | Text | NULL | — | — | — |
