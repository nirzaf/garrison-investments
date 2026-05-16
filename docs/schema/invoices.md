# `invoices`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `invoice_number` | `VARCHAR(80)` | No | `` |  |
| `project_id` | `UUID` | No | `` | projects.id |
| `supplier_id` | `UUID` | Yes | `` | suppliers.id |
| `invoice_date` | `DATE` | No | `` |  |
| `due_date` | `DATE` | No | `` |  |
| `amount` | `NUMERIC(14, 2)` | No | `` |  |
| `tax_amount` | `NUMERIC(14, 2)` | No | `0` |  |
| `total_amount` | `NUMERIC(14, 2)` | No | `` |  |
| `status` | `VARCHAR(30)` | No | `'draft'` |  |
| `payment_status` | `VARCHAR(30)` | No | `'unpaid'` |  |
| `attachment_key` | `VARCHAR(500)` | Yes | `` |  |
| `created_by` | `UUID` | Yes | `` | users.id |
| `approved_by` | `UUID` | Yes | `` | users.id |
| `approved_at` | `DATETIME` | Yes | `` |  |
| `notes` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `project_id` | `projects.id` |
| `supplier_id` | `suppliers.id` |
| `created_by` | `users.id` |
| `approved_by` | `users.id` |

## Referenced By

| Source | Target |
|---|---|
| `payments.invoice_id` | `invoices.id` |
