# approvals

Approval inbox items with submitter, approver, delegation, escalation, and decision state.

[Schema index](README.md) · [SQLAlchemy model](../../backend/app/models/approval.py)

The combination of `request_type` and `request_id` identifies the underlying workflow entity. The partial unique index covers open items in the pending, delegated, and escalated states.

## Columns

| Column | PostgreSQL type | Nullable | Server default |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `uuid_generate_v4()` |
| `request_type` | `varchar(60)` | No | — |
| `request_id` | `uuid` | No | — |
| `project_id` | `uuid` | Yes | — |
| `submitter_id` | `uuid` | Yes | — |
| `approver_id` | `uuid` | Yes | — |
| `delegated_to_id` | `uuid` | Yes | — |
| `escalation_user_id` | `uuid` | Yes | — |
| `status` | `varchar(30)` | No | `'pending'` |
| `step_order` | `integer` | No | `1` |
| `submission_revision` | `integer` | Yes | — |
| `decided_by` | `uuid` | Yes | — |
| `amount` | `numeric(14, 2)` | Yes | — |
| `currency` | `varchar(3)` | Yes | — |
| `title` | `varchar(200)` | No | — |
| `submitter_comments` | `text` | Yes | — |
| `decision_comments` | `text` | Yes | — |
| `delegation_reason` | `text` | Yes | — |
| `override_reason` | `text` | Yes | — |
| `submitted_at` | `timestamptz` | No | — |
| `due_at` | `timestamptz` | No | — |
| `reminded_at` | `timestamptz` | Yes | — |
| `escalated_at` | `timestamptz` | Yes | — |
| `decided_at` | `timestamptz` | Yes | — |
| `created_at` | `timestamptz` | No | `now()` |
| `updated_at` | `timestamptz` | No | `now()` |
| `deleted_at` | `timestamptz` | Yes | — |

## Keys and constraints

| Constraint | Rule |
| --- | --- |
| `pk_approvals` | `PRIMARY KEY (id)` |

## Foreign keys

| Constraint | Local columns | Referenced columns | On delete |
| --- | --- | --- | --- |
| `fk_approvals_approver_id_users` | `(approver_id)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_approvals_delegated_to_id_users` | `(delegated_to_id)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_approvals_escalation_user_id_users` | `(escalation_user_id)` | [`users(id)`](users.md) | `SET NULL` |
| `fk_approvals_project_id_projects` | `(project_id)` | [`projects(id)`](projects.md) | `SET NULL` |
| `fk_approvals_submitter_id_users` | `(submitter_id)` | [`users(id)`](users.md) | `SET NULL` |

## Indexes

| Index | Method | Keys | Unique | Predicate |
| --- | --- | --- | --- | --- |
| `idx_approvals_delegate_inbox` | `btree` | `delegated_to_id, status` | No | — |
| `idx_approvals_due` | `btree` | `status, due_at` | No | — |
| `idx_approvals_inbox` | `btree` | `approver_id, status` | No | — |
| `idx_approvals_outbox` | `btree` | `submitter_id, status` | No | — |
| `idx_approvals_request` | `btree` | `request_type, request_id` | No | — |
| `uq_approvals_open_request` | `btree` | `request_type, request_id` | Yes | `((deleted_at IS NULL) AND (status IN ('pending', 'delegated', 'escalated')))` |

## Material-request stages

For versioned material requests the approval row references
`material_request_submissions(request_id, submission_revision)`. A partial
unique index restricts each revision to one row per stage. Stage 1 is the
assigned engineer and stage 2 is the assigned Group Project Manager.
`decided_by` records the actual actor. Historical approval rows retain their
original status without acquiring a staged decision.

Queued material-decision email is revalidated against the current submission
revision and request state when dispatched. A return-for-correction email is
eligible only while that revision remains returned and the original submitter
is still authorized; correcting the request makes the queued message stale.
[Migration 102](../../backend/alembic/versions/202605310102_material_submission_revisions.py)
