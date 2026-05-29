# activity_log

Defined in `backend/app/models/activity_log.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `action` | String(64) | NOT NULL | — | — | — |
| `archived_at` | TimestampTZ | NULL | — | — | — |
| `comments` | Text | NULL | — | — | — |
| `context_payload` | JSONB | NULL | — | — | — |
| `endpoint` | String(255) | NULL | — | — | — |
| `entity_id` | UUID | NULL | — | — | — |
| `entity_type` | String(64) | NULL | — | — | — |
| `event_type` | String(32) | NOT NULL | audit | — | — |
| `http_method` | String(16) | NULL | — | — | — |
| `instance_id` | String(128) | NULL | — | — | — |
| `ip_address` | String(64) | NULL | — | — | — |
| `new_values` | JSONB | NULL | — | — | — |
| `old_values` | JSONB | NULL | — | — | — |
| `request_id` | String(64) | NULL | — | — | — |
| `retention_until` | TimestampTZ | NULL | — | — | — |
| `session_id` | String(128) | NULL | — | — | — |
| `severity` | String(16) | NOT NULL | INFO | — | — |
| `source_service` | String(64) | NULL | — | — | — |
| `status_code` | Integer | NULL | — | — | — |
| `storage_tier` | String(16) | NOT NULL | hot | — | — |
| `user_agent` | String(512) | NULL | — | — | — |
| `user_id` | UUID | NULL | — | users.id | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

