# task_outbox

Background work recorded in the same database transaction as the operation that schedules it.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/task_outbox.py)

The [outbox dispatchers](../../backend/app/tasks/outbox.py) scan pending records to dispatch Celery tasks and track attempts. Report approvals use a dedupe key for export work. Email notifications use a separate one-minute dispatcher, stable due ordering, a five-minute lease and at most eight automatic broker submissions with exponential backoff. An expired dispatch/worker lease becomes `manual_review`; it is not automatically resent when delivery may have reached the provider. The audited technical retry command applies only to terminal failed queue submissions, never ambiguous provider outcomes.

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
| `next_attempt_at` | `timestamptz` | Yes | — |
| `lease_until` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_task_outbox` | `PRIMARY KEY (id)` |
| `uq_task_outbox_dedupe_key` | `UNIQUE (dedupe_key)` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `ix_task_outbox_pending` | `btree` | `created_at, id` | No | `(status = 'pending')` |
| `ix_task_outbox_notification_due` | `btree` | `next_attempt_at, created_at, id` | No | `(task_name = 'send_email_notification' AND status = 'pending')` |
