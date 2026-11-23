# Logging and Remote CLI Guide

For portal administration and credential-safe JSON log searches, see the [garrisonctl command guide](CLI_ADMINISTRATION.md).

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

A business audit stream also requires a durable signed-in session. It
checks the bearer token, session and current access before querying and
before sending a nonempty batch. Idle feeds recheck within five seconds
without renewing the session. An operator can hold two streams for at most
15 minutes each. A disconnect releases its slot, and the database records
the open and close times. To resume, use the last event UUID with the
same filters and a current bearer token. Both CLI tail commands accept
`--last-event-id <uuid>` and send it as a header.

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

The CLI's `login` subcommand starts a new OTP challenge on every invocation and prints the access token. In development it can use the returned development OTP. The application retains a staging-only OTP compatibility path, but staging is not an active deployment target. Production login uses a fresh delivered OTP for each challenge, so complete the authorized sign-in flow and supply its access token to the CLI. Keep tokens out of terminal captures and evidence files.

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

The scheduled job reports a bounded preview count by default. Expiry requires the approved `scheduled_expiry` policy at `AUDIT_RETENTION_POLICY_PATH` with the exact `AUDIT_RETENTION_POLICY_SHA256`, plus `LOG_PURGE_ENABLED=true`. The application retains unknown records, missing deadlines, future deadlines and records protected by a longer configured policy window. Leave expiry disabled until the named records owner approves the policy, legacy plan and recovery evidence. Policies requiring holds need the separately reviewed hold schema.

### Audit writer inventory

Application code writes `activity_log` through `AuditService.record`; it selects the event type from an explicit value, action prefix, and state-change data before applying the configured policy. The current producers are:

| Writer | Event/action classification input |
| --- | --- |
| HTTP audit middleware | `http.*` actions become `api_request`; optional health-check rows use the same writer. |
| Authentication services | `auth.*` actions become `security_event`. |
| Log search/export API | `logs.*` actions become `log_access`. |
| Application startup/shutdown and Celery maintenance | `system.*`, `celery.*`, and `maintenance.*` actions become `system_event`; explicitly reported failures retain their `error` event type. |
| Domain services: users, imports, reports, approvals, report exports, finance, suppliers, inventory, projects, documents and photos | Explicit event types are preserved; otherwise old/new values classify as `state_change`, and other actions as `user_action`. The policy must match the actual action and event type. |
| `scripts/seed.py::seed_activity_logs` | Six demo actions are explicitly recorded as `audit` through `AuditService.record`; the parent seed command refuses production and is limited to development, local, test or staging. |

Tests may construct `ActivityLog` directly to model legacy rows and edge cases; they are fixtures, not production writers. No other application-side `ActivityLog(...)` constructor is currently present. This inventory describes code paths, not owner-approved retention classes or durations. Until D-28 approves an exact mapping, unmatched rows keep a null deadline, are protected from purge and appear in the read-only reconciliation preview. Do not treat the hot/archive age settings as an approved business-audit retention policy.

Run `python scripts/preview_audit_retention.py --help` for the supported categories and paging inputs. The preview runs read-only and omits event payloads. For each continuation, pass the first page's `cutoff_utc` as `--cutoff` and the last page's `next_after` as `--after`. Use the same cutoff across all categories for one reconciliation inventory. For an approved policy, use `--extension-plan "$PRIVATE_PLAN"` to record the exact proposed deadline extensions. Review the plan with `python scripts/apply_audit_retention.py "$PRIVATE_PLAN"` in its default preview mode. Only a separately authorized apply with the exact plan hash and approval reference can write extensions. Each bounded batch reports its disposition and preserves existing longer deadlines.

## Grafana, Loki, and Alloy

Services emit structured JSON to container stdout. [Alloy](../observability/alloy-config.alloy) discovers the environment's Compose containers, applies redaction, and ships logs to [Loki](../observability/loki-config.yml). Grafana uses Loki for operational queries. Loki's configured retention is 14 days. The PostgreSQL audit store has its own retention and backup policy.

