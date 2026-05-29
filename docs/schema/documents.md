# documents

Defined in `backend/app/models/document.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `title` | String(255) | NOT NULL | — | — | — |
| `document_type` | String(30) | NOT NULL | — | — | — |
| `project_id` | UUID | NULL | — | projects.id | — |
| `status` | String(20) | NOT NULL | pending_approval | — | — |
| `active_version` | Integer | NULL | — | — | — |
| `metadata_json` | 'metadata' | NOT NULL | — | — | — |
| `expiry_date` | Date | NULL | — | — | — |
| `uploaded_by` | UUID | NULL | — | users.id | — |
