# photos

Defined in `backend/app/models/photo.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `caption` | Text | NULL | — | — | — |
| `compressed_path` | String(500) | NULL | — | — | — |
| `entity_id` | UUID | NOT NULL | — | — | — |
| `entity_type` | String(30) | NOT NULL | — | — | — |
| `filename` | String(255) | NOT NULL | — | — | — |
| `height` | Integer | NULL | — | — | — |
| `kind` | String(20) | NOT NULL | photo | — | — |
| `mime_type` | String(80) | NOT NULL | — | — | — |
| `original_name` | String(255) | NOT NULL | — | — | — |
| `processing_status` | String(20) | NOT NULL | ready | — | — |
| `size_bytes` | BigInteger | NOT NULL | — | — | — |
| `storage_path` | String(500) | NOT NULL | — | — | — |
| `taken_at` | TimestampTZ | NULL | — | — | — |
| `thumbnail_path` | String(500) | NULL | — | — | — |
| `uploaded_by` | UUID | NULL | — | users.id | — |
| `width` | Integer | NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

