# Construction Internal Portal

Implementation workspace for the Construction Internal Portal.

All project documentation is maintained under [`docs/`](docs/). Start with the [documentation index](docs/00_README.md), then use [architecture](docs/ARCHITECTURE.md), [current database schema](docs/02_Database_Schema.md), [user stories](docs/user-stories/README.md), and the [implementation review](docs/USER_STORY_IMPLEMENTATION_REVIEW.md) as the source of truth.

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

This repository contains production implementation work across the Phase 1 user
stories in `docs/user-stories/`, including authentication, RBAC, projects/BOQ, daily
reports, approvals, uploads, documents, notifications, audit logs, operations,
inventory, suppliers, finance, analytics, PWA/offline primitives, and data
imports.

Strict completion status is tracked in `docs/USER_STORY_IMPLEMENTATION_REVIEW.md`.
That report uses a 100% acceptance standard: a story is marked complete only
when every acceptance criterion, business rule, UI/UX note, technical note, and
definition-of-done item has implementation evidence plus relevant verification
evidence.

Current local verification commands:

```bash
cd backend
pytest
ruff check .
mypy .

cd ../frontend
npm run lint
npm test
npm run build
```
