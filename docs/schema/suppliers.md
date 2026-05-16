# `suppliers`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `name` | `VARCHAR(200)` | No | `` |  |
| `category` | `VARCHAR(80)` | No | `` |  |
| `rating` | `VARCHAR(20)` | No | `` |  |
| `payment_terms` | `VARCHAR(120)` | No | `` |  |
| `contact_person` | `VARCHAR(150)` | No | `` |  |
| `phone` | `VARCHAR(32)` | No | `` |  |
| `email` | `VARCHAR(255)` | No | `` |  |
| `address` | `TEXT` | No | `` |  |
| `tax_registration_number` | `VARCHAR(80)` | No | `` |  |
| `tds_certificate_number` | `VARCHAR(120)` | Yes | `` |  |
| `tds_expiry_date` | `DATE` | Yes | `` |  |
| `tds_document_key` | `VARCHAR(500)` | Yes | `` |  |
| `compliance_status` | `VARCHAR(30)` | No | `` |  |
| `is_active` | `BOOLEAN` | No | `true` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Referenced By

| Source | Target |
|---|---|
| `invoices.supplier_id` | `suppliers.id` |
