# report_equipment

Stores equipment usage lines for a daily report.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique equipment line identifier. |
| `report_id` | `UUID` | FK | Parent report. References [daily_reports](daily_reports.md). |
| `equipment_name` | `VARCHAR(100)` |  | Equipment name entered or selected by site staff. |
| `quantity` | `INT` |  | Number of units used. |
| `hours_used` | `DECIMAL(5,1)` |  | Total operating hours. |
| `status` | `VARCHAR(20)` |  | Operational status note. |
| `notes` | `TEXT` |  | Optional details. |

## Relations

- Belongs to [daily_reports](daily_reports.md).
- May correspond to tagged tools/assets in [inventory_assets](inventory_assets.md), but this table keeps report evidence independent.

## Indexes

- `idx_equipment_report` on `report_id`.
