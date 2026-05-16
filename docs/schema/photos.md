# `photos`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `filename` | `VARCHAR(255)` | No | `` |  |
| `original_name` | `VARCHAR(255)` | No | `` |  |
| `storage_path` | `VARCHAR(500)` | No | `` |  |
| `compressed_path` | `VARCHAR(500)` | Yes | `` |  |
| `thumbnail_path` | `VARCHAR(500)` | Yes | `` |  |
| `mime_type` | `VARCHAR(80)` | No | `` |  |
| `size_bytes` | `BIGINT` | No | `` |  |
| `width` | `INTEGER` | Yes | `` |  |
| `height` | `INTEGER` | Yes | `` |  |
| `entity_type` | `VARCHAR(30)` | No | `` |  |
| `entity_id` | `UUID` | No | `` |  |
| `kind` | `VARCHAR(20)` | No | `'photo'` |  |
| `caption` | `TEXT` | Yes | `` |  |
| `taken_at` | `DATETIME` | Yes | `` |  |
| `uploaded_by` | `UUID` | Yes | `` | users.id |
| `processing_status` | `VARCHAR(20)` | No | `'ready'` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `uploaded_by` | `users.id` |
