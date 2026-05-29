# inventory_items

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `name` | String(180) | NOT NULL | — | — | — |
| `item_code` | String(60) | NULL | — | — | — |
| `category` | String(80) | NOT NULL | — | — | — |
| `item_type` | String(30) | NOT NULL | — | — | — |
| `unit` | String(20) | NOT NULL | — | — | — |
| `minimum_stock` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `reorder_level` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `unit_cost` | Numeric(14, 2) | NULL | — | — | — |
| `supplier_id` | UUID | NULL | — | — | — |
| `is_active` | Boolean | NOT NULL | true | — | — |
