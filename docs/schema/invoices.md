# invoices

Defined in `backend/app/models/finance.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `invoice_number` | String(80) | NOT NULL | — | — | — |
| `project_id` | UUID | NOT NULL | — | projects.id | — |
| `supplier_id` | UUID | NULL | — | suppliers.id | — |
| `invoice_date` | Date | NOT NULL | — | — | — |
| `due_date` | Date | NOT NULL | — | — | — |
| `amount` | Numeric(14, 2) | NOT NULL | — | — | — |
| `tax_amount` | Numeric(14, 2) | NOT NULL | 0 | — | — |
| `total_amount` | Numeric(14, 2) | NOT NULL | — | — | — |
| `status` | String(30) | NOT NULL | draft | — | — |
| `payment_status` | String(30) | NOT NULL | unpaid | — | — |
| `attachment_key` | String(500) | NULL | — | — | — |
| `created_by` | UUID | NULL | — | users.id | — |
| `approved_by` | UUID | NULL | — | users.id | — |
| `approved_at` | TimestampTZ | NULL | — | — | — |
| `notes` | Text | NULL | — | — | — |
