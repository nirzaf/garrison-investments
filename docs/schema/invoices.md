# invoices

Defined in `backend/app/models/finance.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `amount` | Numeric(14, 2) | NOT NULL | — | — | — |
| `approved_at` | TimestampTZ | NULL | — | — | — |
| `approved_by` | UUID | NULL | — | users.id | — |
| `attachment_key` | String(500) | NULL | — | — | — |
| `created_by` | UUID | NULL | — | users.id | — |
| `due_date` | Date | NOT NULL | — | — | — |
| `invoice_date` | Date | NOT NULL | — | — | — |
| `invoice_number` | String(80) | NOT NULL | — | — | — |
| `notes` | Text | NULL | — | — | — |
| `payment_status` | String(30) | NOT NULL | unpaid | — | — |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `status` | String(30) | NOT NULL | draft | — | — |
| `supplier_id` | UUID | NULL | — | suppliers.id | — |
| `tax_amount` | Numeric(14, 2) | NOT NULL | 0 | — | — |
| `total_amount` | Numeric(14, 2) | NOT NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

