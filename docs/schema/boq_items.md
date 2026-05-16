# `boq_items`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `milestone_id` | `UUID` | Yes | `` | project_milestones.id |
| `item_code` | `VARCHAR(50)` | No | `` |  |
| `description` | `TEXT` | No | `` |  |
| `discipline` | `VARCHAR(50)` | Yes | `` |  |
| `phase` | `VARCHAR(100)` | Yes | `` |  |
| `unit` | `VARCHAR(20)` | No | `` |  |
| `planned_quantity` | `NUMERIC(14, 3)` | No | `` |  |
| `approved_quantity` | `NUMERIC(14, 3)` | No | `0` |  |
| `unit_rate` | `NUMERIC(14, 2)` | No | `` |  |
| `planned_amount` | `NUMERIC(15, 2)` | No | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `project_id` | `projects.id` |
| `milestone_id` | `project_milestones.id` |

## Referenced By

| Source | Target |
|---|---|
| `report_material_consumption.boq_item_id` | `boq_items.id` |
