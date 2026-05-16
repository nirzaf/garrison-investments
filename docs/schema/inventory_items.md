# inventory_items

Stores the shared catalog for consumable materials and trackable tools/items.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique inventory item identifier. |
| `name` | `VARCHAR(150)` |  | Item name. |
| `code` | `VARCHAR(30)` | Unique | Item code used in stock and movement screens. |
| `item_type` | `VARCHAR(20)` |  | `consumable` or `tool`. |
| `category` | `VARCHAR(50)` |  | Category such as cement, steel, tools, electrical, plumbing. |
| `unit` | `VARCHAR(20)` |  | Stock unit such as bags, ton, m3, pcs, nos. |
| `track_assets` | `BOOLEAN` |  | True when individual assets/tags must be tracked. |
| `minimum_stock` | `DECIMAL(12,3)` |  | Minimum expected quantity per business rule. |
| `reorder_point` | `DECIMAL(12,3)` |  | Quantity at which alerts/reorders should start. |
| `unit_price` | `DECIMAL(12,2)` |  | Latest or standard unit price. Access should be role restricted. |
| `supplier_id` | `UUID` | FK | Preferred supplier. References [suppliers](suppliers.md). |
| `created_at` | `TIMESTAMPTZ` |  | Creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last update timestamp. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Optionally supplied by [suppliers](suppliers.md).
- Has stock rows in [inventory_location_stock](inventory_location_stock.md).
- Has serialized assets in [inventory_assets](inventory_assets.md) when `track_assets = TRUE`.
- Has movement history in [inventory_movements](inventory_movements.md).
- Can be consumed by [report_material_consumption](report_material_consumption.md).

## Indexes

- `idx_inventory_items_category` on `category` where not deleted.
- `idx_inventory_items_type` on `item_type` where not deleted.
