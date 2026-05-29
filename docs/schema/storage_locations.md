# storage_locations

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `name` | String(160) | NOT NULL | — | — | — |
| `code` | String(40) | NOT NULL | — | — | — |
| `location_type` | String(30) | NOT NULL | — | — | — |
| `project_id` | UUID | NULL | — | projects.id | — |
| `address` | Text | NULL | — | — | — |
| `is_active` | Boolean | NOT NULL | true | — | — |
