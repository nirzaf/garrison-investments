# photos

Stores metadata for uploaded photos while binary files live in object storage.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique photo identifier. |
| `filename` | `VARCHAR(255)` |  | Stored/generated filename. |
| `original_name` | `VARCHAR(255)` |  | Original uploaded filename. |
| `storage_path` | `VARCHAR(500)` |  | Object storage key for original file. |
| `thumbnail_path` | `VARCHAR(500)` |  | Object storage key for thumbnail. |
| `mime_type` | `VARCHAR(50)` |  | File MIME type. |
| `size_bytes` | `BIGINT` |  | File size. |
| `width` | `INT` |  | Image width in pixels. |
| `height` | `INT` |  | Image height in pixels. |
| `entity_type` | `VARCHAR(30)` |  | Polymorphic owner: daily_report, project, inventory_item, document. |
| `entity_id` | `UUID` |  | Owner record id. Polymorphic by `entity_type`. |
| `caption` | `TEXT` |  | User-entered caption. |
| `taken_at` | `TIMESTAMPTZ` |  | Device/camera capture timestamp. |
| `uploaded_by` | `UUID` | FK | Uploader. References [users](users.md). |
| `created_at` | `TIMESTAMPTZ` |  | Upload timestamp. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker for recovery window. |

## Relations

- Uploaded by [users](users.md).
- Polymorphic relation to [daily_reports](daily_reports.md), [projects](projects.md), [inventory_items](inventory_items.md), or [documents](documents.md).

## Indexes

- `idx_photos_entity` on `(entity_type, entity_id)` where not deleted.
- `idx_photos_date` on `created_at DESC`.
