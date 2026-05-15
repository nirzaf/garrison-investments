# payments

Stores payment records against approved invoices.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique payment identifier. |
| `invoice_id` | `UUID` | FK | Invoice being paid. References [invoices](invoices.md). |
| `project_id` | `UUID` | FK | Project cost context. References [projects](projects.md). |
| `payment_reference` | `VARCHAR(100)` |  | Bank transfer, cheque, or internal payment reference. |
| `payment_date` | `DATE` |  | Actual or planned payment date. |
| `amount` | `DECIMAL(15,2)` |  | Payment amount. |
| `currency` | `VARCHAR(3)` |  | Currency code, default `QAR`. |
| `payment_method` | `VARCHAR(30)` |  | Bank transfer, cheque, cash, card, or other approved method. |
| `status` | `VARCHAR(30)` |  | `scheduled`, `paid`, `failed`, `cancelled`. |
| `approval_id` | `UUID` | FK | Payment approval, if required. References [approvals](approvals.md). |
| `created_by` | `UUID` | FK | User who entered payment. References [users](users.md). |
| `created_at` | `TIMESTAMPTZ` |  | Creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last update timestamp. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Pays [invoices](invoices.md).
- Belongs to [projects](projects.md).
- May be authorized by [approvals](approvals.md).
- Created by [users](users.md).

## Indexes

- `idx_payments_invoice` on `invoice_id`.
- `idx_payments_project` on `project_id`.
- `idx_payments_status` on `status` where `deleted_at IS NULL`.
