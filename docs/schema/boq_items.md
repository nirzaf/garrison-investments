# boq_items

Project bill of quantities, including planned and approved quantities, units, and rates.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/boq_item.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `project_id` | `uuid` | No | — |
| `milestone_id` | `uuid` | Yes | — |
| `item_code` | `varchar(50)` | No | — |
| `description` | `text` | No | — |
| `discipline` | `varchar(50)` | Yes | — |
| `phase` | `varchar(100)` | Yes | — |
| `unit` | `varchar(20)` | No | — |
| `planned_quantity` | `numeric(14, 3)` | No | — |
| `approved_quantity` | `numeric(14, 3)` | No | `0` |
| `unit_rate` | `numeric(14, 2)` | No | — |
| `planned_amount` | `numeric(15, 2)` | No | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_boq_items` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_boq_items_milestone_id_project_milestones` | `(milestone_id)` | [`project_milestones(id)`](project_milestones.md) | `SET NULL` |
| `fk_boq_items_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_boq_items_milestone` | `btree` | `milestone_id` | No | — |
| `idx_boq_items_project` | `btree` | `project_id` | No | — |
| `uq_boq_items_project_code_active` | `btree` | `project_id, item_code` | Yes | `(deleted_at IS NULL)` |
