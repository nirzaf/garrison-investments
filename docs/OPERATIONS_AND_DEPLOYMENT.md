# Operations and Deployment Guide

This document serves as the unified runbook for environments, deployments, configuration, UAT sign-off, operations, backups, and launch evidence for the Construction Internal Portal.

## 1. Environments & Deployment Prerequisites

- **`staging`**: Deployment target for pre-production validation.
- **`production`**: Deployment target for approved launch and release runs.

### Deployment Prerequisites
- Linux host or equivalent Docker runtime with Docker and Docker Compose installed.
- DNS record for the production domain pointing to the host.
- TLS certificate files under `nginx/ssl/` if HTTPS is enabled.
- Production environment file copied to the repository root as `.env`.
- Runtime access to Nginx, backend, Celery worker, Celery beat, PostgreSQL, Redis, and MinIO containers.
- Compose defaults to digest-pinned Silo and mcli because the original MinIO Docker Hub images
  are no longer available. The `minio` service name, S3 settings, and volume path stay the same.
  Hosts using a local image or private mirror can set `OBJECT_STORAGE_IMAGE` and
  `OBJECT_STORAGE_CLIENT_IMAGE`. Before switching an existing host, back up its storage volume
  and verify application objects, backups, and Loki reads on an isolated copy. Keep the original
  volume and image for rollback. See the [Silo migration guide](https://silo.pigsty.io/compatibility/migration/).
- A Docker address pool that does not overlap the `backend_proxy` subnet
  (`NGINX_BACKEND_PROXY_SUBNET`, default `172.29.254.0/29`). If it overlaps an existing network,
  Compose fails with `invalid pool request: Pool overlaps with other one on this address space`;
  change `NGINX_BACKEND_PROXY_SUBNET`, `NGINX_BACKEND_PROXY_DYNAMIC_RANGE` **and**
  `NGINX_BACKEND_PROXY_IP` together so the trusted-proxy list still matches the proxy.

**WARNING**: Do not commit production `.env` files, JWT private keys, SMTP credentials, database passwords, MinIO passwords, or backup encryption passwords.

### Required `.env` Variables

Use production values for every placeholder before deployment.

```env
APP_NAME="Construction Internal Portal"
APP_ENV=production
DEBUG=false
API_V1_PREFIX=/api/v1
BACKEND_CORS_ORIGINS=https://your-domain.example
FRONTEND_BASE_URL=https://your-domain.example

POSTGRES_DB=garrison_portal
POSTGRES_USER=<production-db-user>
POSTGRES_PASSWORD=<strong-production-db-password>
DATABASE_URL=postgresql+asyncpg://<production-db-user>:<strong-production-db-password>@postgres:5432/garrison_portal

REDIS_URL=redis://redis:6379/0

MINIO_ENDPOINT=minio:9000
MINIO_ROOT_USER=<production-minio-user>
MINIO_ROOT_PASSWORD=<strong-production-minio-password>
MINIO_BUCKET=portal-files
MINIO_SECURE=false

JWT_ALGORITHM=RS256
JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private_key
JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public_key
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_HOURS=24
OTP_EXPIRE_MINUTES=10
ACCOUNT_LOCKOUT_MINUTES=30
AUTH_FAILED_ATTEMPT_LIMIT=3

SMTP_HOST=<smtp-host>
SMTP_PORT=587
SMTP_USERNAME=<smtp-username>
SMTP_PASSWORD=<smtp-password>
SMTP_USE_TLS=true
SMTP_FROM_EMAIL=no-reply@garrisons.lk
SMTP_FROM_NAME="Garrisons Investments"
EXCEPTION_EMAIL_RECIPIENTS=admin@garrisons.lk

REPORT_EMAIL_RECIPIENTS=admin@garrisons.lk
REPORT_PDF_TEMPLATE_NAME=company-standard

BACKUP_ENCRYPTION_PASSWORD=<strong-backup-encryption-password>
BACKUP_LOCAL_DIR=/tmp/garrison-backups
BACKUP_RETENTION_DAYS=30
MONTHLY_BACKUP_RETENTION_MONTHS=12

MONITOR_ALERT_RECIPIENTS=admin@garrisons.lk

# Optional overrides (defaults shown)
EXCEPTION_EMAIL_ENABLED=true
NOTIFICATION_RETENTION_DAYS=90
LOG_HOT_RETENTION_DAYS=30
LOG_ARCHIVE_RETENTION_DAYS=365
LOG_STREAM_POLL_SECONDS=1.0
LOG_INSTANCE_ID=<host-or-container-identifier>
LOG_SOURCE_SERVICE=backend-api
LOG_LEVEL=INFO
LOG_HEALTHCHECKS=false

GRAFANA_DOMAIN=logs.your-domain.example
GRAFANA_ADMIN_USER=<grafana-admin-user>
GRAFANA_ADMIN_PASSWORD=<strong-grafana-admin-password>
GRAFANA_DB_PASSWORD=<strong-grafana-database-password>
LOKI_MINIO_ACCESS_KEY=<loki-service-access-key>
LOKI_MINIO_SECRET_KEY=<strong-loki-service-secret>
TRUSTED_PROXY_IPS=127.0.0.1,::1
BUSINESS_TIMEZONE=Asia/Qatar
```

---

## 2. Deployment Flow

1. Merge feature work through pull requests.
2. CI runs backend lint, type checks, migrations, tests, frontend lint, formatting, tests, build, and Docker image build.
3. The deployment owner runs the selected staging deployment process from the approved commit.
4. The Operation Manager or delegated release approver signs off before production deployment.
5. The production deployment applies Alembic migrations, starts the updated Compose services, and checks `/health`.

### Upgrade an existing PostgreSQL 16 database

Fresh environments initialize PostgreSQL 18.6 automatically. For an existing environment,
schedule a maintenance window and rehearse the migration in staging first. The PostgreSQL 18
image mounts `pgdata` at `/var/lib/postgresql` and refuses to start when it detects the legacy
PostgreSQL 16 data directory in that volume.

1. Record the current Compose project, database volume, and deployed revision. Stop application,
   worker, and Grafana writes before taking the final backups. Keep PostgreSQL 16 available to
   create and verify dumps of both the application database and Grafana's database. Capture the
   roles and grants needed to restore their ownership and permissions.
2. Create a fresh volume for PostgreSQL 18 and select it in a Compose override by setting
   `volumes.pgdata.name` to the new volume's name. Keep the same Compose project and include the
   override in every command for the upgraded environment.
3. Start PostgreSQL 18, provision the required roles and empty databases, then restore both
   dumps. Use PostgreSQL 18 client tools and fail the restore on any SQL error.
4. Check the Alembic revision, compare representative record counts and permissions with the
   source, and verify the application and Grafana before resuming writes. Keep the PostgreSQL 16
   volume and backups. Before reopening writes, rollback is the prior revision with its original
   volume. After reopening writes, account for any new data before rolling back.

### Post-Deploy Verification

Run these checks from the repository root on the deployment host:

```bash
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.prod.yml up -d --wait postgres
docker compose -f docker-compose.prod.yml run --rm --no-deps --build backend alembic upgrade head
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
PORTAL_DOMAIN=portal.garrisons.lk
curl --fail --resolve "${PORTAL_DOMAIN}:443:127.0.0.1" "https://${PORTAL_DOMAIN}/health"
curl --fail --resolve "${PORTAL_DOMAIN}:443:127.0.0.1" "https://${PORTAL_DOMAIN}/health/readiness"
curl --fail "https://${GRAFANA_DOMAIN}/api/health"
docker compose -f docker-compose.prod.yml run -T --rm --no-deps --pull never \
  -v "$PWD/docs/import_templates:/docs/import_templates:ro" \
  backend python scripts/validate_import_sources.py --check
docker compose -f docker-compose.prod.yml exec -T backend python scripts/backup.py --target all
```

Before starting production, create DNS for `GRAFANA_DOMAIN` and install a certificate whose SAN covers
that hostname. The `grafana_db_init` and `loki_minio_init` jobs are idempotent and must exit successfully.

On an empty production database, have the deployment operator create the approved first administrator
after migrating the schema. Run from an interactive terminal:

```bash
docker compose -f docker-compose.prod.yml exec backend python scripts/bootstrap_admin.py \
  --email admin@example.com --full-name "Portal Administrator"
```

The command prompts for a temporary password, records the account creation, and requires the
administrator to change the password after sign-in. Verify OTP delivery for the administrator as
part of the launch check.
Grafana, Loki, and Alloy must report healthy; none of their internal ports should be published.

Before changing a running environment, run the repository checks:

```bash
cd backend
pytest -q tests/test_structured_logging.py tests/test_observability_config.py
ruff check .
mypy .

cd ../frontend
npm run lint
npm run api:types:check
npm test
npm run build

cd ..
docker compose --env-file .env.example -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.example -f docker-compose.staging.yml config --quiet
```

The Grafana database initializer uses PostgreSQL `ON_ERROR_STOP` and idempotent role/database checks.
Any non-zero `grafana_db_init` or `loki_minio_init` exit is a deployment failure; inspect the job
logs instead of manually bypassing the dependency.

### Local production-compose rehearsal

To rehearse the production stack on a workstation without touching a live environment:

1. In a scratch copy of the release, copy `.env.example` to `.env`, set `APP_ENV=production`,
   and configure test-only passwords and signing keys. Both Compose interpolation and the
   service-level `env_file` must read this same `.env` file.
2. Mount the generated RSA pair at the paths in `JWT_PRIVATE_KEY_PATH` and `JWT_PUBLIC_KEY_PATH`.
   Put a test certificate in `nginx/ssl/` with the hostname in its SAN.
3. In a Compose override, bind nginx to loopback, remap its ports, and move `NGINX_BACKEND_PROXY_SUBNET`,
   `NGINX_BACKEND_PROXY_DYNAMIC_RANGE`, and `NGINX_BACKEND_PROXY_IP` together when the default
   pool overlaps an existing Docker network.
4. Use a unique Compose project name. Start PostgreSQL with `up -d --wait postgres`, run
   `run --rm --no-deps --build backend alembic upgrade head`, then start the stack with
   `up -d --build --wait`. Pass the same project name and both Compose files to every command.
5. Verify `/` serves the SPA, `/health` returns ok, and a presigned `/portal-files/` object renders
   in a same-origin iframe while `/` itself refuses framing.

Presigned object URLs sign the exact `Host` header the browser sends. Both nginx configs forward
`$http_host` (not `$host`) on `/portal-files/` so a `MINIO_PUBLIC_ENDPOINT` that includes a
non-default port still validates; `$host` strips the port and MinIO rejects the request with
`SignatureDoesNotMatch`.

---

## 3. Operations, Backup & Restore

### Scheduled Background Jobs (Celery Beat)

The Celery beat container runs these schedules automatically (defined in `backend/app/tasks/celery_app.py`, all times UTC):

| Task | Schedule | Purpose |
| --- | --- | --- |
| `dispatch_task_outbox` | Every minute | Queue report exports recorded by successful approvals |
| `run_database_backup` | Daily 01:00 | Encrypted daily database backup to MinIO |
| `run_database_backup` (monthly) | 1st of month 02:00 | Monthly archive backup |
| `check_late_reports` | Hourly | Detect and notify late daily reports |
| `process_approval_reminders` | Hourly | Send approval reminder notifications |
| `check_low_stock` | Hourly | Low-stock inventory alerts |
| `cleanup_old_notifications` | Daily 03:00 | Purge notifications older than `NOTIFICATION_RETENTION_DAYS` |
| `archive_and_purge_logs` | Daily 03:30 | Move hot logs to archive tier and purge expired archives |
| `check_supplier_tds_expiry` | Daily 04:00 | Alert on expiring supplier TDS documents |

### Backup Procedure

The backend container includes `scripts/backup.py`. Scheduled backups require
`BACKUP_ENCRYPTION_PASSWORD`. The CLI also requires it unless the operator explicitly
passes `--allow-unencrypted`, which records a warning before writing the backup.

* **Daily application and Grafana backup:**
  `docker compose -f docker-compose.prod.yml exec -T backend python scripts/backup.py --target all`
* **Monthly archive:**
  `docker compose -f docker-compose.prod.yml exec -T backend python scripts/backup.py --target all --monthly`

Application backups retain their existing prefixes. Grafana metadata is stored under
`backups/grafana/daily` and `backups/grafana/monthly`. Daily backups are retained for 30 days and
monthly archives for 12 months. Loki data is operational, retained for 14 days by the Compactor, and
is not copied into a second backup.

### Restore Test Procedure
1. Download the latest encrypted backup from MinIO.
2. Decrypt it using the configured backup encryption password.
3. Restore into an isolated PostgreSQL database.
4. Confirm the schema loads, core tables are queryable, and the application passes `/health`.
5. Record the restore test date, operator, backup object name, and result.

Run the same isolated restore procedure for the latest Grafana dump, then verify that its tables are
readable. The dump preserves grants. Before restoring it, create the roles referenced by those grants
in the isolated PostgreSQL instance as `NOLOGIN` roles. Keep the running Grafana instance connected
to its normal database.

Use the validation script to confirm the dump is readable:
```bash
docker compose -f docker-compose.prod.yml exec -T backend \
  python scripts/restore_dry_run.py \
  --backup-file /tmp/latest-backup.sql.gz \
  --output docs/launch_evidence/restore-dry-run.md
```

### Operational Alerts

Phase 1 alert routing sends business-critical outages to Admin and the Operation Manager.
Grafana uses SMTP by default. For an installation that uses useSend, configure the following
in the private deployment environment file:

```dotenv
USESEND_API_URL=https://usesend.example.com/api/v1/emails
USESEND_API_KEY=<useSend-api-key>
SMTP_FROM_EMAIL=mailservice@garrisons.lk
GRAFANA_SMTP_ENABLED=false
GRAFANA_CONTACT_POINT_FILE=./observability/grafana/contact-points/usesend.yml
GRAFANA_USESEND_RECIPIENTS_JSON='["admin@example.com","operations@example.com"]'
```

Use an HTTPS API URL, an authorized sender, and a JSON array of the approved alert recipients.
Recreate Grafana after changing the environment file and verify delivery of firing and resolved
notifications before disabling `EXCEPTION_EMAIL_ENABLED`.

Run the independent HTTP monitor from a location with access to the portal and its configured SMTP relay:

```bash
docker compose -f docker-compose.prod.yml exec -T backend \
  python scripts/health_monitor.py \
  --url https://portal.example.com/health \
  --url https://portal.example.com/health/readiness \
  --alert-to admin@example.com,operations@example.com
```

### Remote Log Access

Use the remote log CLI from the backend container or a trusted operator workstation to search and stream centralized application logs:

```bash
cd backend
python scripts/log_cli.py --base-url https://portal.example.com --token-file .log-token search --severity ERROR
```

For full login, search, filter, archive, and live tail usage, see [LOGGING_AND_REMOTE_CLI.md](./LOGGING_AND_REMOTE_CLI.md).

### Payment overage report

Run this read-only command to list active invoices whose active payments exceed the invoice total.
It emits one JSON line per invoice for finance review.

```bash
docker compose -f docker-compose.prod.yml exec -T backend \
  python scripts/report_payment_overages.py --i-understand
```

### Offline draft duplicate review

Run `python scripts/repair_offline_duplicates.py` from the backend to list candidate pairs.
The default mode reads the database and prints IDs for review. To consolidate a reviewed pair,
stop portal writes and run the same command with `--apply --keep KEEP_ID --duplicate DUPLICATE_ID`.
The script rechecks both drafts, moves their photo and retry references, and soft-deletes the
duplicate in one transaction. Production reads and writes require `--i-understand`.

### Inventory reservation review

Run `python scripts/report_inventory_reservation_drift.py --i-understand` from the production
backend to list balances for review. Compare the recorded balance with the open request quantities
and manual reserve movements before reconciling inventory.

Migration `202605300003_repair_inventory_reservations` recomputes the two derived columns —
`material_request_lines.reserved_quantity` and `inventory_location_stock.reserved_qty` — from the
open request quantities and the manual reserve movements, then validates the stock balance checks
so they cover historical rows too. It prints `rows_recomputed=` per table and is safe to re-run
(a second pass reports `0`).

A negative `on_hand_qty` cannot be derived from any record, so `VALIDATE CONSTRAINT` aborts and the
migration rolls back rather than inventing stock. Reconcile those balances with the drift report
above, then re-run `alembic upgrade head`.

### Rollback
1. Identify the last known good Git commit.
2. Check out the known good commit on the host.
3. Rebuild and restart with `docker compose -f docker-compose.prod.yml up -d --build`.
4. Apply backward-compatible migrations (or downgrade if safe).
5. Verify `/health`.
6. If the observability stack is the failure source, set `EXCEPTION_EMAIL_ENABLED=true`, stop
   Grafana/Loki/Alloy, and continue incident diagnosis from rotated Docker JSON logs.

---

## 4. UAT Scenarios & Launch Readiness

### Seed Data
For a new staging environment, configure a temporary `SEED_DEFAULT_PASSWORD` in its private
environment file, then run:
```bash
docker compose exec backend python scripts/seed.py
```
### UAT Scenarios
1. **Admin** logs in, creates a user, updates the role, and verifies audit entries.
2. **Operation Manager** opens dashboard, confirms active projects, reports, documents, and notifications.
3. **Project Manager** reviews reports, rejects/approves, and tests PDF exports.
4. **Civil Engineer** submits reports, updates rejected reports, uploads photos, checks validation.
5. **Civil Supervisor** submits a site update.
6. **Mobile validation** on iOS Safari and Android Chrome.

### Blocker Classification
| Severity | Action |
| --- | --- |
| **Blocker** (Data loss, broken submit) | Must be fixed before sign-off |
| **High** (Failed exports, permission leak) | Must be fixed or formally accepted by MD |
| **Medium** (Layout defect, copy issue) | Can ship with tracked follow-up |
| **Low** (Cosmetic polish) | Backlog candidate |

---

## 5. Launch Evidence Capture & Sign-Off

Record deployment runs, approvers, health checks, backup objects, and sign-offs in a durable record:

```bash
mkdir -p docs/launch_evidence
docker compose -f docker-compose.prod.yml run -T --rm --no-deps --pull never \
  -v "$PWD/docs:/docs" \
  backend python scripts/launch_evidence.py \
  --target production \
  --output /docs/launch_evidence/production-launch.md \
  --health-url https://portal.example.com/health \
  --readiness-url https://portal.example.com/health/readiness \
  --approver "Operation Manager" \
  --backup-object backups/daily/application-YYYYMMDDTHHMMSSZ.sql.gz.enc \
  --restore-log /docs/launch_evidence/restore-dry-run.md \
  --uat-signoff /docs/launch_signoff/uat.md
```

### Sign-Off Checklist
* Production deployment approver is the Operation Manager.
* Staging deployment completed from the current commit.
* `/health` and `/health/readiness` return healthy responses.
* Daily backup completed successfully.
* Restore dry run completed.
* Browser/device UAT completed.
