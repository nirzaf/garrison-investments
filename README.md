# Construction Internal Portal

Implementation workspace for the Construction Internal Portal.

All project documentation is maintained under [`docs/`](docs/). Start with the [documentation index](docs/README.md), then use the [architecture](docs/ARCHITECTURE.md), [roles and permissions](docs/ROLES_AND_PERMISSIONS.md), [operations guide](docs/OPERATIONS_AND_DEPLOYMENT.md), and [production readiness review](docs/PRODUCTION_READINESS_REVIEW.md) as the source of truth. Staging-specific hosts, TLS, and rollback steps live in [STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md).

## Local Development

1. Copy the environment template:

```bash
cp .env.example .env
```

2. Start the database, then wait until it accepts connections:

```bash
docker compose up -d --wait postgres
```

3. Apply database migrations:

```bash
docker compose run --rm --no-deps --build backend alembic upgrade head
docker compose up -d --build
```

4. Load sample data (optional; creates the role-based demo users, projects, BOQ, inventory, and
   finance records used for local walkthroughs). The script prints the seeded admin email and
   temporary password when it finishes:

```bash
docker compose exec backend python scripts/seed.py
```

5. Open the services:

- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health
- MinIO console: http://localhost:9001
- Nginx, the full stack behind the reverse proxy: http://localhost:8080

`docker compose up` also starts the `celery_worker` and `celery_beat` services. The worker runs
report exports, image variants, email delivery, and import jobs; beat schedules the daily and
monthly backups, late-report and low-stock checks, approval reminders, and log/notification
cleanup.

Production and staging add Grafana, Loki, and Alloy for container-log aggregation. Applications
continue writing structured JSON to stdout, Docker retains rotated local logs, and PostgreSQL
`activity_log` remains the authoritative business and audit record. See the
[logging guide](docs/LOGGING_AND_REMOTE_CLI.md) and
[operations guide](docs/OPERATIONS_AND_DEPLOYMENT.md).

## Local Commands

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
fastapi dev app/main.py
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Existing PostgreSQL 16 volumes require a data migration before starting the PostgreSQL 18 image.
See the [database upgrade runbook](docs/OPERATIONS_AND_DEPLOYMENT.md#upgrade-an-existing-postgresql-16-database).

## API Contract

[`docs/openapi.json`](docs/openapi.json) is the committed contract and
`frontend/src/api/schema.d.ts` is generated from it. Nothing regenerates the spec automatically:
after changing backend routes or schemas, export the current spec from the running backend's
`/openapi.json`, save it to `docs/openapi.json`, then run `npm run api:types` in `frontend/` and
commit both files. `npm run api:types:check` fails if the checked-in types no longer match the
checked-in spec.

## Current Implementation Status

This repository contains the completed production implementation of the portal, including authentication, RBAC, projects/BOQ, daily reports, approvals, uploads, documents, notifications, audit logs, operations, inventory, suppliers, finance, analytics, PWA/offline primitives, and data imports. The [production readiness review](docs/PRODUCTION_READINESS_REVIEW.md) records the final verdict and the pre-release checklist.

Local verification is the same gate [CI](.github/workflows/ci.yml) enforces on pull requests and pushes to `main`:

```bash
cd backend
pytest -q -rs
ruff check .
mypy .

cd ../frontend
npm run lint
npm run api:types:check
npm test
npm run build

cd ..
docker compose --env-file .env.example -f docker-compose.prod.yml config --no-env-resolution --quiet
docker compose --env-file .env.example -f docker-compose.staging.yml config --no-env-resolution --quiet
```

Database tests skip when PostgreSQL is unavailable. Run the full suite against disposable development services, including an S3 endpoint for report and document tests. Use `pytest -q -rs` to see skip reasons.

To run the full backend suite locally with the required services available:

```bash
docker compose up -d postgres redis minio

cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
pytest -q -rs
```

No manual bucket creation is needed: the storage services check for and create the `portal-files`
bucket on first write, as do `scripts/seed.py` and `scripts/push_to_storage.py`.

The `backend-tests` CI job runs Pytest and the Playwright browser suite against PostgreSQL,
Redis, and Moto's S3 test server. The browser suite starts the API and serves a production
frontend build. It uses a separate `garrison_browser_test` database and synthetic accounts.

To run the browser suite locally, start the same test services on ports 5432, 6379 and 9000.
Create the dedicated database and apply the backend migrations to it before running the tests:

```bash
docker compose exec postgres createdb -U garrison garrison_browser_test
cd backend
APP_ENV=test DATABASE_URL=postgresql+asyncpg://garrison:garrison_dev_password@127.0.0.1:5432/garrison_browser_test .venv/bin/alembic upgrade head
cd ../frontend
npm ci
npx playwright install chromium
BROWSER_TEST_PYTHON="$PWD/../backend/.venv/bin/python" npm run test:browser
```

The observability regression suite validates application-side structured fields and redaction
(including nested-secret classes, free-text credential patterns, and depth-limited truncation of
deeply nested payloads), request-context cleanup, health-check suppression, Celery lifecycle
records, pipeline-side credential redaction in Alloy, immutable and digest-pinned
Grafana/Loki/Alloy image references, private port exposure, Loki retention, Alloy label
cardinality, dashboards, alert rules, database initialization, and the staging hostname:

```bash
cd backend
pytest -q tests/test_structured_logging.py tests/test_observability_config.py
```

## Continuous Integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and every push to
`main`, cancelling superseded runs on the same ref:

| Job | Runtime | Steps | Failure blocks? |
|---|---|---|---|
| `backend-static` | Python 3.14 | `ruff check .`, `mypy .`, OpenAPI contract check | yes |
| `frontend` | Node 24 | `npm run lint`, `api:types:check`, `npm test`, `npm run build` | yes |
| `compose-validate` | — | renders `docker-compose.prod.yml` and `docker-compose.staging.yml` with `.env.example` | yes |
| `backend-tests` | Python 3.14, Node 24, PostgreSQL 18.6, Redis 7, Moto S3 | Migrate test databases, run Pytest and Playwright Chromium | yes |

Whether a passing job is a merge requirement is set in branch protection, not in the workflow file.

The CI jobs mirror the local verification commands above, so a failure can be reproduced with the
same commands before pushing. Note the `backend-tests` job applies migrations first because the
suite has no schema-creating fixture.
