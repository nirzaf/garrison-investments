# Logging and Remote CLI Guide

[Documentation index](README.md) · [Observability architecture](../README.md#observability-and-audit) · [Operations runbook](OPERATIONS_AND_DEPLOYMENT.md)

## Choose a log source

| Need | Source |
| --- | --- |
| Who performed an action, what changed, or who queried audit data | PostgreSQL `activity_log` via the authenticated audit UI or [log-events API](../backend/app/api/v1/logs.py). Search or stream from the remote CLI. |
| Request latency, unhandled exceptions, Celery retries, or container diagnostics | [Grafana and Loki](#grafana-loki-and-alloy). Correlate API and task records with request or task IDs. |
| Logs during a pipeline outage | [Rotated Docker logs on the deployment host](#incident-fallback). |

Audit entries can contain actions, state changes, request outcomes, authentication and log-access events, and maintenance events. Available fields include timestamp, severity, user ID, request and session IDs, source service, endpoint, status code, and storage tier. Request health events are disabled by default through `LOG_HEALTHCHECKS`.

## Access and CLI setup

Both `GET /api/v1/log-events` and `GET /api/v1/log-events/stream` require an authenticated user with `audit:view`. See [roles and permissions](ROLES_AND_PERMISSIONS.md) for assignments. Access is itself audited. CLI requests carry a CLI session ID and are recorded as `logs.cli.query` or `logs.cli.stream`.

From the repository root, use the backend Python environment with its dependencies installed:

```bash
cd backend
python scripts/log_cli.py --help
python scripts/log_cli.py search --help
python scripts/log_cli.py tail --help
```

The CLI accepts an existing short-lived access token from an authorized sign-in. Store the token in a restricted local file, then define a helper that supplies the environment URL and file path:

```bash
export GARRISON_API_BASE_URL=https://portal.garrisons.lk
export GARRISON_LOG_TOKEN_FILE="$HOME/.garrison-log-token"
garrison_logs() {
  python scripts/log_cli.py --token-file "$GARRISON_LOG_TOKEN_FILE" "$@"
}
garrison_logs search --severity ERROR --limit 20
```

The file must contain only the access token. Set permissions to `0600` and delete it after use. The CLI reads an explicit `--token` or `GARRISON_LOG_TOKEN` before `--token-file`. Unset an expired environment token when using the file. `--base-url` overrides `GARRISON_API_BASE_URL`. Use the origin without an `/api/v1` suffix.

The CLI's `login` subcommand starts a new OTP challenge on every invocation and prints the access token. In development it can use the returned development OTP. The staging login OTP works only when configured for staging. Production login uses a fresh delivered OTP for each challenge, so complete the authorized sign-in flow and supply its access token to the CLI. Keep tokens out of terminal captures and evidence files.

## Search and tail

`search` supports combinations of filters and returns the total number of matching rows. `tail` uses the streaming API and writes one JSON event per line. Give it `--created-from` to bound the historical results it can stream. Use `--max-events` or Ctrl-C to end the stream.

| Need | CLI filters |
| --- | --- |
| Find text or a domain action | `--query`, `--action`, `--entity-type` |
| Find request outcomes | `--severity`, `--event-type`, `--endpoint`, `--source-service` |
| Find a person or time range | `--user-id`, `--created-from`, `--storage-tier hot\|archive\|all` |
| Narrow a search to an exact identifier or response | `--request-id`, `--session-id-filter`, `--ip-address`, `--status-code`, `--created-to` |
| Page or export a search | `--limit` (1–200), `--offset`, `--json` |

The last two rows apply to `search`. Use ISO 8601 timestamps with a timezone. The global `--session-id` before the subcommand sets CLI attribution. The search subcommand's `--session-id-filter` matches the session ID on stored events.

```bash
garrison_logs search --status-code 500 --endpoint /api/v1/ --limit 20
garrison_logs search --request-id "$REQUEST_ID" --json
garrison_logs search --event-type log_access --action logs.cli.query --limit 20
garrison_logs tail --action auth.login_failed \
  --created-from "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --max-events 10
```

Typical event types include `api_request`, `security_event`, `user_action`, `state_change`, `system_event`, `error`, and `log_access`. For a `401`, refresh the authorized sign-in and verify the target origin and token precedence. For a `403`, check `audit:view` on the active account. For empty results, relax filters and check the time window, environment, and storage tier.

## Audit retention

The [Celery Beat schedule](../backend/app/tasks/celery_app.py) runs the retention check daily at 03:30 UTC. The default hot window is 30 days (`LOG_HOT_RETENTION_DAYS`), and the default archive window is 365 days (`LOG_ARCHIVE_RETENTION_DAYS`). Archived rows remain in PostgreSQL and can be queried with `search --storage-tier archive`. `LOG_STREAM_POLL_SECONDS` defaults to one second.

The scheduled job reports a bounded preview count by default. A row becomes a purge candidate after both the archive window and its recorded `retention_until` deadline expire. Rows without a deadline are retained. `LOG_PURGE_ENABLED` defaults to `false`. Enabling it requires the approved records policy, legacy deadline review, and recovery evidence.

Run `python scripts/preview_audit_retention.py` from the backend directory to list candidate IDs and deadlines and count records with missing deadlines. The preview reads from a read-only transaction and omits event payloads.

## Grafana, Loki, and Alloy

Services emit structured JSON to container stdout. [Alloy](../observability/alloy-config.alloy) discovers the environment's Compose containers, applies redaction, and ships logs to [Loki](../observability/loki-config.yml). Grafana uses Loki for operational queries. Loki's configured retention is 14 days. The PostgreSQL audit store has its own retention and backup policy.

Production Grafana is routed through the configured `GRAFANA_DOMAIN` HTTPS hostname. Staging Grafana uses its [staging subpath](../STAGING_DEPLOYMENT.md#target-and-isolation). Grafana disables anonymous access and public sign-up. Loki and Alloy use internal ports.

Use **Garrison Production Logs** for error counts, HTTP status distribution, and log search. Use **Garrison Incident Explorer** for latency and request or task correlation. The dashboard definitions live in [observability/grafana/dashboards](../observability/grafana/dashboards/).

The dashboard IDs are `garrison-production-logs` and `garrison-incident-explorer`. Record the dashboard ID and the relevant time range when escalating an incident.

```logql
{environment="production"} | json | message=~"unhandled_request_exception|task_failed"
{environment="production"} | json | request_id="req-123"
{environment="production", service="backend"} | json | message="http_request_completed" | duration_ms > 2000
{environment="production", service=~"celery_worker|celery_beat"} | json | message="task_retried"
```

Request, session, user, and task IDs are JSON fields queried after `| json`. Keep high-cardinality identifiers out of Loki labels. Keep request bodies, authorization headers, cookies, OTPs, credentials, and raw task arguments or results out of logging call sites. Nginx access logs omit query strings. The backend's redaction processor and Alloy's filters remove credential values, including S3 signing parameters, from supported structured and query-string formats.

### Alert delivery

[Provisioned alerts](../observability/grafana/provisioning/alerting/alerts.yml) cover unhandled failures, HTTP 5xx bursts, repeated Celery retries, sustained slow requests, and Loki/Alloy errors. Query failures enter the alerting state. Ordinary no-data periods remain healthy.

The default [Grafana contact point](../observability/grafana/provisioning/alerting/contact-point.yml) uses SMTP. To use the [useSend webhook](../observability/grafana/contact-points/usesend.yml), set these values in the private deployment environment. Use the full HTTPS email API endpoint and the authorized sender:

```dotenv
USESEND_API_URL=https://usesend.example.com/api/v1/emails
USESEND_API_KEY=<private-key>
SMTP_FROM_EMAIL=mailservice@garrisons.lk
GRAFANA_SMTP_ENABLED=false
GRAFANA_CONTACT_POINT_FILE=./observability/grafana/contact-points/usesend.yml
GRAFANA_USESEND_RECIPIENTS_JSON='["operations@example.com"]'
```

Recreate Grafana after the environment change. Verify firing and resolved notifications in the approved recipients' mailboxes before turning off the backend's exception emails through `EXCEPTION_EMAIL_ENABLED`.

### Incident fallback

Use rotated Docker logs while the collection pipeline is being restored. On production, define the [active Compose helper](OPERATIONS_AND_DEPLOYMENT.md#host-bootstrap-and-runner-maintenance), then run:

```bash
prod logs --since 30m backend celery_worker celery_beat
```

The [standalone HTTP monitor](../backend/scripts/health_monitor.py) can probe an external URL from a host with SMTP relay access. Grafana alerting and this monitor use separate delivery paths.

## Verify logging changes

From the backend environment, run the focused checks:

```bash
pytest -q tests/test_structured_logging.py tests/test_observability_config.py
```

These checks cover structured context and redaction, dashboard and alert configuration, retention, ports, pinned images, and database initialization. Check deployed service health and alert delivery when the change affects a live environment.

### Observability acceptance drill

1. Record the source SHA, deployed configuration identity, operator, reviewer, and isolated test environment. Verify authenticated Grafana access and confirm that Loki, Alloy, PostgreSQL, and the backend are reachable only through their intended network paths.
2. Generate a controlled HTTP failure and Celery retry with a shared synthetic correlation marker. Find both in **Garrison Incident Explorer** and record their request and task IDs. Include harmless credential-shaped markers to test application and Alloy redaction. Check the collected records for those markers without copying secrets into the evidence.
3. Exercise each provisioned rule with representative signals. Confirm the query result and configured evaluation window without changing the rule thresholds. Use the approved test contact point. Record firing and resolved mailbox receipts, rule ID, timestamps, and grouping behavior.
4. Interrupt collection briefly in the isolated environment. Keep the source container running, emit a unique marker, and check whether it arrives after recovery. Record the outage duration and the events observed or missing. Use the incident fallback when a collection gap is suspected.
5. Record the effective Loki operational retention and the separate database audit retention. Check an authorized archived-audit query and link the evidence to the release record. Keep any named operator and mailbox evidence in the approved restricted location.
