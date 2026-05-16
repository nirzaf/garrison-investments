# boq_items

Stores project BOQ lines and approved quantity/value baselines used for progress and budget comparison.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique BOQ line identifier. |
| `project_id` | `UUID` | FK | Parent project. References [projects](projects.md). |
| `milestone_id` | `UUID` | FK | Optional linked milestone. References [project_milestones](project_milestones.md). |
| `item_code` | `VARCHAR(50)` |  | BOQ line or imported spreadsheet code. |
| `description` | `TEXT` |  | BOQ item description. |
| `discipline` | `VARCHAR(50)` |  | Work discipline or trade. |
| `unit` | `VARCHAR(20)` |  | Quantity unit. |
| `planned_quantity` | `DECIMAL(14,3)` |  | Contract quantity. |
| `approved_quantity` | `DECIMAL(14,3)` |  | Quantity approved through reports/WIRs. |
| `unit_rate` | `DECIMAL(14,2)` |  | Contract unit rate. |
| `planned_amount` | `DECIMAL(15,2)` |  | Planned quantity x unit rate. |
| `created_at` | `TIMESTAMPTZ` |  | Creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last update timestamp. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Belongs to [projects](projects.md).
- Optionally belongs to [project_milestones](project_milestones.md).
- Used by [daily_reports](daily_reports.md) and finance dashboards for progress and budget comparison.

## Indexes

- `idx_boq_items_project` on `project_id`.
- `idx_boq_items_milestone` on `milestone_id`.
- Unique intended key: `(project_id, item_code)` where `deleted_at IS NULL`.
