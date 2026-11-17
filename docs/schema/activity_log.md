# activity_log

Audit and operational events with actor, request, context, and retention metadata.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/activity_log.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `user_id` | `uuid` | Yes | — |
| `action` | `varchar(64)` | No | — |
| `entity_type` | `varchar(64)` | Yes | — |
| `entity_id` | `uuid` | Yes | — |
| `ip_address` | `varchar(64)` | Yes | — |
| `user_agent` | `varchar(512)` | Yes | — |
| `comments` | `text` | Yes | — |
| `old_values` | `jsonb` | Yes | — |
| `new_values` | `jsonb` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |
| `event_type` | `varchar(32)` | No | `'audit'` |
| `severity` | `varchar(16)` | No | `'INFO'` |
| `request_id` | `varchar(64)` | Yes | — |
| `session_id` | `varchar(128)` | Yes | — |
| `endpoint` | `varchar(255)` | Yes | — |
| `http_method` | `varchar(16)` | Yes | — |
| `status_code` | `integer` | Yes | — |
| `source_service` | `varchar(64)` | Yes | — |
| `instance_id` | `varchar(128)` | Yes | — |
| `storage_tier` | `varchar(16)` | No | `'hot'` |
| `archived_at` | `timestamptz` | Yes | — |
| `retention_until` | `timestamptz` | Yes | — |
| `context_payload` | `jsonb` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_activity_log` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_activity_log_user_id_users` | `(user_id)` | [`users(id)`](users.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `ix_activity_log_endpoint` | `btree` | `endpoint` | No | — |
| `ix_activity_log_event_type` | `btree` | `event_type` | No | — |
| `ix_activity_log_request_id` | `btree` | `request_id` | No | — |
| `ix_activity_log_search` | `gin` | `activity_log_search_vector((event_type)::text, (severity)::text, (action)::text, (entity_type)::text, (endpoint)::text, comments, (context_payload)::text, (old_values)::text, (new_values)::text)` | No | — |
| `ix_activity_log_session_id` | `btree` | `session_id` | No | — |
| `ix_activity_log_severity` | `btree` | `severity` | No | — |
| `ix_activity_log_source_service` | `btree` | `source_service` | No | — |
| `ix_activity_log_storage_tier` | `btree` | `storage_tier` | No | — |
| `ix_activity_log_user_action` | `btree` | `user_id, action` | No | — |

## Business audit streams

[Revision 092](../../backend/alembic/versions/202605310092_business_log_streams.py)
adds `business_log_streams`. Each row records the user and correlation IDs
and the open, expiry and close timestamps. The user UUID is retained when
an account is deleted. The index on user and expiry supports the two-stream
admission check. The table keeps stream receipts independent of the
business token and event payload.
