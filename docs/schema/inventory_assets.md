# inventory_assets

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `item_id` | UUID | NOT NULL | — | inventory_items.id | — |
| `asset_tag` | String(80) | NOT NULL | — | — | — |
| `current_location_id` | UUID | NOT NULL | — | storage_locations.id | — |
| `condition` | String(40) | NOT NULL | good | — | — |
| `status` | String(30) | NOT NULL | active | — | — |
