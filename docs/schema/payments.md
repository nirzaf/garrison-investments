# payments

Defined in `backend/app/models/finance.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `amount` | Numeric(14, 2) | NOT NULL | — | — | — |
| `invoice_id` | UUID | NOT NULL | — | invoices.id | — |
| `method` | String(50) | NOT NULL | — | — | — |
| `notes` | Text | NULL | — | — | — |
| `payment_date` | Date | NOT NULL | — | — | — |
| `recorded_by` | UUID | NULL | — | users.id | — |
| `reference_number` | String(100) | NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

