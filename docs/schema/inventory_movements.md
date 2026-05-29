# inventory_movements

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `item_id` | UUID | NOT NULL | — | inventory_items.id | — |
| `asset_id` | UUID | NULL | — | inventory_assets.id | — |
| `movement_type` | String(30) | NOT NULL | — | — | — |
| `quantity` | Numeric(14, 3) | NOT NULL | — | — | — |
| `from_location_id` | UUID | NULL | — | storage_locations.id | — |
| `to_location_id` | UUID | NULL | — | storage_locations.id | — |
| `project_id` | UUID | NULL | — | projects.id | — |
| `reference_type` | String(40) | NULL | — | — | — |
| `reference_id` | UUID | NULL | — | — | — |
| `handled_by` | UUID | NULL | — | users.id | — |
| `notes` | Text | NULL | — | — | — |
