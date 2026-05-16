# `approvals`

Generated from the current SQLAlchemy model metadata in `backend/app/models`.

## Columns

| Column | Type | Nullable | Default | References |
|---|---|---:|---|---|
| `id` | `UUID` | No | `uuid_generate_v4()` |  |
| `request_type` | `VARCHAR(60)` | No | `` |  |
| `request_id` | `UUID` | No | `` |  |
| `project_id` | `UUID` | Yes | `` | projects.id |
| `submitter_id` | `UUID` | Yes | `` | users.id |
| `approver_id` | `UUID` | Yes | `` | users.id |
| `delegated_to_id` | `UUID` | Yes | `` | users.id |
| `escalation_user_id` | `UUID` | Yes | `` | users.id |
| `status` | `VARCHAR(30)` | No | `'pending'` |  |
| `step_order` | `INTEGER` | No | `1` |  |
| `amount` | `NUMERIC(14, 2)` | Yes | `` |  |
| `currency` | `VARCHAR(3)` | Yes | `` |  |
| `title` | `VARCHAR(200)` | No | `` |  |
| `submitter_comments` | `TEXT` | Yes | `` |  |
| `decision_comments` | `TEXT` | Yes | `` |  |
| `delegation_reason` | `TEXT` | Yes | `` |  |
| `override_reason` | `TEXT` | Yes | `` |  |
| `submitted_at` | `DATETIME` | No | `` |  |
| `due_at` | `DATETIME` | No | `` |  |
| `reminded_at` | `DATETIME` | Yes | `` |  |
| `escalated_at` | `DATETIME` | Yes | `` |  |
| `decided_at` | `DATETIME` | Yes | `` |  |
| `created_at` | `DATETIME` | No | `now()` |  |
| `updated_at` | `DATETIME` | No | `now()` |  |
| `deleted_at` | `DATETIME` | Yes | `` |  |

## Keys

- Primary key: `id`

## Outbound Relationships

| Column | References |
|---|---|
| `project_id` | `projects.id` |
| `submitter_id` | `users.id` |
| `approver_id` | `users.id` |
| `delegated_to_id` | `users.id` |
| `escalation_user_id` | `users.id` |
