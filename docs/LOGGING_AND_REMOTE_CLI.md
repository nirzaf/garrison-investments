# Logging and Remote CLI Guide

This guide explains how to access, search, filter, and stream centralized application logs through the remote CLI implemented in `backend/scripts/log_cli.py`.

## 1. What the System Captures

The centralized log system stores application events in the shared `activity_log` table and emits structured JSON application logs through `structlog`.

Captured events include:

- API requests and response outcomes
- Auth flows such as login, OTP verification, refresh, logout, and password reset
- User actions and domain events from service-layer audit writes
- State changes with `old_values` and `new_values`
- Handled and unhandled application errors
- Celery task failures
- Maintenance events such as log retention/archive runs
- Log query and stream access activity from the remote CLI

Each stored log entry includes standardized fields such as:

- `created_at`
- `event_type`
- `severity`
- `user_id`
- `request_id`
- `session_id`
- `ip_address`
- `endpoint`
- `http_method`
- `status_code`
- `source_service`
- `instance_id`
- `storage_tier`
- `context_payload`

## 2. Access Control

Remote log access is protected by the backend RBAC layer.

- Required permission: `audit:view`
- Typical authorized role: `admin`
- All CLI searches and live streams are themselves written back into the log store as `logs.cli.query` or `logs.cli.stream`

If a user does not have permission, the API returns `403 Forbidden`.

## 3. CLI Location

Run the CLI from the backend folder:

```bash
cd backend
python scripts/log_cli.py --help
```

You can also point it to a remote environment with `--base-url`.

## 4. Authentication

The CLI authenticates against the existing FastAPI auth endpoints and reuses the same JWT access token model as the web app.

### 4.1 Login and Print a Token

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  login \
  --email admin@example.com \
  --password 'your-password'
```

Example output:

```text
access_token=<jwt>
user=admin@example.com
```

### 4.2 Save a Token to a File

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  login \
  --email admin@example.com \
  --password 'your-password' \
  --save-token .log-token
```

### 4.3 Use an Existing Token

You can pass the token in one of three ways:

```bash
python scripts/log_cli.py --base-url https://portal.example.com --token '<jwt>' search
```

```bash
python scripts/log_cli.py --base-url https://portal.example.com --token-file .log-token search
```

```bash
export GARRISON_LOG_TOKEN='<jwt>'
python scripts/log_cli.py --base-url https://portal.example.com search
```

### 4.4 OTP Note

The CLI uses the same login plus OTP verification flow as the browser app.

- In development/test, the backend may return `dev_otp`
- In staging/production, provide the OTP explicitly with `--otp`

## 5. Search Logs

The `search` command calls `GET /api/v1/log-events` and supports full-text search plus exact field filters.

### 5.1 Basic Search

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search
```

### 5.2 Full-Text Search

Searches run against key text fields including action, endpoint, comments, and JSON payload text.

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --query "daily report missing"
```

### 5.3 Filter by Severity

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --severity ERROR
```

### 5.4 Filter by Event Type

Typical event types include:

- `api_request`
- `security_event`
- `user_action`
- `state_change`
- `system_event`
- `error`
- `log_access`

Example:

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --event-type error
```

### 5.5 Filter by Action

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --action auth.login_failed
```

### 5.6 Filter by Endpoint

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --endpoint /api/v1/auth
```

### 5.7 Filter by User, Request, or Session

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --user-id 11111111-1111-1111-1111-111111111111
```

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --request-id req-123
```

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --session-id-filter req-123
```

### 5.8 Filter by Source Service or Storage Tier

`storage_tier` lets you query hot logs, archived logs, or both through the same API.

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --source-service backend-api --storage-tier archive
```

### 5.9 Filter by Status Code or Time Window

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --status-code 500
```

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search \
  --created-from 2026-05-28T00:00:00Z \
  --created-to 2026-05-28T23:59:59Z
```

### 5.10 Pagination

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --limit 100 --offset 200
```

### 5.11 JSON Output

Use `--json` when another script or operator tool needs the raw response payload.

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --severity ERROR --json
```

## 6. Combine Filters

Typical production usage combines a text query with narrow field filters.

Example: failed auth requests on the auth endpoints:

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search \
  --event-type security_event \
  --action auth.login_failed \
  --endpoint /api/v1/auth \
  --severity ERROR
```

Example: archived retention events:

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search \
  --action maintenance.logs_retention \
  --storage-tier archive
```

## 7. Real-Time Streaming

The `tail` command opens a streaming connection to `GET /api/v1/log-events/stream`.

### 7.1 Tail All Matching Events

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  tail
```

### 7.2 Tail Only Errors

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  tail --event-type error
```

### 7.3 Tail a Specific Endpoint

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  tail --endpoint /api/v1/auth
```

### 7.4 Stop After N Events

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  tail --event-type error --max-events 20
```

