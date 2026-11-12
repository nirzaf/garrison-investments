# invoices

Supplier invoices linked to projects, with amounts, approval state, and payment status.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/finance.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `invoice_number` | `varchar(80)` | No | — |
| `project_id` | `uuid` | No | — |
| `supplier_id` | `uuid` | Yes | — |
| `invoice_date` | `date` | No | — |
| `due_date` | `date` | No | — |
| `amount` | `numeric(14, 2)` | No | — |
| `tax_amount` | `numeric(14, 2)` | No | `0` |
| `total_amount` | `numeric(14, 2)` | No | — |
| `status` | `varchar(30)` | No | `'draft'` |
| `payment_status` | `varchar(30)` | No | `'unpaid'` |
| `attachment_key` | `varchar(500)` | Yes | — |
| `created_by` | `uuid` | Yes | — |
| `approved_by` | `uuid` | Yes | — |
| `approved_at` | `timestamptz` | Yes | — |
| `notes` | `text` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |
| `revision` | `integer` | No | `1` |

Invoice decisions, corrections, attachment changes, and payments advance the revision while holding the invoice row lock. Older invoice status and notes requests may omit a revision. New correction fields require it.

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_invoices` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_invoices_approved_by_users` | `(approved_by)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_invoices_created_by_users` | `(created_by)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_invoices_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `CASCADE` |
| `fk_invoices_supplier_id_suppliers` | `(supplier_id)` | [`suppliers(id)`](suppliers.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_invoices_project` | `btree` | `project_id, status` | No | — |
| `idx_invoices_supplier` | `btree` | `supplier_id` | No | — |
| `uq_invoices_number` | `btree` | `invoice_number` | Yes | — |
