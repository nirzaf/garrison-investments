# inventory_location_stock

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `item_id` | UUID | NOT NULL | — | inventory_items.id | — |
| `location_id` | UUID | NOT NULL | — | storage_locations.id | — |
| `on_hand_qty` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `reserved_qty` | Numeric(14, 3) | NOT NULL | 0 | — | — |
