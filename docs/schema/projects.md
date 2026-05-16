# `projects`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `name` | `VARCHAR(200)` | No | `` |  |
| `code` | `VARCHAR(20)` | No | `` |  |
| `location` | `TEXT` | Yes | `` |  |
| `description` | `TEXT` | Yes | `` |  |
| `scope_of_work` | `TEXT` | No | `` |  |
| `status` | `VARCHAR(30)` | No | `'planning'` |  |
| `budget_amount` | `NUMERIC(15, 2)` | Yes | `` |  |
| `start_date` | `DATE` | Yes | `` |  |
| `target_end_date` | `DATE` | No | `` |  |
| `actual_end_date` | `DATE` | Yes | `` |  |
| `client_name` | `VARCHAR(200)` | Yes | `` |  |
| `contract_number` | `VARCHAR(50)` | Yes | `` |  |
| `progress_percentage` | `NUMERIC(5, 2)` | No | `0` |  |
| `created_by` | `UUID` | Yes | `` | users.id |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `created_by` | `users.id` |

## Referenced By

| Source | Target |
|---|---|
| `approvals.project_id` | `projects.id` |
| `boq_items.project_id` | `projects.id` |
| `daily_reports.project_id` | `projects.id` |
| `documents.project_id` | `projects.id` |
| `inventory_movements.project_id` | `projects.id` |
| `invoices.project_id` | `projects.id` |
| `material_requests.project_id` | `projects.id` |
| `project_members.project_id` | `projects.id` |
| `project_milestones.project_id` | `projects.id` |
| `storage_locations.project_id` | `projects.id` |
| `supervisor_updates.project_id` | `projects.id` |
