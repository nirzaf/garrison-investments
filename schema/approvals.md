# approvals

Stores generic approval workflow records for reports, documents, inventory movements, invoices, and other controlled actions.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique approval record identifier. |
| `request_type` | `VARCHAR(30)` |  | Source type such as daily_report, inventory_request, document, invoice, payment. |
| `request_id` | `UUID` |  | Source record id. Polymorphic by `request_type`. |
| `requested_by` | `UUID` | FK | Requesting user. References [users](users.md). |
| `approver_id` | `UUID` | FK | Assigned approver. References [users](users.md). |
| `approval_level` | `INT` |  | Level in multi-step route. |
| `status` | `VARCHAR(20)` |  | `pending`, `approved`, `rejected`, or `cancelled`. |
| `comments` | `TEXT` |  | Approval/rejection comments. Required on rejection. |
| `decided_at` | `TIMESTAMPTZ` |  | Decision timestamp. |
| `created_at` | `TIMESTAMPTZ` |  | Request timestamp. |

## Relations

- Requested and decided by [users](users.md).
- Authorizes [daily_reports](daily_reports.md), [documents](documents.md), [inventory_movements](inventory_movements.md), [invoices](invoices.md), or [payments](payments.md) depending on `request_type`.

## Indexes

- `idx_approvals_approver` on `(approver_id, status)`.
- `idx_approvals_request` on `(request_type, request_id)`.
