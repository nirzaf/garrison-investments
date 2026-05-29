# boq_items

Defined in `backend/app/models/boq_item.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `milestone_id` | UUID | NULL | — | project_milestones.id | — |
| `item_code` | String(50) | NOT NULL | — | — | — |
| `description` | Text | NOT NULL | — | — | — |
| `discipline` | String(50) | NULL | — | — | — |
| `phase` | String(100) | NULL | — | — | — |
| `unit` | String(20) | NOT NULL | — | — | — |
| `planned_quantity` | Numeric(14, 3) | NOT NULL | — | — | — |
| `approved_quantity` | Numeric(14, 3) | NOT NULL | 0 | — | — |
| `unit_rate` | Numeric(14, 2) | NOT NULL | — | — | — |
| `planned_amount` | Numeric(15, 2) | NOT NULL | — | — | — |
