# `project_milestones`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `name` | `VARCHAR(150)` | No | `` |  |
| `discipline` | `VARCHAR(50)` | Yes | `` |  |
| `planned_start_date` | `DATE` | Yes | `` |  |
| `planned_end_date` | `DATE` | Yes | `` |  |
| `actual_start_date` | `DATE` | Yes | `` |  |
| `actual_end_date` | `DATE` | Yes | `` |  |
| `progress_percentage` | `NUMERIC(5, 2)` | No | `0` |  |
| `status` | `VARCHAR(30)` | No | `'not_started'` |  |
| `sort_order` | `INTEGER` | No | `0` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `project_id` | `projects.id` |

## Referenced By

| Source | Target |
|---|---|
| `boq_items.milestone_id` | `project_milestones.id` |
