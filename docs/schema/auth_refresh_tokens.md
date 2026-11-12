# auth_refresh_tokens

Hashed refresh tokens with expiry and revocation timestamps.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/auth.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `user_id` | `uuid` | No | — |
| `token_hash` | `varchar(255)` | No | — |
| `expires_at` | `timestamptz` | No | — |
| `revoked_at` | `timestamptz` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_auth_refresh_tokens` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_auth_refresh_tokens_user_id_users` | `(user_id)` | [`users(id)`](users.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `ix_auth_refresh_tokens_token_hash_active` | `btree` | `token_hash` | Yes | `(deleted_at IS NULL)` |
| `ix_auth_refresh_tokens_user_active` | `btree` | `user_id` | No | `(deleted_at IS NULL)` |
