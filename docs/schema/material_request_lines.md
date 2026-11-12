# material_request_lines

Requested, reserved, and issued quantities for each material request line.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/inventory.py)

`reserved_quantity` records the line’s remaining reservation. The [inventory service](../../backend/app/services/inventory_service.py) updates it when issuing or releasing stock.

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `request_id` | `uuid` | No | — |
| `item_id` | `uuid` | No | — |
| `quantity` | `numeric(14, 3)` | No | — |
| `reserved_quantity` | `numeric(14, 3)` | No | `0` |
| `issued_quantity` | `numeric(14, 3)` | No | `0` |
| `unit_cost` | `numeric(14, 2)` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_material_request_lines` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_material_request_lines_item_id_inventory_items` | `(item_id)` | [`inventory_items(id)`](inventory_items.md) | `RESTRICT` |
| `fk_material_request_lines_request_id_material_requests` | `(request_id)` | [`material_requests(id)`](material_requests.md) | `CASCADE` |
