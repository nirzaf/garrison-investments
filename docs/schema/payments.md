# payments

Defined in `backend/app/models/finance.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `invoice_id` | UUID | NOT NULL | — | invoices.id | — |
| `payment_date` | Date | NOT NULL | — | — | — |
| `amount` | Numeric(14, 2) | NOT NULL | — | — | — |
| `method` | String(50) | NOT NULL | — | — | — |
| `reference_number` | String(100) | NULL | — | — | — |
| `recorded_by` | UUID | NULL | — | users.id | — |
| `notes` | Text | NULL | — | — | — |
