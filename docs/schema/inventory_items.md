# `inventory_items`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `name` | `VARCHAR(180)` | No | `` |  |
| `item_code` | `VARCHAR(60)` | Yes | `` |  |
| `category` | `VARCHAR(80)` | No | `` |  |
| `item_type` | `VARCHAR(30)` | No | `` |  |
| `unit` | `VARCHAR(20)` | No | `` |  |
| `minimum_stock` | `NUMERIC(14, 3)` | No | `0` |  |
| `reorder_level` | `NUMERIC(14, 3)` | No | `0` |  |
| `unit_cost` | `NUMERIC(14, 2)` | Yes | `` |  |
| `supplier_id` | `UUID` | Yes | `` |  |
| `is_active` | `BOOLEAN` | No | `true` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Referenced By

| Source | Target |
|---|---|
| `inventory_assets.item_id` | `inventory_items.id` |
| `inventory_location_stock.item_id` | `inventory_items.id` |
| `inventory_movements.item_id` | `inventory_items.id` |
| `material_request_lines.item_id` | `inventory_items.id` |
