# Garrisons Construction Internal Portal

The portal connects daily site reporting with project oversight, document control, inventory, supplier compliance, finance, and management reporting. It gives site teams a mobile-friendly way to capture work and gives office teams a shared record of approvals, stock movements, payments, and audit events.

[Production portal](https://portal.garrisons.lk) · [Release notes](https://github.com/nirzaf/garrison-investments/releases) · [Documentation index](docs/README.md)

## Implemented features

| Area | What the portal supports |
| --- | --- |
| Identity and account management | Password and emailed one-time code sign-in, password reset and change, forced password change for new or reset accounts, session refresh and logout, a user profile, and administrator controls for creating, deactivating, resetting, and changing the roles of other active users. |
| Dashboards and projects | Company-wide or scoped dashboards, recent activity, searchable projects, project setup with bill of quantities (BOQ) and milestones, project team assignments, timelines, and tasks. |
| Supervisor site updates | Capture attendance, overtime, work location, progress, delays, notes, and files. Supervisors can save, reopen, update, and submit drafts. |
| Engineer daily reports | Capture work completed, next-day plans, progress, safety and inspections, manpower, equipment, materials, and media. Reports can reference supervisor updates. Engineers can reopen returned reports with reviewer feedback, revise them, and resubmit. Reviewers can approve or return reports, inspect approval history, and download approved report PDFs. |
| Approvals | A review inbox for daily reports and workflow requests, including material requests, invoices, and document-related approvals. Eligible approvers can approve, reject with a reason, delegate, or override where the workflow permits. Reminders and notifications track pending work. |
| Documents and photos | Searchable document library, version history and approval, authorized previews and downloads, photo and attachment uploads, and original, compressed, thumbnail, or watermarked image views where the format supports them. File access uses time-limited signed URLs. |
| Inventory and stores | Warehouses and project stores, consumables and asset-tagged equipment, stock by location, receipts, transfers, returns, adjustments, and movement history. Material requests support approval, reservation, issuance, and cancellation. Low-stock alerts and report-linked material consumption support reconciliation. |
| Suppliers | Supplier records, activation status, technical data sheet (TDS) uploads and downloads, expiry dates, and scheduled expiry reminders. |
| Finance | Invoice records, supporting attachments, approval workflows, project budget summaries through the API, and payment recording against approved invoices. The system tracks partial and full payment and checks the outstanding balance. |
| Analytics and exports | Scoped analytics with filters for project, date range, location, and department where supported. Download project progress and material usage as XLSX files or a management summary as PDF. |
| Data imports | Downloadable templates, CSV and XLSX validation previews, synchronous and background processing, batch status, and import history for users, projects, suppliers, materials, BOQ, opening stock, and document metadata. Document binaries are uploaded through the document library. |
| Notifications and guidance | Notification history, unread counts, read and mute controls, email delivery through useSend or SMTP, role-specific in-app manuals, a permission reference, and a launch acceptance checklist. |
| Mobile and offline reporting | Installable progressive web app (PWA), responsive screens, camera-friendly file capture, local daily report drafts, and queued file uploads that retry after reconnecting. Retry protection ties queued uploads to the intended report. |
| Audit and operations | Business and security audit records, an audit and security UI for authorized users, filtered operational log search and streaming through the API and remote CLI, structured application logs, Grafana dashboards and alerting, and encrypted backups with restore procedures. |

### Roles and access

Each account has one role. Route permissions, project membership, record ownership, and workflow state determine the actions available on a given record. The [role and permission guide](docs/ROLES_AND_PERMISSIONS.md) describes the full matrix.

| Role | Main responsibilities |
| --- | --- |
| Admin | User and role administration, imports, security and audit, company oversight, and authorized workflow overrides. |
| General Manager | Company dashboards, cross-project oversight, approvals, analytics, and management reporting. |
| Operation Manager | Company operations, project setup and oversight, workflow review, and coordination across reports, stores, and finance. |
| Project Manager | Manage assigned projects and review their reports, documents, and workflow requests. |
| Civil Engineer | Prepare official daily reports for assigned projects, attach site evidence, and correct returned reports. |
| Civil Supervisor | Record and submit daily site updates and supporting evidence. |
| Store Keeper | Manage stock and assets, material requests, issuance, transfers, and supplier information within the assigned permissions. |
| Accounts | Work with invoices, attachments, payments, and finance reporting within the assigned permissions. |

## Architecture

### Production runtime

```mermaid
flowchart TB
    browser["Portal users<br/>React PWA, service worker, IndexedDB"]

    subgraph host["Hostinger VPS · Docker Compose"]
        direction TB
        nginx["Nginx<br/>HTTPS reverse proxy"]
        frontend[("Static SPA volume")]
        api["FastAPI / Uvicorn<br/>Routes, access checks, domain services"]
        beat["Celery Beat<br/>Scheduled jobs"]
        worker["Celery workers<br/>Exports, imports, notifications, backups"]
        postgres[("PostgreSQL<br/>Business data, audit, task outbox")]
        redis[("Redis<br/>Queues, job results, rate limits")]
        objects[("S3-compatible storage<br/>Uploads, exports, backups")]

        nginx -->|"Routes and assets"| frontend
        nginx -->|"/api and /health"| api
        nginx -->|"Signed /portal-files requests"| objects
        api -->|"SQLAlchemy repositories"| postgres
        api -->|"Store files and sign URLs"| objects
        api -->|"Rate limits and jobs"| redis
        beat -->|"Enqueue scheduled jobs"| redis
        redis -->|"Deliver queued jobs"| worker
        worker -->|"Update records"| postgres
        worker -->|"Store exports and backups"| objects
    end

    mail["Mail provider<br/>useSend HTTPS API or SMTP"]

    browser -->|"HTTPS"| nginx
    api -->|"One-time codes and transactional mail"| mail
    worker -->|"Notification email"| mail
```

- **Client and edge.** The React and TypeScript PWA uses the API for authenticated workflows. Nginx serves the compiled frontend, forwards API and health requests over the backend network, and proxies signed object requests.
- **Application and data.** FastAPI applies permission and scope checks before domain services access records or authorize files. PostgreSQL stores project, workflow, inventory, finance, audit, idempotency, and task outbox records. Redis supports Celery and authentication rate limits. The Compose service named `minio` exposes an S3-compatible API. The default image is Silo, with host overrides supported.
- **Background work.** Workers handle queued exports, imports, notifications, and maintenance. Celery Beat schedules outbox dispatch, approval reminders, late-report checks, low-stock and supplier alerts, retention jobs, and daily and monthly backups. Scheduler times use UTC. Business dates use the configured timezone, which defaults to `Asia/Qatar`.

### Observability and audit

```mermaid
flowchart TB
    app["API and worker stdout"] -->|"Structured logs"| logs["Docker logs"]
    logs --> alloy["Grafana Alloy<br/>Collect and redact"]
    alloy --> loki["Loki<br/>Centralized logs"]
    loki --> s3[("S3-compatible log storage")]

    operator["Operations staff"] -->|"HTTPS"| nginx["Nginx<br/>Grafana virtual host"]
    nginx --> grafana["Grafana<br/>Dashboards and alert rules"]
    grafana -->|"Query logs"| loki
    grafana --> db[("Grafana database<br/>PostgreSQL metadata")]
    grafana -->|"Firing and resolved alerts"| mail["useSend or SMTP"]
```

Grafana uses its configured virtual host when DNS and TLS are in place. Business audit records and application-side operational events are stored in PostgreSQL. Authorized users can search or stream them through the [remote log CLI](docs/LOGGING_AND_REMOTE_CLI.md) and its API. The [runbook](docs/OPERATIONS_AND_DEPLOYMENT.md#3-operations-backup--restore) covers log retention, encrypted backups, and isolated restores.

### CI and production deployment

```mermaid
flowchart TB
    change["Pull request or push to main"] --> ci["GitHub-hosted CI<br/>Lint, types, API contract, tests, build, Compose"]
    ci --> gate{"Successful push CI<br/>for the current main commit?"}
    gate -->|"Yes"| runner["Self-hosted Hostinger runner<br/>garrison-production"]
    gate -->|"No"| stop["Stop before deployment"]
    runner --> release["Verify the exact commit<br/>Build, check compatibility, and activate"]
    release --> smoke{"Public readiness and<br/>served asset hashes pass?"}
    smoke -->|"Yes"| receipt["Record the active release"]
    smoke -->|"No"| rollback["Restore the previous release"]
```

[CI](.github/workflows/ci.yml) runs on GitHub-hosted `ubuntu-latest` runners for pull requests and pushes to `main`. The [production workflow](.github/workflows/deploy.yml) runs after successful CI for the current `main` commit and uses the dedicated self-hosted Hostinger runner. The [host release script](deploy/hostinger-release.sh) checks the upstream CI run and commit, publishes the frontend, and verifies the public readiness endpoint and served asset hashes. Application service updates take encrypted backups before activation. Pending database migrations and changes to stateful services require the reviewed maintenance procedure in the [deployment runbook](docs/OPERATIONS_AND_DEPLOYMENT.md#production-deployments-from-github-actions).

The [launch checklist](docs/OPERATIONS_AND_DEPLOYMENT.md#5-launch-evidence-capture--sign-off) records release approval, backup and restore evidence, and browser and device acceptance. The [staging guide](STAGING_DEPLOYMENT.md) covers the separate staging target.

## Getting started

Install Docker with Compose v2. For native development or tests, use Python 3.14 and Node.js 24, matching the CI toolchain.

From a fresh checkout:

```bash
cp .env.example .env
docker compose up -d --wait postgres
docker compose run --rm --no-deps --build backend alembic upgrade head
docker compose up -d --build
```

| Local service | URL |
| --- | --- |
| Vite frontend | [localhost:3000](http://localhost:3000) |
| FastAPI Swagger UI | [localhost:8000/docs](http://localhost:8000/docs) |
| Health and readiness | [localhost:8000/health](http://localhost:8000/health), [localhost:8000/health/readiness](http://localhost:8000/health/readiness) |
| Nginx reverse proxy | [localhost:8080](http://localhost:8080) |
| Object storage console | [localhost:9001](http://localhost:9001) |

To load sample projects and accounts for a local walkthrough, set `SEED_DEFAULT_PASSWORD` in the local `.env` and run:

```bash
docker compose exec backend python scripts/seed.py
```

The seed command prints the local administrator email. The development configuration can display the OTP in the sign-in form. Production uses the [first-administrator bootstrap](docs/OPERATIONS_AND_DEPLOYMENT.md#post-deploy-verification), private signing keys, and a configured mail provider. Use sample data only in development, test, or an approved staging environment.

For native frontend and backend development, run PostgreSQL, Redis, and object storage in Compose. Keep ports 3000 and 8000 free for the native app processes. From the repository root:

```bash
docker compose up -d --wait postgres redis minio
cd backend
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
fastapi dev app/main.py
```

In a separate terminal:

```bash
cd frontend
npm ci
npm run dev
```

Use [.env.example](.env.example) as the local configuration reference and the [runbook](docs/OPERATIONS_AND_DEPLOYMENT.md) for production settings, mail, signing keys, and backup encryption. Keep credentials in private environment files. Existing PostgreSQL 16 volumes require the [database upgrade procedure](docs/OPERATIONS_AND_DEPLOYMENT.md#upgrade-an-existing-postgresql-16-database) before starting PostgreSQL 18.

Production uses HTTPS, short-lived JWT access tokens, rotating HTTP-only refresh cookies, and configured RS256 signing keys. Nginx is the public gateway for the portal. Database, queue, object storage, and observability services use private container ports. Configure the public object URL and trusted ingress addresses with the production proxy settings so signed downloads and client attribution work through Nginx.

## Verification

Run backend tests against disposable PostgreSQL, Redis, and S3-compatible services. The development Compose stack provides these on local ports 5432, 6379, and 9000. CI uses a dedicated PostgreSQL database and Moto for S3. Review skipped tests with `-rs`.

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
ruff check .
mypy .
python scripts/export_openapi.py --check
pytest -q -rs
```

```bash
cd frontend
npm ci
npm run lint
npm run api:types:check
npm test
npm run build
```

The Chromium suite uses synthetic accounts, a separate `garrison_browser_test` database, and its own Redis database and object bucket. It exercises offline report recovery, supervisor draft submission, and administrator role changes and auditing. With the disposable services running, prepare its database once and run the suite from the repository root:

```bash
docker compose exec postgres createdb -U garrison garrison_browser_test
(
  cd backend
  APP_ENV=test DATABASE_URL=postgresql+asyncpg://garrison:garrison_dev_password@127.0.0.1:5432/garrison_browser_test \
    .venv/bin/alembic upgrade head
)
(
  cd frontend
  npm ci
  npx playwright install chromium
  BROWSER_TEST_PYTHON="$PWD/../backend/.venv/bin/python" npm run test:browser
)
```

Validate both deployment Compose files with the example configuration:

```bash
docker compose --env-file .env.example -f docker-compose.prod.yml config --no-env-resolution --quiet
docker compose --env-file .env.example -f docker-compose.staging.yml config --no-env-resolution --quiet
```

### API contract changes

The API is versioned under `/api/v1`. [`docs/openapi.json`](docs/openapi.json) is the checked-in contract, and [`frontend/src/api/schema.d.ts`](frontend/src/api/schema.d.ts) is generated from it. After changing a route or schema, regenerate both and commit them together:

```bash
cd backend
.venv/bin/python scripts/export_openapi.py
cd ../frontend
npm run api:types
```

## Repository guide

| Path | Contents |
| --- | --- |
| [`frontend/`](frontend/) | React, TypeScript, Vite, and Tailwind UI, generated API types, service worker, and Chromium tests. |
| [`backend/`](backend/) | FastAPI routers, domain services, SQLAlchemy repositories and models, Alembic migrations, Celery tasks, operator scripts, and Pytest suite. |
| [`nginx/`](nginx/) and [Compose files](docker-compose.prod.yml) | Reverse proxy, service definitions, networks, and persistent volumes. |
| [`observability/`](observability/) | Alloy and Loki configuration, Grafana dashboards, provisioning, and alert contact points. |
| [`deploy/`](deploy/) and [`.github/workflows/`](.github/workflows/) | Host release script, CI, and production deployment workflow. |
| [`docs/`](docs/) | Architecture, access rules, operations, API contract, schema reference, and import templates. |

## Further reading

- [Architecture](docs/ARCHITECTURE.md) and [database schema](docs/schema/README.md)
- [Roles and permissions](docs/ROLES_AND_PERMISSIONS.md) and [import templates](docs/import_templates/)
- [Operations, deployment, backup, and UAT](docs/OPERATIONS_AND_DEPLOYMENT.md)
- [Staging deployment](STAGING_DEPLOYMENT.md) and [remote log CLI](docs/LOGGING_AND_REMOTE_CLI.md)
- [Historical production readiness review](docs/PRODUCTION_READINESS_REVIEW.md)
