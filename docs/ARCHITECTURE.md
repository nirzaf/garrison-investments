# Garrisons Portal architecture

The portal supports construction project delivery, field reporting, approvals, inventory, documents, and finance. Start with the [feature inventory](../README.md#implemented-features) for user-facing behavior and the [documentation index](README.md) for related guides.

- [Runtime and data flow](#runtime-and-data-flow)
- [API contract](#api-contract)
- [Workflow invariants](#workflow-invariants)
- [Implementation map](#implementation-map)
- [Security and scoping](#security-and-scoping)
- [Deployment and verification](#deployment-and-verification)

## Runtime and data flow

The [production runtime diagram](../README.md#production-runtime) shows the public ingress, application services, data stores, and mail provider.

1. Nginx terminates HTTPS, serves the built React application with a client-route fallback, and proxies `/api/` and `/health` to FastAPI. The production configuration also forwards signed object requests under `/portal-files/`. [Production Nginx configuration](../nginx/nginx.prod.conf)
2. The browser mounts React Router, Auth Context, and TanStack Query. Pages handle workflow state and call domain API modules through a shared Axios client. The client attaches the in-memory access token, coordinates refresh, and limits automatic transport retries to safe methods. [Browser entry point](../frontend/src/main.tsx) · [Routes](../frontend/src/App.tsx) · [HTTP client](../frontend/src/api/client.ts)
3. FastAPI initializes settings, signing keys, request context, auth rate limiting, request auditing, and exception handlers. Routers validate request data with Pydantic, resolve the actor and database session, and call domain services. Services enforce workflow rules and control transaction boundaries. Repositories and direct SQLAlchemy queries in services provide persistence. [Application factory](../backend/app/main.py) · [API dependencies](../backend/app/api/dependencies.py) · [Async session](../backend/app/database.py)
4. PostgreSQL stores application state, audit and operational events, idempotency keys, and the report task outbox. Object storage holds media, documents, exports, and backups. Separate internal and public S3 client settings let services write through the private endpoint and generate URLs for the public proxy. [Schema index](schema/README.md) · [Storage client](../backend/app/services/storage_service.py) · [Production Compose](../docker-compose.prod.yml)
5. Redis supports authentication rate limiting and serves as the Celery broker and result backend. Celery workers handle scheduled jobs, imports, report export, and email. Beat schedules the task outbox dispatcher, backups, workflow reminders, and maintenance in UTC. Business-date validation uses the separately configured portal timezone. [Rate limiter](../backend/app/middleware/rate_limit.py) · [Task schedule](../backend/app/tasks/celery_app.py) · [Settings](../backend/app/config.py)

Portal email can use useSend or SMTP through `EmailService`. Login and password-reset codes send during the auth request. Notification and report email tasks record delivery state and retry transport failures. [Mail transport](../backend/app/services/email_service.py) · [Auth service](../backend/app/services/auth_service.py) · [Email tasks](../backend/app/tasks/email.py)

## API contract

| Question | Source |
| --- | --- |
| Which endpoints and response schemas exist? | [Checked-in OpenAPI](openapi.json), [router registration](../backend/app/api/v1/router.py), and [Pydantic schemas](../backend/app/schemas/) |
| What types do browser API modules use? | [Generated TypeScript contract](../frontend/src/api/schema.d.ts) and [domain clients](../frontend/src/api/) |
| How do I regenerate or verify the contract? | [API contract commands](../README.md#api-contract-changes) and [backend contract test](../backend/tests/test_openapi_contract.py) |
| How are errors represented? | [Exception models](../backend/app/utils/exceptions.py), [exception handlers](../backend/app/main.py), and [frontend error handling](../frontend/src/api/errors.ts) |

The normal API prefix is `/api/v1`. Application and validation errors carry `detail`, `error_code`, and `errors`. Check the specific operation for its paging contract. Some list operations return an envelope with a total, while inventory lists expose totals in `X-Total-Count`. `/health` and `/health/readiness` are outside the API prefix. Readiness checks database connectivity and returns HTTP 503 when the database is unavailable. [Inventory routes](../backend/app/api/v1/inventory.py) · [Health endpoints](../backend/app/main.py)

## Workflow invariants

### Project setup and scheduling

- Project setup validates the full milestone and BOQ input before writing the project. Milestone names and BOQ codes must be unique after normalization. A BOQ milestone link must resolve within the submitted setup. PostgreSQL stores quantities and rates as decimals and the backend calculates the planned amount. [Project setup service](../backend/app/services/project_service.py) · [Project form](../frontend/src/pages/projects/ProjectCreateForm.tsx)
- Project and task edit screens send the revision from the record they opened. The service serializes project edits, assignments, and task changes on the parent project. Existing project metadata and assignment API clients may omit the revision during transition. The task update endpoint requires it. A task keeps one predecessor in the same project, and the service rejects cycles. [Project endpoints](../backend/app/api/v1/projects.py) · [Timeline](../frontend/src/pages/projects/ProjectTimeline.tsx)

### Field reporting and offline recovery

- Civil Supervisors draft and submit their own updates for assigned projects. Engineer report submission verifies selected updates from the same project and records who verified them. Official daily reports have their own draft, submission, and decision path. Report submission assigns the report number, and a rejection returns the report to draft with reviewer feedback. [Supervisor updates](../backend/app/services/reporting_service.py) · [Daily reports](../backend/app/services/report_service.py)
- Approval locks the report row before checking its state. It records the decision, consumes report materials, and writes a PDF task outbox entry within the transaction. The scheduled dispatcher publishes pending entries. The export task stores the PDF and can queue email to configured report recipients. [Report service](../backend/app/services/report_service.py) · [Outbox dispatcher](../backend/app/tasks/outbox.py) · [Report tasks](../backend/app/tasks/report.py)
- The service worker caches the app shell. IndexedDB stores local daily report drafts and queued uploads. A queue flush persists the latest valid owned draft even without attachments. It records the server identity and revision before uploading files. An older local revision cannot overwrite a newer server report. The browser and service-worker fallback share the same grouping, claim, and retry behavior. [Offline queue](../frontend/src/api/offlineQueue.ts) · [Service worker](../frontend/public/sw.js)
- Queued report files use the same byte checks in the app and worker. A blocked file stays available for removal with its reason. The queue records the first expected report revision before sending. If the response is lost, a replay uses the same file key and expected revision, and an exact receipt advances the draft base and clears the queued copy together. [Queued upload rules](../frontend/public/report-file-sync.js)
- Offline draft and upload records are partitioned by the verified user and application/API origin. A session generation fences queued operations in the browser and worker. Sign-out clears the current user's local drafts and queued uploads after confirmation. Session expiry suspends sync and keeps the records for that user to resume after sign-in. [Offline storage](../frontend/src/api/offlineDb.ts) · [Browser session](../frontend/src/api/browserSession.ts)
- Report creation and photo upload accept an optional `Idempotency-Key`. A PostgreSQL record scopes the key by user and route and binds it to the resource in the write transaction. Replays can recover the original resource after a dropped response. [Idempotency service](../backend/app/services/idempotency.py) · [Idempotency tests](../backend/tests/test_idempotency.py)

### Approvals, inventory, and finance

- The approvals screen separates daily report decisions, the workflow inbox, and the current user’s outbox. A conflicting decision refreshes the record and its action controls. Entity-backed approvals are opened by their owning workflow. The generic approval service enforces request-specific delegation rules and an open-request uniqueness constraint. Pending decisions, reminders, escalation, and Admin override are implemented there. [Approvals UI](../frontend/src/pages/approvals/ApprovalInboxPage.tsx) · [Approval service](../backend/app/services/approval_service.py)
- Inventory records movements and maintains stock and reservation quantities by item and location. A receipt requires an active destination and a quantity representable to three decimal places. The stock forms retain the original request and key when the result is unconfirmed. Replaying that key returns the recorded movement. Selected-quantity reservation and issue use the request revision and record an idempotent receipt while updating stock and request lines. Cancellation closes open approvals and releases the unused line reservation in the same transaction. [Inventory service](../backend/app/services/inventory_service.py) · [Reservation regression tests](../backend/tests/test_inventory_accounting.py)
- A tagged transfer moves one unit of the asset's item between two distinct active locations. The transfer locks the tag, checks its current location and available stock, then updates the tag and stock in the same transaction. [Inventory service](../backend/app/services/inventory_service.py)
- Invoice state changes, corrections, and payment recording lock the invoice row. Rejected invoices without payments can be corrected at the current revision and resubmitted for a new approval cycle. Prior approval decisions remain in history. Payments require an approved invoice, a positive amount, and sufficient outstanding balance. The payment form retries an unconfirmed write with the original key and payload. The backend binds that key to the recorded payment in the invoice transaction. The budget summary compares the project budget against billable invoices and reports payments separately. [Finance service](../backend/app/services/finance_service.py) · [Concurrency tests](../backend/tests/test_report_payment_concurrency.py)
- Finance users choose suppliers through a minimal active-supplier lookup. The write path rechecks the supplier before selecting it. Supplier managers control deactivation and TDS evidence. Existing invoices and stock keep their historical supplier references. [Finance routes](../backend/app/api/v1/finance.py) · [Supplier service](../backend/app/services/supplier_service.py)

### Files, documents, and imports

- Photo and attachment access follows the owning entity. Uploads validate the supported file type and size. JPEG and PNG photo uploads can produce watermarked and thumbnail variants, and HEIC is stored as an original. Uploads and recovery serialize on the report or update row to enforce the five-active-photo quota. The API checks access before generating a time-limited signed link. [Photo service](../backend/app/services/photo_service.py)
- Document uploads start a version awaiting approval. Approval locks the parent document, validates and activates the selected version, and supersedes the previous active version. Download links are generated after document scope checks. **Refresh preview** requests a new five-minute link for the version already open and checks access again. [Document service](../backend/app/services/document_service.py) · [Document library](../frontend/src/pages/documents/DocumentsPage.tsx)
- Imports validate template rows and show a preview before execution. Background processing locks the existing batch and commits imported rows with the completion marker. Document imports create metadata, including the supplied filename. Use the document upload flow for binaries. [Import templates](import_templates/README.md) · [Import service](../backend/app/services/import_service.py) · [Import tasks](../backend/app/tasks/imports.py)

## Implementation map

| Area | API entry | Primary implementation |
| --- | --- | --- |
| Sign-in, reset, and sessions | [Auth](../backend/app/api/v1/auth.py) | [Auth service](../backend/app/services/auth_service.py), [signing and password helpers](../backend/app/utils/security.py), [Auth Context](../frontend/src/context/AuthContext.tsx) |
| Users and roles | [Users](../backend/app/api/v1/users.py) | [User service](../backend/app/services/user_service.py), [role mapping](../backend/app/utils/permissions.py) |
| Projects, assignments, BOQ, timeline | [Projects](../backend/app/api/v1/projects.py) | [Project service](../backend/app/services/project_service.py), [project repository](../backend/app/repositories/project_repository.py) |
| Dashboard and management exports | [Dashboard](../backend/app/api/v1/dashboard.py), [analytics](../backend/app/api/v1/analytics.py) | [Dashboard scope](../backend/app/services/dashboard_service.py), [analytics queries and exports](../backend/app/services/analytics_service.py) |
| Daily reports, PDFs, supervisor updates | [Reports](../backend/app/api/v1/reports.py), [supervisor updates](../backend/app/api/v1/supervisor_updates.py) | [Report service](../backend/app/services/report_service.py), [PDF export](../backend/app/services/report_export_service.py), [supervisor update service](../backend/app/services/reporting_service.py) |
| Workflow approvals and notifications | [Approvals](../backend/app/api/v1/approvals.py), [notifications](../backend/app/api/v1/notifications.py) | [Approval service](../backend/app/services/approval_service.py), [notification service](../backend/app/services/notification_service.py) |
| Inventory and suppliers | [Inventory](../backend/app/api/v1/inventory.py), [suppliers](../backend/app/api/v1/suppliers.py) | [Inventory service](../backend/app/services/inventory_service.py), [supplier service](../backend/app/services/supplier_service.py) |
| Documents and media | [Documents](../backend/app/api/v1/documents.py), [photos](../backend/app/api/v1/photos.py) | [Document service](../backend/app/services/document_service.py), [photo service](../backend/app/services/photo_service.py), [shared authorization](../backend/app/services/authorization.py) |
| Invoices, attachments, payments, budgets | [Finance](../backend/app/api/v1/finance.py) | [Finance service](../backend/app/services/finance_service.py) |
| Data imports | [Imports](../backend/app/api/v1/imports.py) | [Import service](../backend/app/services/import_service.py), [import tasks](../backend/app/tasks/imports.py) |
| Audit and operational logs | [Audit](../backend/app/api/v1/audit.py), [logs](../backend/app/api/v1/logs.py) | [Audit service](../backend/app/services/audit_service.py), [observability code](../backend/app/observability/), [remote CLI](LOGGING_AND_REMOTE_CLI.md) |

## Security and scoping

- Sign-in requires a password and an OTP. The browser uses a short-lived bearer JWT and a rotating HTTP-only refresh cookie. For authenticated requests the API reloads the active user, so current account state and role govern permissions. Password changes, resets, and Admin password updates revoke refresh sessions. Production and staging require configured signing keys at startup. Production disables development OTP exposure and ignores the staging login code. [Auth API](../backend/app/api/v1/auth.py) · [Auth service](../backend/app/services/auth_service.py) · [Signing key validation](../backend/app/utils/security.py)
- Route dependencies check baseline permissions where declared. Services check scope, ownership, eligibility, and state. Browser route and menu gates control what the UI presents. Consult the [access guide](ROLES_AND_PERMISSIONS.md) when adding an operation or changing visibility.
- Nginx applies security headers and sets the forwarding headers used by the API. Client IP resolution trusts forwarding data according to configured proxy addresses. [Production Nginx configuration](../nginx/nginx.prod.conf) · [Request IP handling](../backend/app/utils/request.py)
- Audit rows and application-side operational events persist in PostgreSQL. API and worker logs also go to stdout for Alloy and Loki. Grafana queries Loki and can send alerts. The [observability diagram](../README.md#observability-and-audit) and [log guide](LOGGING_AND_REMOTE_CLI.md) explain both paths.

## Deployment and verification

- The root README contains [local setup](../README.md#getting-started) and [verification commands](../README.md#verification). The [backend entry point](../backend/ARCHITECTURE.md) links the fixtures, migration files, and focused test suites.
- GitHub-hosted CI runs backend and frontend gates. The production workflow uses a dedicated self-hosted runner after successful CI for the current `main` push. The host release script publishes the build and verifies readiness and the served frontend assets. [CI and deployment diagram](../README.md#ci-and-production-deployment) · [CI workflow](../.github/workflows/ci.yml) · [Deployment workflow](../.github/workflows/deploy.yml) · [Host release script](../deploy/hostinger-release.sh)
- Use the [operations runbook](OPERATIONS_AND_DEPLOYMENT.md) for environment settings, schema upgrades, backups, isolated restores, and launch evidence. [Alembic revisions](../backend/alembic/versions/) define database evolution. [Production Compose](../docker-compose.prod.yml) and [settings](../backend/app/config.py) are the sources for deployed services and configuration keys.
