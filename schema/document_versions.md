# document_versions

Stores immutable file versions for a document.

## Columns

| Column | Type | Key | Explanation |
|---|---|---|---|
| `id` | `UUID` | PK | Unique version identifier. |
| `document_id` | `UUID` | FK | Parent document. References [documents](documents.md). |
| `version` | `INT` |  | Version number under the parent document. |
| `storage_path` | `VARCHAR(500)` |  | Object storage key for this version. |
| `size_bytes` | `BIGINT` |  | File size. |
| `change_notes` | `TEXT` |  | Description of what changed in this version. |
| `uploaded_by` | `UUID` | FK | Uploader. References [users](users.md). |
| `created_at` | `TIMESTAMPTZ` |  | Upload timestamp. |

## Relations

- Belongs to [documents](documents.md).
- Uploaded by [users](users.md).

## Constraints and Indexes

- Unique version per document: `(document_id, version)`.
