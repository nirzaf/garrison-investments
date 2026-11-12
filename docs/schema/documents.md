# documents

Document metadata, optional project association, expiry, and active version number.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/document.py)

`active_version` is the selected version number within the document. See [document versions](document_versions.md) and the [document service](../../backend/app/services/document_service.py) for version selection.

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `title` | `varchar(255)` | No | — |
| `document_type` | `varchar(30)` | No | — |
| `project_id` | `uuid` | Yes | — |
| `status` | `varchar(20)` | No | `'pending_approval'` |
| `active_version` | `integer` | Yes | — |
| `metadata` | `jsonb` | No | — |
| `expiry_date` | `date` | Yes | — |
| `uploaded_by` | `uuid` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_documents` | `PRIMARY KEY (id)` |
| `ck_documents_ck_documents_status_valid` | `CHECK ((status IN ('pending_approval', 'active', 'superseded', 'archived')))` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_documents_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `CASCADE` |
| `fk_documents_uploaded_by_users` | `(uploaded_by)` | [`users(id)`](users.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_documents_project` | `btree` | `project_id` | No | `(deleted_at IS NULL)` |
| `idx_documents_search` | `gin` | `to_tsvector('english'::regconfig, (title)::text)` | No | — |
| `idx_documents_status` | `btree` | `status` | No | — |
| `idx_documents_type` | `btree` | `document_type` | No | `(deleted_at IS NULL)` |
