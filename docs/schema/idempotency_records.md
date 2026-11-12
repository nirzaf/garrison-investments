# idempotency_records

Request keys and resource references used to deduplicate retried writes.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/idempotency_record.py)

The [idempotency service](../../backend/app/services/idempotency.py) scopes a key by user and route. It reserves the key before creating the resource and binds `resource_id` in the same transaction. Invoice payments bind a key to the recorded payment in the same transaction. Selected material quantity commands also persist a canonical request fingerprint and their result. The same key and payload return that result, while a changed payload conflicts.

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `key` | `varchar(200)` | No | — |
| `user_id` | `uuid` | No | — |
| `route` | `varchar(100)` | No | — |
| `resource_type` | `varchar(50)` | Yes | — |
| `resource_id` | `uuid` | Yes | — |
| `request_fingerprint` | `varchar(64)` | Yes | — |
| `response_json` | `jsonb` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_idempotency_records` | `PRIMARY KEY (id)` |
| `uq_idempotency_records_key_user_route` | `UNIQUE (key, user_id, route)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_idempotency_records_user_id_users` | `(user_id)` | [`users(id)`](users.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_idempotency_records_created_at` | `btree` | `created_at` | No | — |
