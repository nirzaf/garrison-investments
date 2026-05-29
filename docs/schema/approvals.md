# approvals

Defined in `backend/app/models/approval.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `request_type` | String(60) | NOT NULL | — | — | — |
| `request_id` | UUID | NOT NULL | — | — | — |
| `project_id` | UUID | NULL | — | projects.id | — |
| `submitter_id` | UUID | NULL | — | users.id | — |
| `approver_id` | UUID | NULL | — | users.id | — |
| `delegated_to_id` | UUID | NULL | — | users.id | — |
| `escalation_user_id` | UUID | NULL | — | users.id | — |
| `status` | String(30) | NOT NULL | pending | — | — |
| `step_order` | Integer | NOT NULL | 1 | — | — |
| `amount` | Numeric(14, 2) | NULL | — | — | — |
| `currency` | String(3) | NULL | — | — | — |
| `title` | String(200) | NOT NULL | — | — | — |
| `submitter_comments` | Text | NULL | — | — | — |
| `decision_comments` | Text | NULL | — | — | — |
| `delegation_reason` | Text | NULL | — | — | — |
| `override_reason` | Text | NULL | — | — | — |
| `submitted_at` | TimestampTZ | NOT NULL | — | — | — |
| `due_at` | TimestampTZ | NOT NULL | — | — | — |
| `reminded_at` | TimestampTZ | NULL | — | — | — |
| `escalated_at` | TimestampTZ | NULL | — | — | — |
| `decided_at` | TimestampTZ | NULL | — | — | — |
