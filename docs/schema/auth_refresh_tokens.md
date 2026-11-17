# auth_refresh_tokens

Hashed refresh tokens with expiry, revocation and authenticated-session ownership.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/auth.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `user_id` | `uuid` | No | — |
| `token_hash` | `varchar(255)` | No | — |
| `session_id` | `uuid` | Yes, for legacy refresh rows | — |
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
| `fk_auth_refresh_tokens_session_owner` | `(session_id, user_id)` | `auth_sessions(id, user_id)` | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `ix_auth_refresh_tokens_token_hash_active` | `btree` | `token_hash` | Yes | `(deleted_at IS NULL)` |
| `ix_auth_refresh_tokens_user_active` | `btree` | `user_id` | No | `(deleted_at IS NULL)` |
| `ix_auth_refresh_tokens_session_id` | `btree` | `session_id` | No | — |

## Authenticated sessions

Revision [`202605310062`](../../backend/alembic/versions/202605310062_auth_sessions.py)
adds `auth_sessions`. Each row contains an application-generated UUID, its
owning user UUID, creation and update timestamps, absolute expiry, and
optional revocation time. The primary key is `id`, the composite unique key
is `(id, user_id)`, and expiry must follow creation. The user foreign key
cascades only on actual user deletion. A `(user_id, expires_at)` index
supports bounded account-session lookup.

Login OTP creates one session. The access JWT carries `sid` and expires no
later than the session. Refresh rotates within that session. Reuse of an
unexpired rotated refresh token revokes its session. Logout revokes the
current session. Password change, reset and access changes revoke all
sessions for the affected user.

Legacy nontechnical JWTs without `sid` retain their original expiry and
access-revision checks. The first use of an unexpired legacy refresh token
creates a session without extending its existing expiry. The additive
schema and records must be retained on rollback. Technical login remains
disabled in this increment.
