# documents

Stores document metadata and active document state. Files live in object storage.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique document identifier. |
| `title` | `VARCHAR(255)` |  | Document title/search text. |
| `document_type` | `VARCHAR(30)` |  | `drawing`, `boq`, `contract`, `wir`, `invoice`, or `other`. |
| `project_id` | `UUID` | FK | Optional project. References [projects](projects.md). |
| `storage_path` | `VARCHAR(500)` |  | Object storage key for current file. |
| `mime_type` | `VARCHAR(50)` |  | File MIME type. |
| `size_bytes` | `BIGINT` |  | File size. |
| `version` | `INT` |  | Current document version number. |
| `status` | `VARCHAR(20)` |  | `draft`, `active`, `superseded`, or `archived`. |
| `uploaded_by` | `UUID` | FK | Uploader. References [users](users.md). |
| `created_at` | `TIMESTAMPTZ` |  | Creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` |  | Last metadata update. |
| `deleted_at` | `TIMESTAMPTZ` |  | Soft delete marker. |

## Relations

- Optionally belongs to [projects](projects.md).
- Uploaded by [users](users.md).
- Has [document_versions](document_versions.md).
- Can be routed through [approvals](approvals.md).
- May have [photos](photos.md) if preview/attachment evidence is needed.

## Indexes

- `idx_documents_project` on `project_id` where not deleted.
- `idx_documents_type` on `document_type` where not deleted.
- `idx_documents_search` GIN on `to_tsvector('english', title)`.
