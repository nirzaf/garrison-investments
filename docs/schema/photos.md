# photos

Original media and generated renditions for reports, updates, and other supported entities.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/photo.py)

The [photo service](../../backend/app/services/photo_service.py) uses `entity_type` and `entity_id` to associate files with their parents. Original, compressed, and thumbnail paths are object-storage keys. For daily report uploads, `report_revision` preserves the revision assigned to that upload for idempotent replay. `classification` is `unclassified`, `operational`, or `financial`; uploaded files begin unclassified. An independent reviewer records a reasoned, audited classification. Direct metadata, original, thumbnail, search, and signed-URL access applies the classification and existing owner/project checks.

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `filename` | `varchar(255)` | No | — |
| `original_name` | `varchar(255)` | No | — |
| `storage_path` | `varchar(500)` | No | — |
| `compressed_path` | `varchar(500)` | Yes | — |
| `thumbnail_path` | `varchar(500)` | Yes | — |
| `mime_type` | `varchar(80)` | No | — |
| `size_bytes` | `bigint` | No | — |
| `classification` | `varchar(20)` | No | `'unclassified'` |
| `report_revision` | `integer` | Yes | — |
| `width` | `integer` | Yes | — |
| `height` | `integer` | Yes | — |
| `entity_type` | `varchar(30)` | No | — |
| `entity_id` | `uuid` | No | — |
| `kind` | `varchar(20)` | No | `'photo'` |
| `caption` | `text` | Yes | — |
| `taken_at` | `timestamptz` | Yes | — |
| `uploaded_by` | `uuid` | Yes | — |
| `processing_status` | `varchar(20)` | No | `'ready'` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_photos` | `PRIMARY KEY (id)` |
| `ck_photos_ck_photos_kind_valid` | `CHECK ((kind IN ('photo', 'attachment')))` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_photos_uploaded_by_users` | `(uploaded_by)` | [`users(id)`](users.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_photos_date` | `btree` | `created_at DESC` | No | — |
| `idx_photos_entity` | `btree` | `entity_type, entity_id` | No | `(deleted_at IS NULL)` |
