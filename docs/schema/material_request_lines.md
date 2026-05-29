# material_request_lines

Defined in `backend/app/models/inventory.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `request_id` | UUID | NOT NULL | — | material_requests.id | — |
| `item_id` | UUID | NOT NULL | — | inventory_items.id | — |
| `quantity` | Numeric(14, 3) | NOT NULL | — | — | — |
| `reserved_quantity` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `issued_quantity` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `unit_cost` | Numeric(14, 2) | NULL | — | — | — |
