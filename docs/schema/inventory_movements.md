# inventory_movements

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `asset_id` | UUID | NULL | — | inventory_assets.id | — |
| `from_location_id` | UUID | NULL | — | storage_locations.id | — |
| `handled_by` | UUID | NULL | — | users.id | — |
| `item_id` | UUID | NOT NULL | — | inventory_items.id | — |
| `movement_type` | String(30) | NOT NULL | — | — | — |
| `notes` | Text | NULL | — | — | — |
| `project_id` | UUID | NULL | — | projects.id | — |
| `quantity` | Numeric(14, 3) | NOT NULL | — | — | — |
| `reference_id` | UUID | NULL | — | — | — |
| `reference_type` | String(40) | NULL | — | — | — |
| `to_location_id` | UUID | NULL | — | storage_locations.id | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

