# storage_locations

Stores warehouse and project site stores for location-aware inventory.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique storage location identifier. |
| `code` | `VARCHAR(30)` | Unique | Short location code. |
| `name` | `VARCHAR(150)` |  | Human-readable warehouse or site store name. |
| `location_type` | `VARCHAR(20)` |  | `warehouse` or `site`. |
| `project_id` | `UUID` | FK | Optional project when this is a project site store. References [projects](projects.md). |
| `address` | `TEXT` |  | Physical address or location notes. |
| `is_active` | `BOOLEAN` |  | Inactive locations cannot receive new stock movements. |
| `created_at` | `TIMESTAMPTZ` |  | Creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last update timestamp. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Optional project relation to [projects](projects.md).
- Holds [inventory_location_stock](inventory_location_stock.md).
- Is current location for [inventory_assets](inventory_assets.md).
- Is source or destination in [inventory_movements](inventory_movements.md).

## Indexes

- `idx_storage_locations_type` on `location_type` where active and not deleted.
