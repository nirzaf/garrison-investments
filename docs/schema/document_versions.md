# document_versions

Defined in `backend/app/models/document.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `approval_comments` | Text | NULL | — | — | — |
| `approved_at` | TimestampTZ | NULL | — | — | — |
| `approved_by` | UUID | NULL | — | users.id | — |
| `document_id` | UUID | NOT NULL | — | documents.id | — |
| `mime_type` | String(80) | NOT NULL | — | — | — |
| `original_name` | String(255) | NOT NULL | — | — | — |
| `size_bytes` | BigInteger | NOT NULL | — | — | — |
| `status` | String(20) | NOT NULL | pending_approval | — | — |
| `storage_path` | String(500) | NOT NULL | — | — | — |
| `uploaded_by` | UUID | NULL | — | users.id | — |
| `version` | Integer | NOT NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

