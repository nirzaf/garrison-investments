# notifications

User notifications with read, mute, email delivery state, and retained supersession history for obsolete leave actions.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/notification.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `user_id` | `uuid` | No | — |
| `title` | `varchar(200)` | No | — |
| `body` | `text` | No | — |
| `notification_type` | `varchar(30)` | No | — |
| `reference_type` | `varchar(30)` | Yes | — |
| `reference_id` | `uuid` | Yes | — |
| `is_read` | `boolean` | No | `false` |
| `muted` | `boolean` | No | `false` |
| `email_status` | `varchar(20)` | Yes | — |
| `read_at` | `timestamptz` | Yes | — |
| `event_code` | `varchar(30)` | Yes | — |
| `event_revision` | `integer` | Yes | — |
| `superseded_at` | `timestamptz` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_notifications` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_notifications_user_id_users` | `(user_id)` | [`users(id)`](users.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_notifications_reference` | `btree` | `reference_type, reference_id` | No | — |
| `idx_notifications_user` | `btree` | `user_id, is_read, created_at DESC` | No | — |
