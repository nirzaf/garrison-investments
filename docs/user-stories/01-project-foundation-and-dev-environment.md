# Project Foundation and Dev Environment

## Title
Project Foundation and Dev Environment

## User Story
As a development team member,
I want a consistent local development environment,
so that I can build, run, test, and debug the portal reliably.

## Description
Set up the backend, frontend, database, cache, object storage, and local configuration structure described in the technical specification. This story creates the baseline project skeleton without implementing business modules.

## Acceptance Criteria
1. Given I clone the repository,
   When I follow the documented setup command,
   Then the backend, frontend, PostgreSQL, Redis, and MinIO services start locally.

2. Given the backend service is running,
   When I open the health check endpoint,
   Then I receive a successful response with service and database status.

3. Given the frontend service is running,
   When I open the local frontend URL,
   Then I see the initial app shell or login route without runtime errors.

4. Given migrations are configured,
   When I run the migration command,
   Then the database schema is created from versioned migrations.

## Business Rules
- Local setup must not require production secrets.
- Environment variables must be documented through an example file.
- Services must be containerized for repeatable development.
- Runtime code must follow the documented FastAPI, React, PostgreSQL, Redis, and MinIO architecture.

## UI/UX Notes
- The initial frontend may be minimal but must load cleanly.
- The initial route should make it clear whether the user is unauthenticated or viewing a setup placeholder.
- Error screens should be user-friendly and not expose stack traces.

## Technical Notes
- Create Docker Compose services for backend, frontend, PostgreSQL, Redis, and MinIO.
- Scaffold FastAPI with health check, settings, database session, and API version routing.
- Scaffold React with TypeScript, Tailwind, router, and shared styling foundation.
- Configure Alembic for PostgreSQL migrations.
- Follow `../../ARCHITECTURE.md` directory structure, Docker Compose service layout, `/health` and `/health/readiness` checks, and backend request lifecycle.
- Use Python 3.12+, FastAPI, async SQLAlchemy 2.0, Pydantic V2, React 18, Vite, Tailwind, TanStack Query, Redis, Celery, PostgreSQL 16, and MinIO as the baseline stack.
- Keep all production secrets out of Git.

## Priority
High

## Dependencies
- Final choice of local package managers and runtime versions.
- Initial `.env.example` values for ports, database, Redis, MinIO, and JWT settings.

## Definition of Done
- Local services start from a clean checkout.
- Backend health check passes.
- Frontend loads without errors.
- Initial migration runs successfully.
- Setup instructions are documented.
- No production credentials are committed.
