# `document_versions`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `document_id` | `UUID` | No | `` | documents.id |
| `version` | `INTEGER` | No | `` |  |
| `status` | `VARCHAR(20)` | No | `'pending_approval'` |  |
| `storage_path` | `VARCHAR(500)` | No | `` |  |
| `original_name` | `VARCHAR(255)` | No | `` |  |
| `mime_type` | `VARCHAR(80)` | No | `` |  |
| `size_bytes` | `BIGINT` | No | `` |  |
| `uploaded_by` | `UUID` | Yes | `` | users.id |
| `approved_by` | `UUID` | Yes | `` | users.id |
| `approved_at` | `DATETIME` | Yes | `` |  |
| `approval_comments` | `TEXT` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `document_id` | `documents.id` |
| `uploaded_by` | `users.id` |
| `approved_by` | `users.id` |
