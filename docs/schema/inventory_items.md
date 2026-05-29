# inventory_items

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `category` | String(80) | NOT NULL | — | — | — |
| `is_active` | Boolean | NOT NULL | true | — | — |
| `item_code` | String(60) | NULL | — | — | — |
| `item_type` | String(30) | NOT NULL | — | — | — |
| `minimum_stock` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `name` | String(180) | NOT NULL | — | — | — |
| `reorder_level` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `supplier_id` | UUID | NULL | — | — | — |
| `unit` | String(20) | NOT NULL | — | — | — |
| `unit_cost` | Numeric(14, 2) | NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

