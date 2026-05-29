# documents

Defined in `backend/app/models/document.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `active_version` | Integer | NULL | — | — | — |
| `document_type` | String(30) | NOT NULL | — | — | — |
| `expiry_date` | Date | NULL | — | — | — |
| `metadata` | JSONB | NOT NULL | — | — | — |
| `project_id` | UUID | NULL | — | projects.id | — |
| `status` | String(20) | NOT NULL | pending_approval | — | — |
| `title` | String(255) | NOT NULL | — | — | — |
| `uploaded_by` | UUID | NULL | — | users.id | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

