# material_request_lines

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `issued_quantity` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `item_id` | UUID | NOT NULL | — | inventory_items.id | — |
| `quantity` | Numeric(14, 3) | NOT NULL | — | — | — |
| `request_id` | UUID | NOT NULL | — | material_requests.id | — |
| `reserved_quantity` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `unit_cost` | Numeric(14, 2) | NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

