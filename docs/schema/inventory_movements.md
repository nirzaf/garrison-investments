# inventory_movements

Stores receive, request, reserve, issue, transfer, return, consume, and adjustment events for inventory.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique movement identifier. |
| `item_id` | `UUID` | FK | Inventory item moved. References [inventory_items](inventory_items.md). |
| `asset_id` | `UUID` | FK | Optional tagged asset. References [inventory_assets](inventory_assets.md). |
| `movement_type` | `VARCHAR(20)` |  | `receive`, `request`, `reserve`, `issue`, `transfer`, `return`, `consume`, or `adjustment`. |
| `quantity` | `DECIMAL(10,3)` |  | Quantity moved; for tagged tools usually 1. |
| `from_location_id` | `UUID` | FK | Source warehouse/site. References [storage_locations](storage_locations.md). |
| `to_location_id` | `UUID` | FK | Destination warehouse/site. References [storage_locations](storage_locations.md). |
| `approval_id` | `UUID` | FK | Approval that authorized issue/transfer, when required. References [approvals](approvals.md). |
| `reference_type` | `VARCHAR(30)` |  | Business source such as purchase, daily_report, inventory_request, tool_transfer, adjustment. |
| `reference_id` | `UUID` |  | Identifier of the source record. Polymorphic by `reference_type`. |
| `performed_by` | `UUID` | FK | User who recorded the movement. References [users](users.md). |
| `notes` | `TEXT` |  | Operational explanation. |
| `created_at` | `TIMESTAMPTZ` |  | Movement timestamp. |

## Relations

- Belongs to [inventory_items](inventory_items.md).
- Optionally belongs to [inventory_assets](inventory_assets.md).
- Uses [storage_locations](storage_locations.md) as source and/or destination.
- May be authorized by [approvals](approvals.md).
- Recorded by [users](users.md).
- Updates [inventory_location_stock](inventory_location_stock.md) and current location on [inventory_assets](inventory_assets.md).

## Indexes

- `idx_inventory_movements_item` on `item_id`.
- `idx_inventory_movements_asset` on `asset_id`.
- `idx_inventory_movements_date` on `created_at DESC`.
