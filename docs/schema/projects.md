# projects

Stores construction project master data and the anchor record for reports, BOQ, documents, inventory site stores, and finance.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique project identifier. |
| `name` | `VARCHAR(200)` |  | Project name shown to all roles. |
| `code` | `VARCHAR(20)` | Unique | Short project code used in report/document numbering. |
| `location` | `TEXT` |  | Physical project location. |
| `description` | `TEXT` |  | Optional project summary. |
| `status` | `VARCHAR(30)` |  | `planning`, `active`, `on_hold`, `completed`, or `cancelled`. |
| `budget_amount` | `DECIMAL(15,2)` |  | Approved budget baseline. |
| `start_date` | `DATE` |  | Planned start date. |
| `target_end_date` | `DATE` |  | Planned completion date. |
| `actual_end_date` | `DATE` |  | Actual completion date once closed. |
| `client_name` | `VARCHAR(200)` |  | Client or customer name. |
| `contract_number` | `VARCHAR(50)` |  | Contract reference. |
| `progress_percentage` | `DECIMAL(5,2)` |  | Current project progress, calculated from approved quantities/milestones. |
| `created_by` | `UUID` | FK | User who created the project. References [users](users.md). |
| `created_at` | `TIMESTAMPTZ` |  | Project creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last project metadata update. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Created by [users](users.md).
- Has many [project_members](project_members.md), [project_milestones](project_milestones.md), and [boq_items](boq_items.md).
- Has many [daily_reports](daily_reports.md), [documents](documents.md), [invoices](invoices.md), and optional site [storage_locations](storage_locations.md).
- Can be linked to serialized [inventory_assets](inventory_assets.md) currently assigned to a project site.

## Indexes

- `idx_projects_status` on `status` where `deleted_at IS NULL`.
- `idx_projects_code` on `code`.
