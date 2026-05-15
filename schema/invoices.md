# invoices

Stores supplier/customer invoice metadata for project-level accounts and cost visibility.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique invoice identifier. |
| `project_id` | `UUID` | FK | Costed project. References [projects](projects.md). |
| `supplier_id` | `UUID` | FK | Supplier issuing the invoice. References [suppliers](suppliers.md). |
| `document_id` | `UUID` | FK | Uploaded invoice file. References [documents](documents.md). |
| `invoice_number` | `VARCHAR(80)` |  | Supplier invoice number. |
| `invoice_date` | `DATE` |  | Invoice issue date. |
| `due_date` | `DATE` |  | Payment due date. |
| `currency` | `VARCHAR(3)` |  | Currency code, default `QAR`. |
| `subtotal_amount` | `DECIMAL(15,2)` |  | Invoice subtotal before tax/discount. |
| `tax_amount` | `DECIMAL(15,2)` |  | Tax amount. |
| `total_amount` | `DECIMAL(15,2)` |  | Total invoice amount. |
| `status` | `VARCHAR(30)` |  | `draft`, `accounts_review`, `pending_approval`, `approved`, `part_paid`, `paid`, `rejected`, `cancelled`. |
| `approval_id` | `UUID` | FK | Approval workflow. References [approvals](approvals.md). |
| `created_by` | `UUID` | FK | User who entered invoice. References [users](users.md). |
| `created_at` | `TIMESTAMPTZ` |  | Creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last update timestamp. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Belongs to [projects](projects.md) and [suppliers](suppliers.md).
- Can attach a file through [documents](documents.md).
- Can be authorized by [approvals](approvals.md).
- Has [payments](payments.md).
- Created by [users](users.md).

## Indexes

- `idx_invoices_project` on `project_id`.
- `idx_invoices_supplier` on `supplier_id`.
- `idx_invoices_status` on `status` where `deleted_at IS NULL`.
- Intended unique key: `(supplier_id, invoice_number)` where `deleted_at IS NULL`.
