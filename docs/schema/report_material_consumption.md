# report_material_consumption

Stores materials consumed in a daily report and links approved site usage back to inventory.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique consumption line identifier. |
| `report_id` | `UUID` | FK | Parent daily report. References [daily_reports](daily_reports.md). |
| `inventory_item_id` | `UUID` | FK | Optional inventory item. References [inventory_items](inventory_items.md). |
| `material_name` | `VARCHAR(150)` |  | Material name snapshot retained even if catalog changes. |
| `quantity` | `DECIMAL(10,3)` |  | Consumed quantity. |
| `unit` | `VARCHAR(20)` |  | Quantity unit. |
| `wastage` | `DECIMAL(10,3)` |  | Wasted quantity, if any. |
| `notes` | `TEXT` |  | Optional consumption notes. |

## Relations

- Belongs to [daily_reports](daily_reports.md).
- Optionally references [inventory_items](inventory_items.md).
- Approved consumption can generate [inventory_movements](inventory_movements.md) of type `consume`.

## Indexes

- `idx_consumption_report` on `report_id`.
