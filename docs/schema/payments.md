# payments

Recorded invoice payments with dates, methods, references, and actors.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/finance.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `invoice_id` | `uuid` | No | — |
| `payment_date` | `date` | No | — |
| `amount` | `numeric(14, 2)` | No | — |
| `method` | `varchar(50)` | No | — |
| `reference_number` | `varchar(100)` | Yes | — |
| `recorded_by` | `uuid` | Yes | — |
| `notes` | `text` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_payments` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_payments_invoice_id_invoices` | `(invoice_id)` | [`invoices(id)`](invoices.md) | `CASCADE` |
| `fk_payments_recorded_by_users` | `(recorded_by)` | [`users(id)`](users.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_payments_invoice` | `btree` | `invoice_id` | No | — |
