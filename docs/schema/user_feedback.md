# user_feedback

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/user_feedback.py) · [Migration 099](../../backend/alembic/versions/202605310099_user_feedback.py) · [Feedback and triage](../LOGGING_AND_REMOTE_CLI.md#user-feedback-and-triage)

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | — |
| `reporter_id` | `uuid` | Yes | — |
| `submission_id` | `uuid` | No | — |
| `submission_fingerprint` | `varchar(64)` | No | — |
| `category` | `varchar(16)` | No | — |
| `title` | `varchar(140)` | No | — |
| `description` | `text` | No | — |
| `status` | `varchar(16)` | No | `'new'` |
| `revision` | `integer` | No | `1` |
| `diagnostics` | `jsonb` | No | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |

## Constraints and queries

- `reporter_id` references [`users.id`](users.md) with `ON DELETE SET NULL`.
- The unique pair `(reporter_id, submission_id)` and payload fingerprint make
  retries idempotent. The service locks the reporter row before admitting up to
  ten new reports per hour. The `(reporter_id, created_at)` index supports that check.
- Category is `bug`, `suggestion`, or `other`. Status is `new`,
  `investigating`, or `resolved`. Triage locks the row, requires the current
  revision, and records changed status and revision in [the audit log](activity_log.md).
- The `(created_at, id)` index supports the newest-first inbox.
- Diagnostics contain up to eight verified failed request summaries. The service
  stores the request reference, timestamp, module, HTTP method, and status.
  Summary snapshots remain with the report when its status changes.

Migration 099 adds an empty table and indexes. Existing business and audit
tables need no backfill. An application rollback should preserve the table
and submitted reports.
