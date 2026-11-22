# Garrisons Construction Internal Portal

**Lifecycle: Internal beta.** The project uses fast, risk-based iterations. The
[beta release policy](docs/BETA_RELEASE_POLICY.md) explains the small routine
release gate and the technical safeguards that remain mandatory.

The portal connects daily site reporting with project oversight, document control, inventory, supplier compliance, finance, and management reporting. It gives site teams a mobile-friendly way to capture work and gives office teams a shared record of approvals, stock movements, payments, and audit events.

[Production portal](https://portal.garrisons.lk) · [Release notes](https://github.com/nirzaf/garrison-investments/releases) · [Documentation index](docs/README.md)

## Implemented features

This is a source-code feature inventory, not a promise that every feature is
enabled for every account. Pending migrations, configuration, account grants,
and workflow-specific defects still affect the relevant feature; optional
formal-acceptance evidence does not block unrelated beta iterations. See the
[operations runbook](docs/OPERATIONS_AND_DEPLOYMENT.md) for current deployment
evidence and the [optional follow-up ledger](docs/POST_RELEASE_ACTIONS.md).

| Area | What the portal supports |
| --- | --- |
| Identity and account management | Password and emailed one-time code sign-in (with code restart and offline-storage prechecks before consuming an OTP), password reset and change, session refresh and logout, a read-only user profile, and authorized account controls for creating, deactivating, resetting, and changing the roles of other active users. |
| Dashboards and projects | Company-wide or scoped dashboards, recent activity, searchable projects, multi-row bill of quantities (BOQ) and milestone setup, project editing and team assignments, and task timelines with an accessible Gantt view. |
| Supervisor site updates | Capture attendance, overtime, work location, progress, delays, notes, and files. Supervisors can save, reopen, update, preview or download uploaded draft files (including original-only HEIC files), and submit drafts. |
| Engineer daily reports | Capture work completed, next-day plans, progress, safety and inspections, manpower, equipment, materials, and media. Report submission verifies linked supervisor updates. Returned reports retain their verified evidence and report number. Engineers can reopen returned reports with reviewer feedback, revise them, and resubmit. Reviewers can approve or return reports, inspect approval history, and download approved report PDFs. |
| Approvals | A report approval inbox, a workflow inbox, and an outbox for the current user’s submissions. Eligible actors can approve, reject with a reason, or delegate when the owning workflow permits. The active role policy denies generic overrides and invoice decisions. Reminders and notifications track pending work. |
| Documents and photos | Searchable document library with matching filter counts, replacement versions with explicit approval, authorized previews with in-dialog link refresh and downloads, and photo and attachment uploads. Authorized authors can remove eligible draft media. The current role policy blocks recovery of deleted media. HEIC files are available as originals. File access uses time-limited signed URLs. |
| Inventory and stores | Warehouses and project stores, consumables and asset-tagged equipment, stock by location, receipts, transfers, returns, adjustments, and movement history. Multi-line material requests support approval, quantity-selected partial reservation and issue, and cancellation of unissued stock. Low-stock alerts and report-linked material consumption support reconciliation. |
| Suppliers | Supplier register and compliance edits, deactivation that preserves history, technical data sheet (TDS) maintenance, and expiry reminders. |
| Finance | Authorized directors can review invoice details, attachments, recorded payments, and project budget comparisons. The active policy denies invoice and payment mutations. |
| Analytics and exports | Scoped analytics with filters for project, date range, location, and department where supported. Download project progress and material usage as XLSX files or a management summary as PDF. |
| HR and workforce | Employee directory and organization, recruitment with private CV review, onboarding and probation decisions, personnel documents, letter previews, attendance and timesheets, leave, staff self-service, and controlled account provisioning and offboarding. See the [HR guide](docs/HR_WORKFORCE.md). |
| Data imports | Downloadable templates, CSV and XLSX validation previews, synchronous and background processing, batch status, and import history for users, projects, suppliers, materials, BOQ, opening stock, and document metadata. Document binaries are uploaded through the document library. |
| Notifications and guidance | Notification history with direct links to target workflows, unread counts, read and mute controls, email through useSend or SMTP, a permission-based in-app manual with dedicated HR Manager guidance, and Launch readiness information. |
| Offline and file reporting | Installable progressive web app (PWA), responsive screens, photo file selection, account-owned local drafts, and file uploads that resume after reconnecting. Valid daily report drafts can sync without files, and revision checks protect newer server changes. |
| Audit and operations | Business and security audit records, an audit and security UI for authorized users, filtered operational log search and streaming through the API and remote CLI, structured application logs, Grafana dashboards and alerting, and encrypted backups with restore procedures. |

### Roles and access

Each account has one role. Route permissions, project membership, record ownership, and workflow state determine the actions available on a given record. The [role and permission guide](docs/ROLES_AND_PERMISSIONS.md) describes the full matrix.

| Role | Main responsibilities |
| --- | --- |
| Managing Director | Company-wide user, project, reporting, inventory, supplier, document, finance, audit, and dashboard privileges. |
| Operations Director | Company-wide user, project, reporting, inventory, supplier, document, finance, audit, and dashboard privileges. |
| Group Project Manager | Project management, scoped dashboards, report review and approval, inventory visibility, and document viewing. |
| MEP Project Manager | Project management, scoped dashboards, report review and approval, inventory visibility, supplier management, and document viewing. |
| Quantity Surveyor | Scoped dashboard, report submission, inventory viewing, supplier management, and document viewing. |
| Senior Site Supervisor | Assigned-project viewing, scoped dashboard, report submission, inventory viewing, and document viewing. |
| Site Supervisor | Assigned-project viewing, scoped dashboard, report submission, inventory viewing, and document viewing. |
| HR Manager | Workforce oversight, HR reviews, protected employee records, company/scoped dashboards, and authorized site-report review. |
| Administrative Executive | User-directory reading, company/scoped dashboards, inventory viewing, supplier management, and document viewing. |

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
- **Background work.** Workers handle queued exports, imports, notifications, and maintenance. Celery Beat schedules outbox dispatch, approval reminders, late-report checks, low-stock and supplier alerts, retention jobs, and daily and monthly database backups. These database backups do not prove recovery of referenced file objects; the full recovery set and restore drill remain separate acceptance gates. Scheduler times use UTC. Business dates use the configured timezone, which defaults to `Asia/Qatar`.

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

Grafana uses its configured virtual host when DNS and TLS are in place. Business audit records and application-side operational events are stored in PostgreSQL. Authorized users can search or stream them through the [remote log CLI](docs/LOGGING_AND_REMOTE_CLI.md) and its API. The [runbook](docs/OPERATIONS_AND_DEPLOYMENT.md#3-operations-backup-restore) covers log retention, encrypted backups, and isolated restores.

### CI and production deployment

```mermaid
flowchart TB
    change["Pull request or push to main"] --> ci["Isolated self-hosted CI<br/>Lint, types, API contract, tests, build, Compose"]
    ci --> gate{"Successful push CI for<br/>main on this repository?"}
    gate -->|"Yes"| runner["Self-hosted Hostinger runner<br/>garrison-production"]
    gate -->|"No"| stop["Stop before deployment"]
    runner --> release["Verify commit, CI jobs, runtime config, TLS/keys,<br/>and LOG_PURGE_ENABLED=false; build and activate"]
    release --> smoke{"Public readiness and<br/>served asset hashes pass?"}
    smoke -->|"Yes"| receipt["Record the active release"]
    smoke -->|"No"| rollback["Restore a compatible release or stop writers for forward recovery"]
```

[CI](.github/workflows/ci.yml) runs on isolated self-hosted Linux x64 runners tagged `garrison-ci`, with persistent dependency caches and disposable PostgreSQL, Redis, and object-storage fixtures. CI does not receive production secrets, production Docker access, or the Hostinger production runner. The fast-main candidate requires five jobs on a push to `main` (backend lint/types/OpenAPI, frontend lint/types/tests/build, Compose validation, and both backend integration shards); pull requests and manual CI keep the complete seven-job suite, including both Chrome browser shards. The [production workflow](.github/workflows/deploy.yml) runs after eligible successful CI for the current `main` commit on the separate Hostinger runner. The [host release script](deploy/hostinger-release.sh) verifies the upstream CI run and attempt, the exact workflow-specific required job set, current `main` commit, host file ownership/permissions, effective runtime configuration (including mounted TLS/JWT key files, stateful Compose baseline, and `LOG_PURGE_ENABLED=false`), and compatible Alembic heads. For routine `technical-checks-v1` releases, the candidate path applies a reachable pending Alembic upgrade under the deployment lock, skips migration when the schema already matches, and omits the synchronous pre-deployment backup; scheduled backups remain configured and the accepted migration data-loss risk is documented. It publishes the frontend, verifies the public readiness endpoint and served asset hashes, and records `Deployed — Formal Acceptance Pending`. See the [deployment runbook](docs/OPERATIONS_AND_DEPLOYMENT.md#production-deployments-from-github-actions) for the current live snapshot and candidate installation state.

The [beta release policy](docs/BETA_RELEASE_POLICY.md) defines routine release checks. Optional formal-acceptance evidence and owner decisions are tracked in [post-release actions](docs/POST_RELEASE_ACTIONS.md); they are not universal deployment blockers. Stateful migrations and production operations still follow the [maintenance runbook](docs/OPERATIONS_AND_DEPLOYMENT.md#production-maintenance). Staging is not an active release target; see the [retirement notice](STAGING_DEPLOYMENT.md).

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

The seed command prints the local Managing Director demo email. The development configuration can display the OTP in the sign-in form. Production uses the [first-Managing-Director bootstrap](docs/OPERATIONS_AND_DEPLOYMENT.md#post-deploy-verification), private signing keys, and a configured mail provider. Use sample data only in isolated development or test environments.

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

Use [.env.example](.env.example) as the local configuration reference and the [runbook](docs/OPERATIONS_AND_DEPLOYMENT.md) for production settings, mail, signing keys, and backup encryption. Keep credentials in private environment files. Fresh Compose setups use PostgreSQL 19.0 with the versioned `pgdata19` volume. Existing PostgreSQL 18 data must be migrated with the [PostgreSQL 18-to-19 procedure](docs/OPERATIONS_AND_DEPLOYMENT.md#upgrade-postgresql-18-to-190) before switching the database image or volume.

For terminal administration, see the [garrisonctl command guide](docs/CLI_ADMINISTRATION.md).

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

The Google Chrome suite uses synthetic accounts, a separate `garrison_browser_test` database, and its own Redis database and object bucket. It exercises offline report recovery, supervisor draft submission, and authorized role changes and auditing. With the disposable services running, prepare its database once and run the suite from the repository root:

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
  npx playwright install chrome
  BROWSER_TEST_PYTHON="$PWD/../backend/.venv/bin/python" npm run test:browser
)
```

Validate production Compose with the example configuration:

```bash
docker compose --env-file .env.example -f docker-compose.prod.yml config --no-env-resolution --quiet
```

The legacy staging Compose file is not a deployment or acceptance target. CI retains a focused compatibility test for remaining legacy configuration.

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
| [`frontend/`](frontend/) | React, TypeScript, Vite, and Tailwind UI, generated API types, service worker, and Google Chrome browser tests. |
| [`backend/`](backend/) | FastAPI routers, domain services, SQLAlchemy repositories and models, Alembic migrations, Celery tasks, operator scripts, and Pytest suite. |
| [`nginx/`](nginx/) and [Compose files](docker-compose.prod.yml) | Reverse proxy, service definitions, networks, and persistent volumes. |
| [`observability/`](observability/) | Alloy and Loki configuration, Grafana dashboards, provisioning, and alert contact points. |
| [`deploy/`](deploy/) and [`.github/workflows/`](.github/workflows/) | Host release script, CI, and production deployment workflow. |
| [`docs/`](docs/) | Architecture, access rules, operations, post-release governance backlog, API contract, schema reference, and import templates. |
