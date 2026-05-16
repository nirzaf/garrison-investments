# `payments`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `invoice_id` | `UUID` | No | `` | invoices.id |
| `payment_date` | `DATE` | No | `` |  |
| `amount` | `NUMERIC(14, 2)` | No | `` |  |
| `method` | `VARCHAR(50)` | No | `` |  |
| `reference_number` | `VARCHAR(100)` | Yes | `` |  |
| `recorded_by` | `UUID` | Yes | `` | users.id |
| `notes` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `invoice_id` | `invoices.id` |
| `recorded_by` | `users.id` |
