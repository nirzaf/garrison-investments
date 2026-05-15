# notifications

Stores in-app notification records and links them to the user who must act or be informed.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique notification identifier. |
| `user_id` | `UUID` | FK | Recipient. References [users](users.md). |
| `title` | `VARCHAR(200)` |  | Short notification title. |
| `body` | `TEXT` |  | Detailed message text. |
| `notification_type` | `VARCHAR(30)` |  | approval, alert, reminder, announcement, or similar. |
| `reference_type` | `VARCHAR(30)` |  | Optional source type. |
| `reference_id` | `UUID` |  | Optional source id. Polymorphic by `reference_type`. |
| `is_read` | `BOOLEAN` |  | Read/unread state. |
| `created_at` | `TIMESTAMPTZ` |  | Notification timestamp. |

## Relations

- Belongs to [users](users.md).
- Can point to [approvals](approvals.md), [daily_reports](daily_reports.md), [documents](documents.md), [inventory_items](inventory_items.md), or [invoices](invoices.md) through `reference_type/reference_id`.

## Indexes

- `idx_notifications_user` on `(user_id, is_read, created_at DESC)`.
