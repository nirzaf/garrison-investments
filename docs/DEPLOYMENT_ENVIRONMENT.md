# Deployment Environment

Date: 2026-05-16

This checklist covers the current Docker Compose production deployment path. It lists
the infrastructure inputs and environment variables needed to run the portal without
including real secret values.

## Deployment Prerequisites

- Linux host or equivalent Docker runtime.
- Docker and Docker Compose installed on the deployment host.
- DNS record for the production domain pointing to the host.
- TLS certificate files under `nginx/ssl/` if HTTPS is enabled.
- Production environment file copied to the repository root as `.env`.
- Runtime access to the Nginx, frontend, backend, Celery worker, Celery beat,
  PostgreSQL, Redis, and MinIO containers.

Do not commit production `.env` files, JWT private keys, SMTP credentials, database
passwords, MinIO passwords, or backup encryption passwords.

## Required `.env`

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
DEV_EXPOSE_OTP=false
STAGING_LOGIN_OTP=

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
```

`SMTP_USERNAME`, `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`, and `SMTP_USE_TLS` are the
production names read by `backend/app/config.py`. The older `.env.example`
placeholders `SMTP_USER` and `SMTP_FROM` are development placeholders and should not
be used as the production source of truth.

`FRONTEND_BASE_URL` is used by backend-generated notification emails to append absolute
links back into the deployed portal. Set it to the public app origin without a path,
for example `https://portal.example.com`.

## Optional And Script-Only Variables

| Variable | Used by | Purpose |
| --- | --- | --- |
| `RESTORE_DATABASE_URL` | `backend/scripts/restore_dry_run.py` | Target isolated database for a full restore drill. |
| `SMTP_HOST` | `backend/scripts/health_monitor.py` | SMTP host for health-monitor failure alerts. |
| `SMTP_PORT` | `backend/scripts/health_monitor.py` | SMTP port for health-monitor failure alerts. |
| `SMTP_FROM_EMAIL` | `backend/scripts/health_monitor.py` | Sender address for health-monitor failure alerts. |
| `MONITOR_ALERT_RECIPIENTS` | `backend/scripts/health_monitor.py` | Comma-separated alert recipients for uptime/readiness failures. |

## Post-Deploy Verification

Run these checks from the repository root on the deployment host:

```bash
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec -T backend alembic upgrade head
curl --fail http://localhost/health
docker compose -f docker-compose.prod.yml exec -T backend python scripts/validate_import_sources.py --check
docker compose -f docker-compose.prod.yml exec -T backend python scripts/backup.py
```

Record the deployment run, approval, health/readiness checks, backup object, restore
drill, and sign-off evidence in the launch evidence files described by
`docs/09_Production_Readiness_Evidence.md`.
