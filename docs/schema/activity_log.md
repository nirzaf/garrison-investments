# activity_log

Defined in `backend/app/models/activity_log.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `user_id` | UUID | NULL | — | users.id | — |
| `event_type` | String(32) | NOT NULL | audit | — | — |
| `severity` | String(16) | NOT NULL | INFO | — | — |
| `action` | String(64) | NOT NULL | — | — | — |
| `entity_type` | String(64) | NULL | — | — | — |
| `entity_id` | UUID | NULL | — | — | — |
| `request_id` | String(64) | NULL | — | — | — |
| `session_id` | String(128) | NULL | — | — | — |
| `ip_address` | String(64) | NULL | — | — | — |
| `endpoint` | String(255) | NULL | — | — | — |
| `http_method` | String(16) | NULL | — | — | — |
| `status_code` | Integer | NULL | — | — | — |
| `source_service` | String(64) | NULL | — | — | — |
| `instance_id` | String(128) | NULL | — | — | — |
| `storage_tier` | String(16) | NOT NULL | hot | — | — |
| `archived_at` | TimestampTZ | NULL | — | — | — |
| `retention_until` | TimestampTZ | NULL | — | — | — |
| `user_agent` | String(512) | NULL | — | — | — |
| `comments` | Text | NULL | — | — | — |
| `context_payload` | JSONB | NULL | — | — | — |
| `old_values` | JSONB | NULL | — | — | — |
| `new_values` | JSONB | NULL | — | — | — |
