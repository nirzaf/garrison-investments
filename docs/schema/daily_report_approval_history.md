# daily_report_approval_history

Daily report submission and decision history, including the actor and previous status.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/daily_report.py)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `report_id` | `uuid` | No | — |
| `actor_id` | `uuid` | Yes | — |
| `decision` | `varchar(20)` | No | — |
| `previous_status` | `varchar(20)` | No | — |
| `comments` | `text` | Yes | — |
| `decided_at` | `timestamptz` | No | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_daily_report_approval_history` | `PRIMARY KEY (id)` |
| `ck_daily_report_approval_history_ck_daily_report_approv_7120` | `CHECK ((decision IN ('submitted', 'approved', 'rejected')))` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_daily_report_approval_history_actor_id_users` | `(actor_id)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_daily_report_approval_history_report_id_daily_reports` | `(report_id)` | [`daily_reports(id)`](daily_reports.md) | `CASCADE` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_daily_report_approval_history_report` | `btree` | `report_id, decided_at DESC` | No | — |
