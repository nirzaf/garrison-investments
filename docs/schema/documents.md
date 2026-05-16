# `documents`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `title` | `VARCHAR(255)` | No | `` |  |
| `document_type` | `VARCHAR(30)` | No | `` |  |
| `project_id` | `UUID` | Yes | `` | projects.id |
| `status` | `VARCHAR(20)` | No | `'pending_approval'` |  |
| `active_version` | `INTEGER` | Yes | `` |  |
| `metadata` | `JSONB` | No | `` |  |
| `expiry_date` | `DATE` | Yes | `` |  |
| `uploaded_by` | `UUID` | Yes | `` | users.id |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `project_id` | `projects.id` |
| `uploaded_by` | `users.id` |

## Referenced By

| Source | Target |
|---|---|
| `document_versions.document_id` | `documents.id` |
