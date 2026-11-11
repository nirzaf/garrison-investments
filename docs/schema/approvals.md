# approvals

Defined in `backend/app/models/approval.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `amount` | Numeric(14, 2) | NULL | — | — | — |
| `approver_id` | UUID | NULL | — | users.id | — |
| `currency` | String(3) | NULL | — | — | — |
| `decided_at` | TimestampTZ | NULL | — | — | — |
| `decision_comments` | Text | NULL | — | — | — |
| `delegated_to_id` | UUID | NULL | — | users.id | — |
| `delegation_reason` | Text | NULL | — | — | — |
| `due_at` | TimestampTZ | NOT NULL | — | — | — |
| `escalated_at` | TimestampTZ | NULL | — | — | — |
| `escalation_user_id` | UUID | NULL | — | users.id | — |
| `override_reason` | Text | NULL | — | — | — |
| `project_id` | UUID | NULL | — | projects.id | — |
| `reminded_at` | TimestampTZ | NULL | — | — | — |
| `request_id` | UUID | NOT NULL | — | — | — |
| `request_type` | String(60) | NOT NULL | — | — | — |
| `status` | String(30) | NOT NULL | pending | — | — |
| `step_order` | Integer | NOT NULL | 1 | — | — |
| `submitted_at` | TimestampTZ | NOT NULL | — | — | — |
| `submitter_comments` | Text | NULL | — | — | — |
| `submitter_id` | UUID | NULL | — | users.id | — |
| `title` | String(200) | NOT NULL | — | — | — |
| `created_at` | TimestampTZ | NOT NULL | now() | — | — |
| `updated_at` | TimestampTZ | NOT NULL | now() | — | — |
| `deleted_at` | TimestampTZ | NULL | — | — | — |

