# suppliers

Supplier contact, commercial terms, and tax compliance information.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/supplier.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `name` | `varchar(200)` | No | — |
| `category` | `varchar(80)` | No | — |
| `rating` | `varchar(20)` | No | — |
| `payment_terms` | `varchar(120)` | No | — |
| `contact_person` | `varchar(150)` | No | — |
| `phone` | `varchar(32)` | No | — |
| `email` | `varchar(255)` | No | — |
| `address` | `text` | No | — |
| `tax_registration_number` | `varchar(80)` | No | — |
| `tds_certificate_number` | `varchar(120)` | Yes | — |
| `tds_expiry_date` | `date` | Yes | — |
| `tds_document_key` | `varchar(500)` | Yes | — |
| `compliance_status` | `varchar(30)` | No | — |
| `is_active` | `boolean` | No | `true` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |
| `revision` | `integer` | No | `1` |

Supplier edits, deactivation, and TDS uploads advance the revision. Deactivation sets `is_active` to false and keeps the row and TDS reference accessible to supplier managers. Invoices can still display the supplier on historical records. Previously soft-deleted suppliers retain their existing stored state.

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_suppliers` | `PRIMARY KEY (id)` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_suppliers_active` | `btree` | `is_active, name` | No | — |
| `idx_suppliers_compliance` | `btree` | `compliance_status` | No | — |
