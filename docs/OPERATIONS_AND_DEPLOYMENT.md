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
5. The production deployment runs `docker compose -f docker-compose.prod.yml up -d --build`, applies Alembic migrations, and checks `/health`.

### Post-Deploy Verification

Run these checks from the repository root on the deployment host:

```bash
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml exec -T backend alembic upgrade head
curl --fail http://localhost/health
curl --fail http://localhost/health/readiness
curl --fail "https://${GRAFANA_DOMAIN}/api/health"
docker compose -f docker-compose.prod.yml exec -T backend python scripts/validate_import_sources.py --check
docker compose -f docker-compose.prod.yml exec -T backend python scripts/backup.py --target all
```

Before starting production, create DNS for `GRAFANA_DOMAIN` and install a certificate whose SAN covers
that hostname. The `grafana_db_init` and `loki_minio_init` jobs are idempotent and must exit successfully.
Grafana, Loki, and Alloy must report healthy; none of their internal ports should be published.

---

## 3. Operations, Backup & Restore

### Scheduled Background Jobs (Celery Beat)

The Celery beat container runs these schedules automatically (defined in `backend/app/tasks/celery_app.py`, all times UTC):

| Task | Schedule | Purpose |
| --- | --- | --- |
| `run_database_backup` | Daily 01:00 | Encrypted daily database backup to MinIO |
| `run_database_backup` (monthly) | 1st of month 02:00 | Monthly archive backup |
| `check_late_reports` | Hourly | Detect and notify late daily reports |
| `process_approval_reminders` | Hourly | Send approval reminder notifications |
| `check_low_stock` | Hourly | Low-stock inventory alerts |
| `cleanup_old_notifications` | Daily 03:00 | Purge notifications older than `NOTIFICATION_RETENTION_DAYS` |
| `archive_and_purge_logs` | Daily 03:30 | Move hot logs to archive tier and purge expired archives |
| `check_supplier_tds_expiry` | Daily 04:00 | Alert on expiring supplier TDS documents |

### Backup Procedure

The backend container includes `scripts/backup.py`.

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

Run the same isolated restore procedure for the latest Grafana dump, restore it into a temporary
database owned by a temporary restricted user, and verify that its tables are readable. Do not point a
running Grafana instance at the restore-test database.

Use the validation script to confirm the dump is readable:
```bash
docker compose -f docker-compose.prod.yml exec -T backend \
  python scripts/restore_dry_run.py \
  --backup-file /tmp/latest-backup.sql.gz \
  --output docs/launch_evidence/restore-dry-run.md
```

### Operational Alerts
Phase 1 alert routing sends business-critical outages to Admin and the Operation Manager.
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

### Rollback
1. Identify the last known good Git commit.
2. Check out the known good commit on the host.
3. Rebuild and restart with `docker compose -f docker-compose.prod.yml up -d --build`.
4. Apply backward-compatible migrations (or downgrade if safe).
5. Verify `/health`.

---

## 4. UAT Scenarios & Launch Readiness

### Seed Data
For testing/staging only, run:
```bash
docker compose exec backend python scripts/seed.py
```
Seeded accounts use the password `ChangeMe123!`.

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
docker compose -f docker-compose.prod.yml exec -T backend \
  python scripts/launch_evidence.py \
  --target production \
  --output docs/launch_evidence/production-launch.md \
  --health-url https://portal.example.com/health \
  --readiness-url https://portal.example.com/health/readiness \
  --approver "Operation Manager" \
  --backup-object backups/daily/latest.sql.gz \
  --restore-log docs/launch_evidence/restore-dry-run.md \
  --uat-signoff docs/launch_signoff/uat.md
```

### Sign-Off Checklist
* Production deployment approver is the Operation Manager.
* Staging deployment completed from the current commit.
* `/health` and `/health/readiness` return healthy responses.
* Daily backup completed successfully.
* Restore dry run completed.
* Browser/device UAT completed.
