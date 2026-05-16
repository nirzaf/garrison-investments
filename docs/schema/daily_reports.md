# `daily_reports`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `engineer_id` | `UUID` | No | `` | users.id |
| `report_number` | `VARCHAR(60)` | Yes | `` |  |
| `report_date` | `DATE` | No | `` |  |
| `work_location` | `VARCHAR(255)` | No | `` |  |
| `manpower_total` | `INTEGER` | No | `0` |  |
| `overtime_hours` | `NUMERIC(5, 2)` | No | `0` |  |
| `work_completed` | `TEXT` | No | `` |  |
| `progress_percentage` | `NUMERIC(5, 2)` | No | `` |  |
| `safety_incidents` | `INTEGER` | No | `0` |  |
| `safety_notes` | `TEXT` | Yes | `` |  |
| `wir_status` | `VARCHAR(50)` | No | `` |  |
| `inspection_status` | `VARCHAR(50)` | No | `` |  |
| `delay_notes` | `TEXT` | Yes | `` |  |
| `next_day_plan` | `TEXT` | No | `` |  |
| `supervisor_update_ids` | `JSONB` | No | `` |  |
| `photo_refs` | `JSONB` | No | `` |  |
| `attachment_refs` | `JSONB` | No | `` |  |
| `status` | `VARCHAR(20)` | No | `'draft'` |  |
| `submitted_at` | `DATETIME` | Yes | `` |  |
| `approved_by` | `UUID` | Yes | `` | users.id |
| `approved_at` | `DATETIME` | Yes | `` |  |
| `rejection_comments` | `TEXT` | Yes | `` |  |
| `extra_fields` | `JSONB` | No | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `project_id` | `projects.id` |
| `engineer_id` | `users.id` |
| `approved_by` | `users.id` |

## Referenced By

| Source | Target |
|---|---|
| `daily_report_approval_history.report_id` | `daily_reports.id` |
| `report_equipment.report_id` | `daily_reports.id` |
| `report_exports.report_id` | `daily_reports.id` |
| `report_manpower.report_id` | `daily_reports.id` |
| `report_material_consumption.report_id` | `daily_reports.id` |
