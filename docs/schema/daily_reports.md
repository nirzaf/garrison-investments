# daily_reports

Engineer-authored daily site reports, with workflow status, referenced updates, and approval metadata.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/daily_report.py)

The [report service](../../backend/app/services/report_service.py) assigns `report_number` on submission. The unique index applies once the number is present.

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `project_id` | `uuid` | No | — |
| `engineer_id` | `uuid` | No | — |
| `report_number` | `varchar(60)` | Yes | — |
| `report_date` | `date` | No | — |
| `work_location` | `varchar(255)` | No | — |
| `manpower_total` | `integer` | No | `0` |
| `overtime_hours` | `numeric(5, 2)` | No | `0` |
| `work_completed` | `text` | No | — |
| `progress_percentage` | `numeric(5, 2)` | No | — |
| `safety_incidents` | `integer` | No | `0` |
| `safety_notes` | `text` | Yes | — |
| `wir_status` | `varchar(50)` | No | — |
| `inspection_status` | `varchar(50)` | No | — |
| `delay_notes` | `text` | Yes | — |
| `next_day_plan` | `text` | No | — |
| `supervisor_update_ids` | `jsonb` | No | — |
| `photo_refs` | `jsonb` | No | — |
| `attachment_refs` | `jsonb` | No | — |
| `status` | `varchar(20)` | No | `'draft'` |
| `submitted_at` | `timestamptz` | Yes | — |
| `approved_by` | `uuid` | Yes | — |
| `approved_at` | `timestamptz` | Yes | — |
| `rejection_comments` | `text` | Yes | — |
| `extra_fields` | `jsonb` | No | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_daily_reports` | `PRIMARY KEY (id)` |
| `ck_daily_reports_ck_daily_reports_counts_valid` | `CHECK (((safety_incidents >= 0) AND (manpower_total >= 0)))` |
| `ck_daily_reports_ck_daily_reports_progress_valid` | `CHECK (((progress_percentage >= 0) AND (progress_percentage <= 100)))` |
| `ck_daily_reports_ck_daily_reports_status_valid` | `CHECK ((status IN ('draft', 'submitted', 'approved', 'rejected')))` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_daily_reports_approved_by_users` | `(approved_by)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_daily_reports_engineer_id_users` | `(engineer_id)` | [`users(id)`](users.md) | `CASCADE` |
| `fk_daily_reports_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_daily_reports_extra` | `gin` | `extra_fields` | No | — |
| `idx_daily_reports_project_date` | `btree` | `project_id, report_date DESC` | No | `(deleted_at IS NULL)` |
| `idx_daily_reports_status` | `btree` | `status` | No | — |
| `uq_daily_reports_report_number` | `btree` | `report_number` | Yes | `(report_number IS NOT NULL)` |
