# Operations Runbook

## Environments

- `staging`: automatic deployment from the `develop` branch.
- `production`: deployment from the `main` branch or manual workflow dispatch.

Production approval is enforced through the GitHub `production` environment. Configure the Operation Manager as a required reviewer in repository settings before enabling production deploys.

## Required GitHub Secrets

### Staging

- `STAGING_HOST`
- `STAGING_USER`
- `STAGING_SSH_KEY`
- `STAGING_APP_PATH`

### Production

- `PRODUCTION_HOST`
- `PRODUCTION_USER`
- `PRODUCTION_SSH_KEY`
- `PRODUCTION_APP_PATH`

## Deployment Flow

1. Merge feature work through pull requests.
2. CI runs backend lint, type checks, migrations, tests, frontend lint, formatting, tests, build, and Docker image build.
3. Merging to `develop` deploys staging automatically.
4. Merging to `main` starts production deployment and waits for the GitHub `production` environment approval gate.
5. The deployment runs `docker compose -f docker-compose.prod.yml up -d --build`, applies Alembic migrations, and checks `/health`.

## Backup Procedure

The backend container includes `scripts/backup.py`.

Daily backup:

```bash
docker compose -f docker-compose.prod.yml exec -T backend python scripts/backup.py
```

Monthly archive:

```bash
docker compose -f docker-compose.prod.yml exec -T backend python scripts/backup.py --monthly
```

Required environment variables:

- `DATABASE_URL`
- `MINIO_ENDPOINT`
- `MINIO_ROOT_USER`
- `MINIO_ROOT_PASSWORD`
- `MINIO_BUCKET`
- `BACKUP_ENCRYPTION_PASSWORD`
- `BACKUP_RETENTION_DAYS`
- `MONTHLY_BACKUP_RETENTION_MONTHS`

Daily backups are retained for 30 days by default. Monthly archives are retained for 12 months by default. Restore tests must be performed monthly using the latest backup.

## Restore Test Procedure

1. Download the latest encrypted backup from MinIO.
2. Decrypt it using the configured backup encryption password.
3. Restore into an isolated PostgreSQL database.
4. Confirm the schema loads, core tables are queryable, and the application can pass `/health` against the restored database.
5. Record the restore test date, operator, backup object name, and result.

The repository includes an executable evidence helper for the restore drill. Use it first
in validation-only mode to confirm the dump is readable:

```bash
docker compose -f docker-compose.prod.yml exec -T backend \
  python scripts/restore_dry_run.py \
  --backup-file /tmp/latest-backup.sql.gz \
  --output docs/launch_evidence/restore-dry-run.md
```

For a full isolated restore, provide `RESTORE_DATABASE_URL` or pass
`--restore-database-url` to load the dump with `psql --single-transaction` and write the
same evidence file.

## Launch Evidence Capture

After staging or production deployment, capture a durable launch record:

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
  --uat-signoff docs/launch_signoff/uat.md \
  --template-signoff docs/launch_signoff/templates.md
```

Validate production migration spreadsheets before running imports:

```bash
docker compose -f docker-compose.prod.yml exec -T backend \
  python scripts/validate_import_sources.py \
  --source users=/imports/users.xlsx \
  --source projects=/imports/projects.xlsx \
  --source suppliers=/imports/suppliers.xlsx \
  --source materials=/imports/materials.xlsx \
  --source boq=/imports/boq.xlsx \
  --source documents=/imports/documents.xlsx \
  --source opening_stock=/imports/opening_stock.xlsx \
  --output docs/launch_evidence/import-validation.md \
  --check
```

## Rollback

1. Identify the last known good Git commit.
2. SSH into the target server.
3. Check out the known good commit.
4. Rebuild and restart with `docker compose -f docker-compose.prod.yml up -d --build`.
5. Apply only backward-compatible migrations. If a migration rollback is required, run the matching Alembic downgrade after confirming data impact.
6. Verify `/health` and key UAT smoke paths.

## Operational Alerts

Phase 1 alert routing should send business-critical outages to Admin or technical support and the Operation Manager. Until a monitoring provider is selected, `/health` and container status are the minimum uptime checks.

The backend image includes a provider-neutral health monitor for the minimum uptime
check. Run it from cron, systemd timer, or external scheduler:

```bash
docker compose -f docker-compose.prod.yml exec -T backend \
  python scripts/health_monitor.py \
  --url https://portal.example.com/health \
  --url https://portal.example.com/health/readiness \
  --alert-to admin@example.com,operations@example.com
```

The command exits non-zero on failed checks and sends readable email alerts through the
configured SMTP server.
