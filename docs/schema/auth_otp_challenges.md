# auth_otp_challenges

Hashed one-time codes for login and password reset, with expiry, attempts, and consumption state.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/auth.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `user_id` | `uuid` | No | — |
| `purpose` | `varchar(32)` | No | `'login'` |
| `otp_hash` | `varchar(255)` | No | — |
| `expires_at` | `timestamptz` | No | — |
| `consumed_at` | `timestamptz` | Yes | — |
| `attempts` | `integer` | No | `0` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_auth_otp_challenges` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_auth_otp_challenges_user_id_users` | `(user_id)` | [`users(id)`](users.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `ix_auth_otp_challenges_user_active` | `btree` | `user_id` | No | `(deleted_at IS NULL)` |
