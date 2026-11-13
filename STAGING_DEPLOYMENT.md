# Staging Deployment

[Documentation index](docs/README.md) · [Production runbook](docs/OPERATIONS_AND_DEPLOYMENT.md) · [Logging and alerts](docs/LOGGING_AND_REMOTE_CLI.md)

Use this manual procedure when an approved change needs a separate deployment for validation. The [production GitHub Actions workflow](.github/workflows/deploy.yml) targets Hostinger production.

## Target and isolation

The commands use the settings from the [previous staging deployment](docs/PRODUCTION_READINESS_REVIEW.md#staging-findings-recorded-in-the-review). Confirm the current host, DNS, TLS, ports, and volume names with the operator before reusing them.

| Item | Example staging setting |
| --- | --- |
| Portal | [erp.garrisons.lk](https://erp.garrisons.lk) |
| Grafana | [erp.garrisons.lk/grafana/](https://erp.garrisons.lk/grafana/) |
| Host workspace | `/opt/garrison-investments-staging` |
| Compose project | `garrisonstg` |
| Origin routing | Host Nginx terminates TLS for the staging hostname and proxies the app to `127.0.0.1:3310` and `/grafana/` to `127.0.0.1:3311`. |
| Persistence | The project uses its own PostgreSQL, Redis, S3-compatible storage, and observability volumes. [Staging Compose](docker-compose.staging.yml) specifies their names and ports. |

Use the authorized staging SSH destination from the operator's host configuration. Keep other virtual hosts and Compose projects outside the staging rollout.

## Private environment

Use [.env.example](.env.example) for names and the [shared configuration guide](docs/OPERATIONS_AND_DEPLOYMENT.md#environment-and-configuration) for signing keys, mail, backups, and alerting. Store staging values in the private `.env.staging` on the host. Each release directory must make that file available to Compose interpolation and the service-level `env_file`.

Set these staging-specific values:

```dotenv
APP_ENV=staging
DEBUG=false
FRONTEND_BASE_URL=https://erp.garrisons.lk
BACKEND_CORS_ORIGINS=https://erp.garrisons.lk
GRAFANA_DOMAIN=erp.garrisons.lk
MINIO_ENDPOINT=minio:9000
MINIO_SECURE=false
MINIO_PUBLIC_ENDPOINT=erp.garrisons.lk
MINIO_PUBLIC_SECURE=true
```

Set `DOCKER_SOCKET_GID` to the host's Docker socket group from `stat -Lc '%g' /var/run/docker.sock`. Alloy uses that supplemental group and discovers containers for the staging project. The application prefixes outgoing messages with `[Testing]`. Use approved staging recipients and credentials. If the approved UAT procedure uses `STAGING_LOGIN_OTP`, set the six-digit value in the private environment. The backend checks this value only for login with `APP_ENV=staging`.

## Deploy a reviewed revision

Run the [relevant repository checks](README.md#verification) and identify the source SHA. From the repository root, validate Compose interpolation using the example values:

```bash
docker compose --env-file .env.example -f docker-compose.staging.yml config --no-env-resolution --quiet
```

Transfer that committed tree into a fresh release directory on the staging host. A Git archive of the selected SHA keeps the release independent of local untracked files. Keep the previous release available for rollback and keep the shared secret files outside the transferred tree.

In the candidate release directory, link `.env.staging` to the host's private staging environment and define this Bash helper:

```bash
ln -s /opt/garrison-investments-staging/.env.staging .env.staging
staging() {
  docker compose -p garrisonstg --env-file .env.staging \
    -f docker-compose.staging.yml "$@"
}
staging config --quiet
```

If the environment still has PostgreSQL 16 data, use the [major-version upgrade procedure](docs/OPERATIONS_AND_DEPLOYMENT.md#upgrade-an-existing-postgresql-16-database) and keep the environment's volume override in the helper. For a migration affecting existing data, take a verified staging backup and coordinate when to quiesce writers. Start the database, apply migrations, and deploy:

```bash
staging up -d --wait postgres
staging run --rm --no-deps --build backend alembic upgrade head
staging up -d --build --wait
staging ps --all
```

Confirm the Grafana database and Loki storage initializer jobs completed successfully. After a staging virtual-host edit, check the host Nginx configuration with `nginx -t` before reloading it. Use sample data only for a designated staging dataset. The [local seed workflow](README.md#getting-started) describes the seeder and its password setting.

## Verify the release

```bash
curl -fsS http://127.0.0.1:3310/health/readiness
curl -fsS https://erp.garrisons.lk/health/readiness
curl -fsS https://erp.garrisons.lk/grafana/api/health
```

In a browser, test the affected workflow with an authorized staging account. For file flows, upload or open a fresh file and confirm the signed URL uses `https://erp.garrisons.lk/portal-files/`. For mail changes, confirm that the approved mailbox receives the message and complete the workflow it supports. Verify other virtual hosts after any shared ingress change. Record the source SHA and results in the [launch evidence](docs/OPERATIONS_AND_DEPLOYMENT.md#5-launch-evidence-capture--sign-off).
