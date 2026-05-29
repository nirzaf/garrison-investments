# photos

Defined in `backend/app/models/photo.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `filename` | String(255) | NOT NULL | — | — | — |
| `original_name` | String(255) | NOT NULL | — | — | — |
| `storage_path` | String(500) | NOT NULL | — | — | — |
| `compressed_path` | String(500) | NULL | — | — | — |
| `thumbnail_path` | String(500) | NULL | — | — | — |
| `mime_type` | String(80) | NOT NULL | — | — | — |
| `size_bytes` | BigInteger | NOT NULL | — | — | — |
| `width` | Integer | NULL | — | — | — |
| `height` | Integer | NULL | — | — | — |
| `entity_type` | String(30) | NOT NULL | — | — | — |
| `entity_id` | UUID | NOT NULL | — | — | — |
| `kind` | String(20) | NOT NULL | photo | — | — |
| `caption` | Text | NULL | — | — | — |
| `taken_at` | TimestampTZ | NULL | — | — | — |
| `uploaded_by` | UUID | NULL | — | users.id | — |
| `processing_status` | String(20) | NOT NULL | ready | — | — |
