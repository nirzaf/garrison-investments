# boq_items

Defined in `backend/app/models/boq_item.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `approved_quantity` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `description` | Text | NOT NULL | — | — | — |
| `discipline` | String(50) | NULL | — | — | — |
| `item_code` | String(50) | NOT NULL | — | — | — |
| `milestone_id` | UUID | NULL | — | project_milestones.id | — |
| `phase` | String(100) | NULL | — | — | — |
| `planned_amount` | Numeric(15, 2) | NOT NULL | — | — | — |
| `planned_quantity` | Numeric(14, 3) | NOT NULL | — | — | — |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `unit` | String(20) | NOT NULL | — | — | — |
| `unit_rate` | Numeric(14, 2) | NOT NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

