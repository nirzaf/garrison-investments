# users

Portal accounts, roles, profile fields, password hashes, and sign-in lockout state.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/user.py)

The access revision is included in issued access tokens. Protected requests
compare it with the current account revision. Account access changes advance
it and revoke refresh sessions and pending login codes.
[Access-revision migration](../../backend/alembic/versions/202605310006_user_access_revision.py) · [Authentication service](../../backend/app/services/auth_service.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `email` | `varchar(255)` | No | — |
| `full_name` | `varchar(255)` | No | — |
| `role` | `varchar(64)` | No | — |
| `access_revision` | `integer` | No | `0` |
| `employee_code` | `varchar(64)` | Yes | — |
| `phone` | `varchar(32)` | Yes | — |
| `is_active` | `boolean` | No | `true` |
| `must_change_password` | `boolean` | No | `true` |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |
| `password_hash` | `varchar(255)` | Yes | — |
| `failed_login_attempts` | `integer` | No | `0` |
| `locked_until` | `timestamptz` | Yes | — |
| `last_login_at` | `timestamptz` | Yes | — |
| `designation` | `varchar(100)` | Yes | — |
| `recovery_email_digest` | `varchar(64)` | Yes | — |
| `recovery_email_verified_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_users` | `PRIMARY KEY (id)` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `ix_users_email_active` | `btree` | `email` | No | — |
| `ix_users_role_active` | `btree` | `role` | No | `(deleted_at IS NULL)` |
| `uq_users_email_active` | `btree` | `email` | Yes | `(deleted_at IS NULL)` |
| `uq_users_employee_code_active` | `btree` | `employee_code` | Yes | `((deleted_at IS NULL) AND (employee_code IS NOT NULL))` |
