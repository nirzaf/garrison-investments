# inventory_assets

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `asset_tag` | String(80) | NOT NULL | — | — | — |
| `condition` | String(40) | NOT NULL | good | — | — |
| `current_location_id` | UUID | NOT NULL | — | storage_locations.id | — |
| `item_id` | UUID | NOT NULL | — | inventory_items.id | — |
| `status` | String(30) | NOT NULL | active | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

