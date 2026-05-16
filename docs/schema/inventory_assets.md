# inventory_assets

Stores individual tagged tools/items and their current warehouse/site location.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique asset identifier. |
| `item_id` | `UUID` | FK | Catalog item. References [inventory_items](inventory_items.md). |
| `asset_tag` | `VARCHAR(50)` | Unique | Physical tag/label used to identify the tool/item. |
| `serial_number` | `VARCHAR(100)` |  | Manufacturer serial number, if available. |
| `current_location_id` | `UUID` | FK | Current warehouse/site. References [storage_locations](storage_locations.md). |
| `project_id` | `UUID` | FK | Optional current project association. References [projects](projects.md). |
| `status` | `VARCHAR(20)` |  | `available`, `reserved`, `issued`, `in_repair`, or `retired`. |
| `condition` | `VARCHAR(30)` |  | Current condition such as good, damaged, calibration due. |
| `last_movement_id` | `UUID` | FK | Last movement record. References [inventory_movements](inventory_movements.md). |
| `created_at` | `TIMESTAMPTZ` |  | Creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last update timestamp. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Belongs to [inventory_items](inventory_items.md).
- Currently located at [storage_locations](storage_locations.md).
- Optionally associated with [projects](projects.md).
- Has movement history in [inventory_movements](inventory_movements.md).

## Indexes

- `idx_assets_current_location` on `current_location_id` where not deleted.
- `idx_assets_status` on `status` where not deleted.
