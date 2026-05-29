# daily_report_approval_history

Defined in `backend/app/models/daily_report.py`

## Columns

| Column | Type | Nullable | Default | Foreign Key | Index/Key |
|---|---|---|---|---|---|
| `id` | UUID | — | uuid_generate_v4() | — | PRIMARY KEY |
| `report_id` | UUID | NOT NULL | — | daily_reports.id | — |
| `actor_id` | UUID | NULL | — | users.id | — |
| `decision` | String(20) | NOT NULL | — | — | — |
| `previous_status` | String(20) | NOT NULL | — | — | — |
| `comments` | Text | NULL | — | — | — |
| `decided_at` | TimestampTZ | NOT NULL | — | — | — |