Production Compose configures a Grafana HTTPS virtual host from `GRAFANA_DOMAIN` and proxies it to the private Grafana service. External access to `grafana.portal.garrisons.lk` was **not ready** at the 2026-11-22 production check: the active DNS zone had no A, AAAA, or CNAME record for that name, and the certificate served by Nginx covered only `portal.garrisons.lk`. Normal TLS hostname verification for Grafana therefore failed. The read-only findings and next safe steps are in the [Grafana external-access readiness record](OPERATIONS_AND_DEPLOYMENT.md#grafana-external-access-readiness-2026-11-22). Do not use a TLS verification bypass as acceptance evidence. The legacy staging Compose file retains a subpath configuration, but it is not an active monitoring target.

The repository also contains prepared Grafana certificate-expiry monitor assets. They are not installed or active on production. After a trusted Grafana certificate is installed, the host check verifies the local Nginx listener with Grafana SNI and sends 30-day/7-day expiry alerts through the backend email service to `info@quadrate.lk`. Follow the deployment and test procedure in the operations readiness record; do not treat checked-in unit files as proof of live alert delivery.

Grafana disables anonymous access and public sign-up. Its port 3000 is not published on the production host; route it only through Nginx. Loki and Alloy also use internal ports.

Set `DOCKER_SOCKET_GID` in the deployment environment to the numeric group returned by `stat -Lc '%g' /var/run/docker.sock` on the Docker host. Recreate Alloy when this value changes so its supplementary group matches the socket. Alloy's container health check verifies socket access. To verify ingestion after recreation, use the existing private Loki connection and query a recent request ID from a permitted API read. Confirm that it appears under the expected environment and service labels.

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

[Provisioned alerts](../observability/grafana/provisioning/alerting/alerts.yml) cover unhandled failures, HTTP 5xx bursts, repeated Celery retries, sustained slow requests, and Loki/Alloy errors. The pipeline rule reads severity from Loki's logfmt records and Alloy's JSON records. Query failures enter the alerting state. Ordinary no-data periods remain healthy.

The production [Grafana contact point](../observability/grafana/provisioning/alerting/contact-point.yml) uses SMTP. Grafana alert notifications use the dedicated `info@quadrate.lk` recipient in both SMTP and the optional [useSend webhook](../observability/grafana/contact-points/usesend.yml). This is separate from `EXCEPTION_EMAIL_RECIPIENTS`, which remains for application exception notices. To use useSend, set these values in the private deployment environment. Use the full HTTPS email API endpoint and the authorized sender:

```dotenv
USESEND_API_URL=https://usesend.example.com/api/v1/emails
USESEND_API_KEY=<private-key>
SMTP_FROM_EMAIL=mailservice@garrisons.lk
GRAFANA_SMTP_ENABLED=false
GRAFANA_CONTACT_POINT_FILE=./observability/grafana/contact-points/usesend.yml
```

Recreate Grafana after the environment change. Verify firing and resolved notifications in the approved recipients' mailboxes before turning off the backend's exception emails through `EXCEPTION_EMAIL_ENABLED`.

### Incident fallback

Use rotated Docker logs while the collection pipeline is being restored. On production, define the [active Compose helper](OPERATIONS_AND_DEPLOYMENT.md#host-bootstrap-and-runner-maintenance), then run:

```bash
prod logs --since 30m backend celery_worker celery_beat
```

Treat raw Nginx error logs as restricted. An upstream error can include its original signed URL before Alloy redacts collected output. Use the redacted Loki view for sharing incident excerpts.

Run the [independent monitor](../backend/scripts/health_monitor.py) on the approved host outside the portal's failure domain. Use the [unsigned template](templates/monitor-profile.unsigned.json) to prepare the D-30 profile for owner review. The approved profile binds the environment, HTTPS readiness targets, allowed hosts, timings, sender and recipient groups, responders, and any bounded maintenance windows. Supply SMTP credentials for STARTTLS or implicit TLS, or a useSend key for the approved HTTPS endpoint, through the monitor's private environment. The production profile also requires the authenticated freshness check against the independent recovery destination. Give the monitor only the read-only backup credentials and the independently managed receipt authentication key.

The backup check authenticates the latest scheduled attempt before checking the last verified complete set. Both receipts must match the approved monitor profile's release SHA, environment, policy and configuration. A failed writer restart, a receipt from another release, an unavailable attempt record, or a status older than the approved backup interval plus publication allowance produces a failed check. When switching the profile to a new release, run and verify the scheduled capture for that release. Keep earlier recovery points available under the approved retention policy.

Keep an existing owner-only directory for incident state and write each structured receipt to a separate private path. The command exits nonzero for a failed check or delivery and rejects corrupt state or an overlapping invocation.

The monitor follows readiness redirects only within the target's HTTPS origin. A malformed or out-of-origin redirect fails that check. Other configured probes still run and the receipt records the outcome for each check.

If the notification credential is missing, the monitor still runs its probes and writes a receipt with `transport_ready=false`. It exits nonzero and preserves pending deliveries for retry once credentials are restored. A receipt with that flag cannot satisfy the final scheduled observation check. The flag reports local credential availability. Provider acceptance and responder receipt are verified through the delivery exercise.

The monitor tracks pending primary and escalation deliveries separately. A successful escalation does not clear a failed primary delivery. Retries keep the original message ID for each pending recipient, and resolution goes to recipients that received an incident notification. Keep the current monitor version if its state contains pending escalation. Older versions cannot read that state field.

Maintenance windows suppress delivery only for the listed checks. Probes and receipts continue, and the receipt records suppression. If an outage starts during maintenance and persists, the first probe after expiry attempts the initial notification. The acknowledgement clock starts at the first unsuppressed notification attempt, including a failed attempt so a broken primary route can still escalate. Keep the current monitor version when reusing state that records this clock.

```bash
cd backend
python -m scripts.health_monitor \
  --profile "$APPROVED_MONITOR_PROFILE" --profile-sha256 "$APPROVED_PROFILE_SHA256" \
  --state-dir "$MONITOR_STATE" \
  --receipt "$MONITOR_RUN_RECEIPT"
```

Supply the profile digest from the approved release record. After a responder has received the message, use `--acknowledge CHECK_ID --operator NAME --ack-ref REFERENCE --message-id ID` with the same profile, digest and state directory in place of `--receipt`. The acknowledgement records the received message identity and the local account that entered the attestation. Provider acceptance and human acknowledgement are separate evidence.

Generate the dedicated missing-ingestion rule with the same profile and digest and `--heartbeat-rule "$HEARTBEAT_RULE"`. Before provisioning that output, enable `LOG_HEALTHCHECKS` in the approved environment and verify the actual readiness completion stream in Loki at the approved cadence. The rule detects a missing readiness stream. The existing error-count rules retain their idle no-data behavior.

## Support request evidence

The draft [request evidence projection](../backend/app/services/support_request_logs.py)
reads only HTTP event metadata for an exact request ID. It uses an explicit
timezone-aware window of at most 24 hours, a five-second deadline and at most
100 returned events. It does not select comments, raw endpoints, request
bodies, account fields, or the audit JSON payload. Unknown methods and
invalid status codes become null. A truncated result is labelled.

In the isolated support portal, the browser calls
`GET /api/v1/support/cases/{case_id}/logs`. The server requires a live
technical session, `logs.runtime`, current membership of an open or
investigating case, and the exact request ID linked to that case. It allows
20 searches per minute per operator and commits an append-only access record
before returning evidence. Runtime source adapters beyond SQL HTTP metadata,
incident evidence, and approved exports remain separate work. Production
support ingress is disabled.

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
