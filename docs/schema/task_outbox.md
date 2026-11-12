# task_outbox

Background work recorded in the same database transaction as the operation that schedules it.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/task_outbox.py)

The [outbox dispatcher](../../backend/app/tasks/outbox.py) scans pending records to dispatch Celery tasks and tracks the number of attempts. Report approvals use a dedupe key for export work.

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `dedupe_key` | `varchar(200)` | No | — |
| `task_name` | `varchar(100)` | No | — |
| `args_json` | `jsonb` | No | — |
| `kwargs_json` | `jsonb` | No | — |
| `status` | `varchar(16)` | No | `'pending'` |
| `attempts` | `integer` | No | `0` |
| `created_at` | `timestamptz` | No | `now()` |
| `dispatched_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_task_outbox` | `PRIMARY KEY (id)` |
| `uq_task_outbox_dedupe_key` | `UNIQUE (dedupe_key)` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `ix_task_outbox_pending` | `btree` | `created_at, id` | No | `(status = 'pending')` |
