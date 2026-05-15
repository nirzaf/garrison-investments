# suppliers

Stores supplier master data for inventory purchasing, invoices, and compliance attachments.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique supplier identifier. |
| `name` | `VARCHAR(200)` |  | Supplier company name. |
| `contact_person` | `VARCHAR(150)` |  | Main contact. |
| `phone` | `VARCHAR(20)` |  | Contact phone. |
| `email` | `VARCHAR(255)` |  | Contact email. |
| `address` | `TEXT` |  | Supplier address. |
| `gst_number` | `VARCHAR(20)` |  | Tax/commercial registration reference, if used. |
| `is_active` | `BOOLEAN` |  | Whether supplier can be selected in new records. |
| `created_at` | `TIMESTAMPTZ` |  | Creation timestamp. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Supplies [inventory_items](inventory_items.md).
- Appears on [invoices](invoices.md).
- Compliance files can be stored through [documents](documents.md) or [photos](photos.md) metadata where appropriate.

## Indexes

- Intended `idx_suppliers_active` on `is_active` where `deleted_at IS NULL`.
