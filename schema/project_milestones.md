# project_milestones

Stores project phases, milestone dates, and Gantt-style progress checkpoints.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique milestone identifier. |
| `project_id` | `UUID` | FK | Parent project. References [projects](projects.md). |
| `name` | `VARCHAR(150)` |  | Milestone or phase name. |
| `discipline` | `VARCHAR(50)` |  | Discipline such as civil, MEP, fit-out, or procurement. |
| `planned_start_date` | `DATE` |  | Planned start. |
| `planned_end_date` | `DATE` |  | Planned finish. |
| `actual_start_date` | `DATE` |  | Actual start when work begins. |
| `actual_end_date` | `DATE` |  | Actual finish when complete. |
| `progress_percentage` | `DECIMAL(5,2)` |  | Progress for this milestone. |
| `status` | `VARCHAR(30)` |  | `not_started`, `in_progress`, `delayed`, `completed`, or `blocked`. |
| `sort_order` | `INT` |  | Display order in project timeline. |
| `created_at` | `TIMESTAMPTZ` |  | Creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last update timestamp. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Belongs to [projects](projects.md).
- Progress can be compared with approved [daily_reports](daily_reports.md) and [boq_items](boq_items.md).

## Indexes

- `idx_project_milestones_project` on `project_id, sort_order`.
- `idx_project_milestones_status` on `status` where `deleted_at IS NULL`.
