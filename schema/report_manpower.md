# report_manpower

Stores manpower lines for a daily report.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique manpower line identifier. |
| `report_id` | `UUID` | FK | Parent report. References [daily_reports](daily_reports.md). |
| `labor_type` | `VARCHAR(50)` |  | Skilled, unskilled, operator, technician, or similar. |
| `trade` | `VARCHAR(100)` |  | Mason, carpenter, electrician, plumber, etc. |
| `count` | `INT` |  | Number of workers; must be greater than zero. |
| `hours_worked` | `DECIMAL(4,1)` |  | Regular hours worked. |
| `overtime_hours` | `DECIMAL(4,1)` |  | Overtime hours. |
| `notes` | `TEXT` |  | Optional context. |

## Relations

- Belongs to [daily_reports](daily_reports.md).
- Feeds accounts/manpower cost reporting.

## Indexes

- `idx_manpower_report` on `report_id`.
