# document_versions

Version-specific classification, object-storage keys, file metadata, and approval status.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/document.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `document_id` | `uuid` | No | — |
| `version` | `integer` | No | — |
| `status` | `varchar(20)` | No | `'pending_approval'` |
| `classification` | `varchar(20)` | No | `'unclassified'` |
| `storage_path` | `varchar(500)` | No | — |
| `original_name` | `varchar(255)` | No | — |
| `mime_type` | `varchar(80)` | No | — |
| `size_bytes` | `bigint` | No | — |
| `uploaded_by` | `uuid` | Yes | — |
| `approved_by` | `uuid` | Yes | — |
| `approved_at` | `timestamptz` | Yes | — |
| `approval_comments` | `text` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_document_versions` | `PRIMARY KEY (id)` |
| `ck_document_versions_ck_document_versions_status_valid` | `CHECK ((status IN ('pending_approval', 'active', 'superseded', 'rejected')))` |
| `ck_document_versions_classification` | `CHECK (classification IN ('unclassified', 'operational', 'financial'))` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_document_versions_approved_by_users` | `(approved_by)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_document_versions_document_id_documents` | `(document_id)` | [`documents(id)`](documents.md) | `CASCADE` |
| `fk_document_versions_uploaded_by_users` | `(uploaded_by)` | [`users(id)`](users.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_document_versions_document` | `btree` | `document_id, version` | Yes | — |
| `idx_document_versions_status` | `btree` | `status` | No | — |
