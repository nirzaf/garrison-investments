# daily_reports

Stores the official daily site report after supervisor capture, engineer verification, and approval workflow.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique daily report identifier. |
| `project_id` | `UUID` | FK | Project being reported. References [projects](projects.md). |
| `report_date` | `DATE` |  | Site work date. |
| `submitted_by` | `UUID` | FK | User who submits the report. References [users](users.md). |
| `weather_condition` | `VARCHAR(30)` |  | Weather summary. |
| `temperature` | `DECIMAL(4,1)` |  | Temperature value. |
| `work_completed` | `TEXT` |  | Required daily work summary. |
| `progress_percentage` | `DECIMAL(5,2)` |  | Reported progress contribution. |
| `issues_delays` | `TEXT` |  | Delays, blockers, or site issues. |
| `next_day_plan` | `TEXT` |  | Planned next-day work. |
| `notes` | `TEXT` |  | Additional remarks. |
| `extra_fields` | `JSONB` |  | Flexible per-project form fields. |
| `status` | `VARCHAR(20)` |  | `draft`, `submitted`, `approved`, or `rejected`. |
| `approved_by` | `UUID` | FK | Approver user. References [users](users.md). |
| `approved_at` | `TIMESTAMPTZ` |  | Approval timestamp. |
| `rejection_reason` | `TEXT` |  | Required when rejected. |
| `is_synced` | `BOOLEAN` |  | Indicates whether an offline/mobile draft has synced. |
| `local_created_at` | `TIMESTAMPTZ` |  | Device-side creation timestamp for offline drafts. |
| `created_at` | `TIMESTAMPTZ` |  | Creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last update timestamp. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Belongs to [projects](projects.md).
- Submitted and approved by [users](users.md).
- Has [report_manpower](report_manpower.md), [report_equipment](report_equipment.md), [report_material_consumption](report_material_consumption.md), [photos](photos.md), and [approvals](approvals.md).
- Can generate [documents](documents.md) or exported PDF metadata in document storage.

## Constraints and Indexes

- Intended uniqueness: one active report per `(project_id, report_date)`.
- `idx_reports_project` on `project_id` where `deleted_at IS NULL`.
- `idx_reports_date` on `report_date DESC`.
- `idx_reports_status` on `status`.
- `idx_reports_extra` GIN on `extra_fields`.