## 8. Retention and Archives

The backend retention task runs through Celery and keeps archived logs accessible through the same query path.

- Hot retention window: `LOG_HOT_RETENTION_DAYS`
- Archive retention window: `LOG_ARCHIVE_RETENTION_DAYS`
- Stream poll interval: `LOG_STREAM_POLL_SECONDS` (default `1.0`, used by `GET /api/v1/log-events/stream`)
- Maintenance task: `archive_and_purge_logs`
- Scheduler entry: Celery beat in `backend/app/tasks/celery_app.py` (daily 03:30 UTC)

Operational effect:

1. Older hot logs move to `storage_tier=archive`
2. Expired archived logs are purged
3. Archived logs remain searchable through `search --storage-tier archive`

## 9. Troubleshooting

### 9.1 `403 Forbidden`

Cause:

- The authenticated user does not have `audit:view`

Action:

- Use an admin account or grant the permission through the role model

### 9.2 Login Works but Search Fails with `401`

Cause:

- Expired or missing bearer token

Action:

- Re-run `login`
- Confirm `--token`, `--token-file`, or `GARRISON_LOG_TOKEN` is set

### 9.3 No Results Returned

Cause:

- Filters are too narrow
- The event was archived and you searched only hot logs
- The event type or action name is different than expected

Action:

- Retry with only `--query`
- Retry with `--storage-tier all`, or query `hot` and `archive` separately
- Search by endpoint or time range first, then narrow down

## 10. Recommended Operator Workflows

### Investigate a 500 error

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --status-code 500 --severity ERROR
```

### Monitor auth failures in real time

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  tail --action auth.login_failed
```

### Review who queried the logs

```bash
python scripts/log_cli.py \
  --base-url https://portal.example.com \
  --token-file .log-token \
  search --event-type log_access
```

## 11. Grafana, Loki, and Alloy

Production container logs use a separate operational pipeline:

```text
container stdout -> Grafana Alloy -> Loki -> Grafana
```

This does not replace `activity_log`. PostgreSQL remains the authoritative audit and business-event
store; Loki retains operational container output for 14 days to support incident investigation.

Before serialization, the backend recursively redacts sensitive keys and credential patterns,
including bearer tokens, JWTs, cookies, passwords, OTPs, credential-bearing URLs, and sensitive
query parameters such as `token=...`. Request bodies, headers, raw Celery arguments, and task results
must not be attached to operational records.

Grafana is available only through the HTTPS hostname configured by `GRAFANA_DOMAIN`. Anonymous access
and public sign-up are disabled. Loki and Alloy have no host-published ports.

### Useful LogQL

Unhandled application and task failures:

```logql
{environment="production"} | json
  | message=~"unhandled_request_exception|task_failed"
```

Follow one request:

```logql
{environment="production"} | json | request_id="req-123"
```

Slow API requests:

```logql
{environment="production", service="backend"} | json
  | message="http_request_completed" | duration_ms > 2000
```

Celery retries:

```logql
{environment="production", service=~"celery_worker|celery_beat"} | json
  | message="task_retried"
```

The provisioned dashboards are **Garrison Production Logs** and **Garrison Incident Explorer**.
The operations dashboard includes log volume, error counts, HTTP response status distribution, and
the searchable log stream. The incident dashboard includes request/task correlation, HTTP p95
duration, and Celery retry/failure exploration.
Provisioned alerts cover unhandled failures, 5xx bursts, repeated task retries, sustained slow
requests, and Loki/Alloy errors. Alert query failures enter the alerting state; ordinary no-data
periods remain healthy.

### Sensitive Data Policy

- Never log request bodies, authorization headers, cookies, OTPs, passwords, tokens, task arguments,
  or task results.
- The central processor recursively redacts sensitive keys, bearer tokens, JWT-like values, and
  credentials embedded in URLs.
- `request_id`, `session_id`, `user_id`, and `task_id` are query-time JSON fields, not Loki labels.
- Loki labels are restricted to low-cardinality deployment metadata.

### Incident Fallback

If Grafana, Loki, or Alloy is unavailable, application services continue writing rotated Docker JSON
logs. Use `docker compose -f docker-compose.prod.yml logs --since 30m backend celery_worker` while the
observability stack is restored. Re-enable `EXCEPTION_EMAIL_ENABLED=true` if Grafana alerting must be
rolled back.

### Configuration regression tests

Run the focused, service-independent checks before deployment:

```bash
cd backend
pytest -q tests/test_structured_logging.py tests/test_observability_config.py
```

They validate JSON shape and redaction, request and task context cleanup, health-check suppression,
Celery lifecycle safety, image digests, private ports, 14-day retention, low-cardinality labels,
Grafana security settings, dashboard JSON, alert policy semantics, and idempotent database
initialization. Compose rendering and live service health remain separate deployment gates.
