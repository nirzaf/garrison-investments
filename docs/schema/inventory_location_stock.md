# inventory_location_stock

Stores on-hand, reserved, and available quantity for each inventory item at each warehouse/site store.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique stock row identifier. |
| `item_id` | `UUID` | FK | Inventory item. References [inventory_items](inventory_items.md). |
| `location_id` | `UUID` | FK | Warehouse/site location. References [storage_locations](storage_locations.md). |
| `on_hand_qty` | `DECIMAL(12,3)` |  | Physical quantity recorded at this location. |
| `reserved_qty` | `DECIMAL(12,3)` |  | Quantity reserved for approved issue/transfer requests. |
| `available_qty` | `DECIMAL(12,3)` |  | Generated value: `on_hand_qty - reserved_qty`. |
| `updated_at` | `TIMESTAMPTZ` |  | Last stock recalculation/update timestamp. |

## Relations

- Belongs to [inventory_items](inventory_items.md).
- Belongs to [storage_locations](storage_locations.md).
- Updated by approved [inventory_movements](inventory_movements.md).

## Constraints and Indexes

- Unique pair: `(item_id, location_id)`.
- `idx_inventory_stock_item` on `item_id`.
- `idx_inventory_stock_location` on `location_id`.
- `idx_inventory_stock_low` for low-stock/reserved stock monitoring.
