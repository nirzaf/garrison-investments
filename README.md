# Construction Internal Portal

Implementation workspace for the Construction Internal Portal described in `ARCHITECTURE.md` and the planning documents under `docs/`.

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

This repository currently implements story `TO-DO/01-project-foundation-and-dev-environment.md`:

- Docker Compose development services
- FastAPI app skeleton with `/health`, `/health/readiness`, and `/api/v1`
- PostgreSQL async SQLAlchemy configuration
- Alembic baseline migration for `users`
- React + Vite + TypeScript + Tailwind starter shell
- Environment template without production secrets
