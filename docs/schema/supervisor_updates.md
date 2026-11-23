# supervisor_updates

Supervisor site updates with attendance, overtime, progress, and verification metadata.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/supervisor_update.py)

An engineer’s report submission verifies an eligible update and binds it to that report. A rejected report keeps its bound evidence. The migration leaves legacy ownership unset when more than one historical report could have verified the update.

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `project_id` | `uuid` | No | — |
| `supervisor_id` | `uuid` | No | — |
| `update_date` | `date` | No | — |
| `day_type` | `varchar(20)` | No | `'weekday'` |
| `work_location` | `varchar(255)` | No | — |
| `attendance_count` | `integer` | No | — |
| `overtime_hours` | `numeric(5, 2)` | No | `0` |
| `progress_notes` | `text` | No | — |
| `activity_scope` | `text` | Yes | — |
| `remaining_work` | `text` | Yes | — |
| `completed_area` | `varchar(255)` | Yes | — |
| `completed_quantity` | `numeric(14, 3)` | Yes | — |
| `quantity_unit` | `varchar(30)` | Yes | — |
| `progress_percentage` | `numeric(5, 2)` | Yes | — |
| `revision` | `integer` | No | `1` |
| `submission_revision` | `integer` | Yes | — |
| `delay_notes` | `text` | Yes | — |
| `required_notes` | `text` | No | — |
| `attachment_refs` | `jsonb` | No | — |
| `status` | `varchar(20)` | No | `'draft'` |
| `submitted_at` | `timestamptz` | Yes | — |
| `verified_by` | `uuid` | Yes | — |
| `verified_at` | `timestamptz` | Yes | — |
| `verified_report_id` | `uuid` | Yes | — |
| `verification_notes` | `text` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_supervisor_updates` | `PRIMARY KEY (id)` |
| `ck_supervisor_updates_status_valid` | `CHECK (status IN ('draft', 'submitted', 'pending_qs', 'pending_engineer', 'returned', 'verified', 'rejected'))` |
| `ck_supervisor_updates_day_type_valid` | `CHECK ((day_type IN ('weekday', 'friday', 'public_holiday')))` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_supervisor_updates_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `CASCADE` |
| `fk_supervisor_updates_supervisor_id_users` | `(supervisor_id)` | [`users(id)`](users.md) | `CASCADE` |
| `fk_supervisor_updates_verified_report_id` | `(verified_report_id)` | [`daily_reports(id)`](daily_reports.md) | `RESTRICT` |
| `fk_supervisor_updates_verified_by_users` | `(verified_by)` | [`users(id)`](users.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_supervisor_updates_project_date` | `btree` | `project_id, update_date` | No | `(deleted_at IS NULL)` |
| `idx_supervisor_updates_supervisor` | `btree` | `supervisor_id` | No | `(deleted_at IS NULL)` |
| `ix_supervisor_updates_verified_report_id` | `btree` | `verified_report_id` | No | — |
| `uq_supervisor_update_draft_owner` | `btree` | `project_id, update_date, supervisor_id` | Yes | `((deleted_at IS NULL) AND (status IN ('draft', 'submitted')))` |

## Submitted progress

`supervisor_update_submissions` is keyed by `(update_id, submission_revision)`.
It stores the submitted fields, photo IDs, assigned engineer and optional QS,
and their independent decisions, comments and timestamps. The parent
`revision` changes on edits and decisions. Older verified links and timestamps
are retained without assigning a current submission revision.
[Migration 104](../../backend/alembic/versions/202605310104_supervisor_progress_reviews.py)
