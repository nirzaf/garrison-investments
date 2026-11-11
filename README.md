# Construction Internal Portal

Implementation workspace for the Construction Internal Portal.

All project documentation is maintained under [`docs/`](docs/). Start with the [documentation index](docs/README.md), then use the [architecture](docs/ARCHITECTURE.md), [roles and permissions](docs/ROLES_AND_PERMISSIONS.md), and [operations guide](docs/OPERATIONS_AND_DEPLOYMENT.md) as the source of truth.

## Local Development

1. Copy the environment template:

```bash
cp .env.example .env
```

2. Start the full local stack:

```bash
docker compose up --build
```

3. Apply database migrations:

```bash
docker compose exec backend alembic upgrade head
```

4. Open the services:

- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health
- MinIO console: http://localhost:9001

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

## Current Implementation Status

This repository contains the completed production implementation of the portal, including authentication, RBAC, projects/BOQ, daily reports, approvals, uploads, documents, notifications, audit logs, operations, inventory, suppliers, finance, analytics, PWA/offline primitives, and data imports. All core implementation packages are fully completed and verified.

Current local verification commands:

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
docker compose --env-file .env.example -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.example -f docker-compose.staging.yml config --quiet
```

Backend tests that need PostgreSQL, Redis, and MinIO intentionally skip when those services are unavailable. Use `pytest -q -rs` to make the skip reasons visible.

To run the full backend suite locally with the required services available:

```bash
docker compose up -d postgres redis minio

cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python - <<'PY'
import time

from minio import Minio

client = Minio(
    "localhost:9000",
    access_key="garrison_minio",
    secret_key="garrison_minio_password",
    secure=False,
)
bucket_name = "portal-files"
deadline = time.monotonic() + 60

while True:
    try:
        if not client.bucket_exists(bucket_name):
            client.make_bucket(bucket_name)
        break
    except Exception:
        if time.monotonic() >= deadline:
            raise
        time.sleep(2)
PY
pytest -q -rs
```

The observability regression suite validates structured fields and redaction, request-context
cleanup, Celery lifecycle records, immutable Grafana/Loki/Alloy image references, private port
exposure, Loki retention, Alloy label cardinality, dashboards, alert rules, database initialization,
and the staging hostname:

```bash
cd backend
pytest -q tests/test_structured_logging.py tests/test_observability_config.py
```
