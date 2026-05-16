# Strict User Story Implementation Review

Date: 2026-05-16  
Scope: current working tree, including uncommitted changes  
Source stories: `TO-DO/[0-9][0-9]-*.md`  
Strict rule: a story is `Complete` only when every acceptance criterion, business rule, UI/UX note, technical note, and definition-of-done item has production implementation evidence plus relevant verification evidence.

## Verification Summary

| Command | Result | Review impact |
| --- | --- | --- |
| `cd backend && pytest` | Failed during collection. `asyncpg` and `structlog` are missing from the local Python environment. 17 test modules could not collect. | Backend test evidence is unavailable from this run, so no backend-dependent story can be marked complete. |
| `cd backend && ruff check .` | Failed to start. `ruff` command not found. | Ruff verification is unavailable locally. CI config does include a Ruff step. |
| `cd backend && mypy .` | Passed. `Success: no issues found in 141 source files`. | Static typing evidence is available for backend code. |
| `cd frontend && npm run build` | Passed. Vite built successfully with a large chunk warning. | Frontend production build evidence is available. |
| `cd frontend && npm test` | Passed. 1 test file, 3 tests. React Router SSR `useLayoutEffect` warnings were emitted. | Frontend route smoke-test evidence is available, but coverage is narrow. |
| `cd frontend && npm run lint` | Failed. Unused imports in `frontend/src/pages/reports/SupervisorUpdatePage.tsx`: `Image`, `Paperclip`, `FileDropZone`. | Frontend CI would fail; no frontend story can be considered release-complete. |

Operational/static checks inspected:

- `.github/workflows/ci.yml`: backend Ruff, mypy, Alembic, pytest; frontend ESLint, Prettier, Vitest, build; Docker Compose config/build.
- `.github/workflows/deploy.yml`: staging and production SSH deployments using GitHub environments.
- `docker-compose.yml` and `docker-compose.prod.yml`: backend, frontend, PostgreSQL, Redis, MinIO, Celery worker/beat, Nginx.
- `.env.example`: local database, Redis, MinIO, JWT, OTP, SMTP, backup settings.
- `backend/alembic/versions/*`: migrations through users, auth, projects/BOQ, reports, approvals, exports, photos, documents, notifications, inventory, suppliers, finance, imports.
- `backend/app/tasks/*`, `backend/scripts/backup.py`, `docs/06_Operations_Runbook.md`, `docs/07_UAT_Launch_Readiness.md`, `docs/import_templates/*`.

## Overall Result

Strict completion: **0 / 25 stories complete = 0%**.

| Status | Count |
| --- | ---: |
| Complete | 0 |
| Partial | 25 |
| Missing | 0 |
| Blocked by external dependency | 0 |

All stories have at least some implementation or documentation evidence, but none satisfies strict 100% completion because the repo currently has verification failures and each story still has missing production, test, UX, operational, or dependency-closure items.

## Story Traceability Matrix

| Story | Title | Status | Primary launch risk |
| --- | --- | --- | --- |
| 01 | Project Foundation and Dev Environment | Partial | Local backend verification cannot run; README status is stale. |
| 02 | CI/CD, Staging, Production, and Operations | Partial | Production approval and backup/monitoring are configured/documented but not proven for the target environment. |
| 03 | Authentication, 2FA, and Session Security | Partial | Auth exists, but forced-password UI and backend test verification are incomplete/unproven. |
| 04 | User Roles, Permissions, and Admin Management | Partial | RBAC exists, but strict permission coverage and admin UX completeness are not fully proven. |
| 05 | Project Setup, BOQ, and Team Assignment | Partial | Core project/BOQ APIs and UI exist, but import/export/saved-filter UX and tests are incomplete. |
| 06 | App Shell, Navigation, and Responsive Layout | Partial | Shell exists, but lint is failing and route-level loading/empty/error states are inconsistent. |
| 07 | Supervisor Site Update Flow | Partial | Flow exists, but mobile upload UI/lint/autosave/network behavior are incomplete. |
| 08 | Engineer Daily Report Flow | Partial | Core report flow exists, but full field/template coverage and backend verification are not complete. |
| 09 | Daily Report Approval, Rejection, and History | Partial | Report approval exists, but target-confirmation/admin override and staged late escalation are incomplete. |
| 10 | Report PDF Export and Email Delivery | Partial | PDF/email path exists, but template support and failure visibility are incomplete. |
| 11 | Photo and Attachment Upload Management | Partial | Upload/compression/watermarking exist, but async image-task and mobile/offline upload completeness are incomplete. |
| 12 | Document Upload, Versioning, and Approval | Partial | Document versioning exists, but browser preview/search/grid/detail coverage and tests are incomplete. |
| 13 | Basic Notifications and Alerts | Partial | In-app/email notification primitives exist, but full event matrix, muting, and retention tests are incomplete. |
| 14 | Operational Dashboard Summary | Partial | Summary cards exist, but refresh behavior, caching policy, and broader KPI rules are incomplete. |
| 15 | Audit Log and Download Tracking | Partial | Audit infrastructure exists, but full event coverage, masking, retention, and all-file download tracking are incomplete. |
| 16 | Seed Data, UAT, and Launch Readiness | Partial | Seed/UAT artifacts exist, but launch sign-off scenarios cannot pass with current verification failures. |
| 17 | Generic Approval Engine, Delegation, and Escalation | Partial | Engine exists, but UI lacks delegation/override and reminders/escalation timing differs from story. |
| 18 | Inventory Catalog, Locations, and Stock | Partial | Catalog/stock exist, but asset UI, unit conversion, and strict tests are incomplete. |
| 19 | Material Request, Reservation, and Issue Flow | Partial | Backend lifecycle exists, but frontend request/reserve/issue workflow is missing. |
| 20 | Inventory Movements, Returns, Transfers, and Low Stock | Partial | Movement/low-stock logic exists, but daily-report consumption integration and full movement UI/tests are incomplete. |
| 21 | Supplier Management and Compliance | Partial | Supplier CRUD/TDS exists, but dedicated supplier UI and expiry reminders are incomplete. |
| 22 | Accounts, Invoices, Payments, and Budget Tracking | Partial | Invoice/payment/budget basics exist, but approval chain and finance UX/export completeness are incomplete. |
| 23 | Advanced Analytics and Management Exports | Partial | Analytics/export APIs exist, but async polling UX/templates/stakeholder-approved exports are incomplete. |
| 24 | Mobile PWA, Offline Drafts, and Photo Queue | Partial | PWA/offline draft primitives exist, but conflict handling and supported-browser verification are incomplete. |
| 25 | Data Import Templates and Initial Migration | Partial | Templates/import APIs exist, but async UI, XLSX support, idempotency keys, and rollback tests are incomplete. |

## Detailed Story Review

### 01. Project Foundation and Dev Environment

Status: **Partial**

Evidence:

- Docker Compose local stack exists in `docker-compose.yml` with backend, frontend, PostgreSQL 16, Redis, MinIO, Celery worker/beat, and Nginx.
- Backend FastAPI app, database, settings, `/api/v1`, health/readiness routing, and Alembic migrations exist under `backend/app`, `backend/alembic/versions`, and `backend/app/main.py`.
- Frontend Vite/React/Tailwind app exists under `frontend/`.
- `.env.example` documents local DB, Redis, MinIO, JWT, OTP, SMTP, and backup variables without production secrets.
- `frontend && npm run build` passed; backend `mypy .` passed.

Missing items:

- `backend && pytest` cannot collect locally due missing `asyncpg` and `structlog`; health, migrations, and backend test evidence are therefore not available from this review.
- `frontend && npm run lint` fails, so the initial frontend is not CI-clean.
- Root `README.md` still states only story 01 is implemented, while implementation now spans many stories; status documentation is stale.
- No current evidence that `docker compose up --build`, `/health`, `/health/readiness`, and `alembic upgrade head` were run successfully in this working tree.

Risk:

- Developers may not be able to reproduce the stack from a clean checkout without first resolving local dependency and lint failures.

### 02. CI/CD, Staging, Production, and Operations

Status: **Partial**

Evidence:

- `.github/workflows/ci.yml` includes backend lint/type/migration/test, frontend lint/format/test/build, and Docker Compose validation/build jobs.
- `.github/workflows/deploy.yml` deploys `develop` to staging and `main`/manual target to production through SSH and GitHub environments.
- `docker-compose.prod.yml` defines production-style Nginx, backend, PostgreSQL, Redis, MinIO, Celery worker, and Celery beat services.
- `backend/scripts/backup.py`, `backend/app/tasks/backup.py`, `.env.example`, and `docs/06_Operations_Runbook.md` document daily/monthly backup, retention, restore, and rollback procedures.

Missing items:

- Production deployment approval is expressed as a GitHub `production` environment but the Operation Manager approver identity is not encoded or proven in repo evidence.
- Staging and production host/provider details are secret-dependent and not verifiable locally.
- No current evidence that scheduled daily/monthly backups are actually configured in production; `run_database_backup` exists but Celery beat does not schedule it.
- Basic uptime/error monitoring and alert routing are documented, but no concrete monitoring provider, alert integration, or tested outage alert path exists.
- User-facing downtime messages are not implemented in Nginx or frontend error surfaces.

Risk:

- Release control and data recovery may look complete in code/docs but remain unproven operationally.

### 03. Authentication, 2FA, and Session Security

Status: **Partial**

Evidence:

- Auth APIs exist in `backend/app/api/v1/auth.py`: login, verify OTP, refresh, logout, me, change password, password-reset request/confirm.
- `backend/app/services/auth_service.py` implements password hashing, OTP verification, failed-login lockout, refresh token rotation, logout invalidation, first-login password change flag handling, and auth audit records.
- `backend/app/middleware/rate_limit.py` rate-limits login, OTP, and password reset endpoints.
- `frontend/src/pages/auth/LoginPage.tsx`, `frontend/src/context/AuthContext.tsx`, and `frontend/src/api/auth.ts` implement login and OTP verification client flows.

Missing items:

- Forced first-login password-change UI is not routed as a protected user flow; backend support exists but frontend only handles login and OTP.
- Password reset UI is missing even though backend endpoints exist.
- Session storage claims cannot be fully validated from code review; access token is held in memory, but full refresh-cookie behavior depends on runtime browser/API behavior.
- Backend auth tests could not run locally due missing dependencies.
- `frontend && npm run lint` is failing, so auth UI cannot be considered release-clean.

Risk:

- Users can authenticate, but required first-login/reset flows and security regression evidence are incomplete.

### 04. User Roles, Permissions, and Admin Management

Status: **Partial**

Evidence:

- User APIs exist in `backend/app/api/v1/users.py` for list, create, patch, and deactivate.
- Fixed MVP roles and permission sets exist in `backend/app/utils/permissions.py`.
- API permission dependencies exist in `backend/app/api/dependencies.py` and are used on user, project, audit, import, inventory, supplier, and route guards.
- `backend/app/services/user_service.py` manages user lifecycle and audit records.
- `frontend/src/pages/admin/UserManagementPage.tsx` supports list, filters, create, status badges, and deactivate confirmation.
- `frontend/src/components/layout/AppLayout.tsx` filters navigation by authenticated permissions.

Missing items:

- Backend permission tests could not run locally.
- Admin cannot visibly update all user fields from the current frontend; create/deactivate is present, but rename/reassign UX is incomplete.
- General Manager authority remains a story dependency; current permission matrix grants broad project/report/document/finance visibility but not `users:manage`.
- No database-backed customizable permission records are visible; permissions are fixed in code only.
- Search/filter/sorting is partial; sorting is not evident in the frontend admin table.

Risk:

- Access control foundations exist, but strict role-management and auditability claims are not fully proven.

### 05. Project Setup, BOQ, and Team Assignment

Status: **Partial**

Evidence:

- Project APIs exist in `backend/app/api/v1/projects.py` for list, create, detail, update, members, member assignment, and timeline.
- `backend/app/services/project_service.py` generates project codes, requires at least one BOQ item, creates milestones/BOQ rows, enforces completed/cancelled read-only status, checks member access, and audits changes.
- Project, milestone, BOQ, and member models/migrations exist.
- `frontend/src/pages/projects/ProjectListPage.tsx` supports project list, search/status filters, and project creation with first milestone/BOQ entry.
- BOQ import support exists through import templates and `backend/app/services/import_service.py`.

Missing items:

- Project update/member assignment/timeline/detail flows are not fully exposed in the frontend.
- BOQ spreadsheet import exists via generic import, not inside a project-specific BOQ workflow.
- Export and saved filters are not implemented in the project UI.
- Tablet timeline readability is not verified.
- Backend project tests could not run locally.

Risk:

- Project creation can start, but operational project management remains too thin for launch use.

### 06. App Shell, Navigation, and Responsive Layout

Status: **Partial**

Evidence:

- Protected app shell exists in `frontend/src/components/layout/AppLayout.tsx`.
- `frontend/src/components/layout/RequirePermission.tsx` protects routes.
- Sidebar, mobile bottom navigation, notification bell, offline indicator, and error boundary exist.
- Role-aware navigation uses permissions from `useAuth`.
- Frontend build and route smoke tests pass.

Missing items:

- Frontend lint fails because of unused imports in `SupervisorUpdatePage.tsx`.
- Route-level loading, empty, and error states are inconsistent across pages.
- Mobile MVP route coverage is only partial; bottom nav is limited to four items and not every mobile-required module is directly reachable.
- Responsive checks for desktop/tablet/phone were not run in this review.

Risk:

- The app shell is present, but release quality is blocked by lint and incomplete route-state coverage.

### 07. Supervisor Site Update Flow

Status: **Partial**

Evidence:

- Backend supervisor update APIs exist in `backend/app/api/v1/supervisor_updates.py`.
- `backend/app/services/reporting_service.py` restricts creation to Civil Supervisors, validates project membership, previous-date rules, day type, duplicate drafts, submit status, and audit records.
- `frontend/src/pages/reports/SupervisorUpdatePage.tsx` implements a form with validation, local draft persistence, save/submit, project selection, photo/attachment inputs, size/count limits, and uploaded file tracking.
- Supervisor update model/migration/tests exist, although tests did not run locally.

Missing items:

- The frontend lint failure is in `SupervisorUpdatePage.tsx`.
- Autosave is local-storage based on field changes but not proven every 30 seconds.
- Weak-network retry behavior is not implemented for supervisor updates.
- Camera/mobile photo upload ergonomics are basic file inputs, not a polished mobile camera flow.
- The backend previous-date rule text says admin approval is required, but the current implementation blocks old supervisor submissions for Civil Supervisors rather than routing approval.

Risk:

- Field update capture exists, but the mobile/weak-network and approval nuance required for field use is incomplete.

### 08. Engineer Daily Report Flow

Status: **Partial**

Evidence:

- Daily report APIs exist in `backend/app/api/v1/reports.py`: list, create, get, PDF, update, submit, approve, reject.
- `backend/app/services/report_service.py` creates drafts, validates engineer role/project membership, replaces manpower/equipment/material child rows, verifies supervisor updates, generates report numbers, and locks approved/submitted states.
- Report models/migration include daily reports, manpower, equipment, material consumption, and approval history.
- `frontend/src/pages/reports/DailyReportPage.tsx` implements project/supervisor selection, dynamic manpower/equipment/material rows, draft save, submit, PDF download, photo/attachment upload, local draft, and offline photo queue hooks.

Missing items:

- Full company daily-report field/template confirmation remains a dependency.
- Report print/readability on desktop/tablet was not visually verified.
- Material consumption is captured but not connected to stock reduction.
- Backend report tests could not run locally.
- Frontend route tests do not cover daily report form behavior.

Risk:

- Official report workflow exists, but the form cannot be treated as final company-record coverage without template and stock integration closure.

### 09. Daily Report Approval, Rejection, and History

Status: **Partial**

Evidence:

- Report approve/reject APIs exist in `backend/app/api/v1/reports.py`.
- `backend/app/services/report_service.py` enforces submitted-only approval/rejection, requires rejection reason, writes `DailyReportApprovalHistory`, locks approved reports, notifies the engineer, audits decisions, and queues post-approval tasks.
- `backend/app/tasks/maintenance.py` includes `check_late_reports`; Celery beat schedules it hourly in `backend/app/tasks/celery_app.py`.
- `frontend/src/pages/approvals/ApprovalInboxPage.tsx` lists submitted reports and generic approvals, supports approve/reject actions, and requires rejection comments.
- `frontend/src/pages/reports/DailyReportPage.tsx` displays approval history in report records.

Missing items:

- Daily report approval does not explicitly require or record confirmation that the target was covered.
- Admin override for report approvals is not present in the report-specific UI/API path.
- Late/missing report logic notifies Operation Managers and Project Managers immediately after the cutoff; it does not notify the submitter first and then escalate to Project Manager if still missing.
- Weekend/holiday skip is hard-coded to Friday only, not based on scheduled work.
- Approval screen content/attachments/history preview before action is limited and not verified as complete.
- Backend approval tests could not run locally.

Risk:

- Core approve/reject works, but late escalation and compliance/audit requirements are not 100% aligned with the story.

### 10. Report PDF Export and Email Delivery

Status: **Partial**

Evidence:

- PDF endpoint exists at `GET /api/v1/reports/{report_id}/pdf`.
- `backend/app/services/report_export_service.py`, `backend/app/models/report_export.py`, and migration `202605160008_report_exports.py` support report export metadata.
- `backend/app/tasks/report.py` defines `generate_report_pdf` and `generate_excel_export`; `backend/app/tasks/email.py` defines `send_report_email`.
- `backend/app/services/report_service.py` queues post-approval report PDF generation with `email_after=True`.
- `frontend/src/pages/reports/DailyReportPage.tsx` includes PDF download.

Missing items:

- Company/client template upload or selection is not implemented.
- PDF generation failure visibility for authorized support users is not surfaced in frontend.
- Email status is stored on `report_exports`, but users do not see generation/email status in report detail.
- Large/asynchronous export polling UX is not implemented for report PDFs.
- Backend PDF/email tests could not run locally.

Risk:

- Official report sharing has a backend path, but template compliance and recoverability are not launch-ready.

### 11. Photo and Attachment Upload Management

Status: **Partial**

Evidence:

- Photo APIs exist in `backend/app/api/v1/photos.py`: upload, list, get, download, thumbnail, delete.
- `backend/app/services/photo_service.py` validates file type/size, blocks risky extensions, limits report photos to 5, stores files in MinIO, creates compressed/thumbnail variants, watermarks photos with "Garrisons Investments", and audits upload/download/delete.
- `backend/app/tasks/image.py` defines thumbnail/compress task placeholders.
- Frontend report/supervisor/document pages use upload flows and file inputs; `frontend/src/components/shared/FileDropZone.tsx` exists.

Missing items:

- Image processing is synchronous in `PhotoService`; Celery image tasks are placeholders and not used for thumbnail/compression/watermarking.
- GPS/location metadata handling is not implemented.
- Drag-drop is not consistently wired; `FileDropZone` is currently unused in `SupervisorUpdatePage.tsx` and triggers lint failure.
- Weak-network/mobile upload behavior is partial; only daily report offline queue has implementation.
- Backend photo tests could not run locally.

Risk:

- Uploads work in principle, but field reliability and asynchronous media processing are incomplete.

### 12. Document Upload, Versioning, and Approval

Status: **Partial**

Evidence:

- Document APIs exist in `backend/app/api/v1/documents.py`: list, upload, detail, upload version, list versions, approve version, download.
- `backend/app/services/document_service.py` stores versions, marks pending approval/active/superseded, validates files, audits downloads, and creates approval notifications.
- Document models/migration include document and version history.
- `frontend/src/pages/documents/DocumentsPage.tsx` supports filters/search, upload, approve pending version, preview/download via signed URL, and status badges.

Missing items:

- Browser PDF preview is implemented by opening signed URLs, not an embedded controlled preview with robust state.
- Grid/list toggle is not implemented.
- Metadata forms are basic and not proven against company standards.
- Version history and superseded warnings exist partially but are not proven visually comprehensive.
- Document approval is separate from the generic approval engine in the UI.
- Backend document tests could not run locally.

Risk:

- Document control has foundations, but field users may still lack a reliable active-version workflow.

### 13. Basic Notifications and Alerts

Status: **Partial**

Evidence:

- Notification APIs exist in `backend/app/api/v1/notifications.py`: list, unread count, mark read, mark all read.
- `backend/app/services/notification_service.py` creates in-app records and queues email notification tasks.
- `backend/app/tasks/email.py` sends notification email; `backend/app/tasks/maintenance.py` cleans old notifications.
- `frontend/src/components/layout/AppLayout.tsx` polls unread count every 60 seconds and shows a header bell.
- `frontend/src/pages/notifications/NotificationsPage.tsx` shows notification history and read actions.

Missing items:

- Full event matrix is incomplete or unproven: low stock and approval/report events exist, but new document and all pending approval cases are not consistently wired.
- Users cannot mute notifications in the frontend; backend has a `muted` field but no policy/UI.
- Reminder/escalation jobs exist for generic approvals, but tests did not run.
- User-facing retention cleanup exists, but no local test evidence proves 90-day cleanup.
- Email provider configuration remains external and unverified.

Risk:

- Notifications will work for some events, but users can still miss required actions outside wired paths.

### 14. Operational Dashboard Summary

Status: **Partial**

Evidence:

- Dashboard API exists at `GET /api/v1/dashboard/summary`.
- `backend/app/services/dashboard_service.py` counts active projects, pending approvals, approved reports, pending documents, unread notifications, and recent report activity.
- `frontend/src/pages/dashboard/DashboardPage.tsx` renders dashboard summary cards and recent activity.

Missing items:

- Dashboard refresh every few minutes is not implemented on the page.
- Late/missing reports and upcoming deadlines are not clearly represented in the dashboard summary.
- Low-stock cards are not explicitly hidden/empty until inventory is implemented; inventory is now partially implemented, but dashboard integration remains absent.
- Redis caching policy is documented but not implemented for dashboard summaries.
- Frontend dashboard route has limited test coverage only through broad smoke tests.

Risk:

- Management visibility is useful but incomplete for Phase 1 operating control.

### 15. Audit Log and Download Tracking

Status: **Partial**

Evidence:

- `backend/app/models/activity_log.py`, `backend/app/services/audit_service.py`, and migration support audit logs.
- `backend/app/middleware/audit.py` records authenticated HTTP request outcomes with status codes.
- Auth, projects, reports, documents, photos, suppliers, finance, imports, and approvals call `AuditService.record` for many domain events.
- Audit API is admin-permission protected in `backend/app/api/v1/audit.py`.
- `frontend/src/pages/admin/AuditLogPage.tsx` supports filters and displays audit logs.

Missing items:

- Download tracking is implemented for documents, photos, supplier TDS, and invoice attachments, but report PDF downloads are not clearly audited.
- Audit log retention for 7 years and deleted-record recoverability for 30 days are not implemented as lifecycle policies.
- Sensitive value masking is not implemented consistently.
- Admin audit UI has filters but no clear detail view or sorting.
- Delegated/override audit exists for generic approvals, but UI is incomplete and tests did not run.

Risk:

- Compliance traceability is present but not strong enough for legal/audit retention claims.

### 16. Seed Data, UAT, and Launch Readiness

Status: **Partial**

Evidence:

- `backend/scripts/seed.py` creates users, projects, suppliers, inventory, reports, approvals, and notifications.
- `docs/07_UAT_Launch_Readiness.md` contains launch readiness and UAT checklists.
- Role-specific test account data exists in seed script patterns.
- Backend tests exist for many modules, though they could not run locally.

Missing items:

- No evidence that Phase 1 launch scenarios pass on mobile and desktop.
- UAT sign-off by MD and Operation Manager is not recorded.
- API response envelope, RBAC enforcement, and frontend route error-boundary UAT checks are not executable from this report.
- Current lint/backend-test failures block launch-readiness completion.

Risk:

- Seed and UAT planning exist, but launch readiness cannot be claimed until verification is green and sign-off is recorded.

### 17. Generic Approval Engine, Delegation, and Escalation

Status: **Partial**

Evidence:

- Generic approval APIs exist in `backend/app/api/v1/approvals.py`: list, create, detail, approve, reject, delegate, override.
- `backend/app/services/approval_service.py` supports request type/id, approver resolution, delegation, admin override, rejection reason, reminders/escalation, entity decision application for material requests, invoices, daily reports, and documents, notifications, and audit records.
- `backend/app/tasks/approval.py` runs approval reminders/escalations; Celery beat schedules it hourly.
- `frontend/src/pages/approvals/ApprovalInboxPage.tsx` lists pending generic approvals and supports approve/reject.

Missing items:

- Frontend does not expose delegation or admin override actions.
- Approval inbox tabs are `reports` and `workflow`, not pending/rejected/approved tabs as required.
- Reminder/escalation timing is not exactly story-aligned: approvals default due time is 24 hours, and both reminder/escalation checks are based on due timestamps; story requires reminder after 24 hours and escalation after 48 hours.
- Approval comments visibility "only to managers" is not enforced in UI evidence.
- Project changes approval is not wired.
- Backend approval tests could not run locally.

Risk:

- Reusable approval foundations exist, but delayed-approval governance is not production-complete.

### 18. Inventory Catalog, Locations, and Stock

Status: **Partial**

Evidence:

- Inventory APIs exist in `backend/app/api/v1/inventory.py` for locations, items, stock, assets, movements, low stock, and material requests.
- `backend/app/services/inventory_service.py` manages locations/items/assets, validates supplier requirement, restricts price visibility, prevents negative stock, tracks stock by location, and handles assets/current location on transfer.
- Inventory models/migration cover storage locations, inventory items, location stock, assets, material requests, request lines, and movements.
- `frontend/src/pages/inventory/InventoryPage.tsx` supports locations, suppliers, inventory item creation, receive stock, item stock matrix, low-stock panel, and TDS upload.

Missing items:

- Unit conversion per material is not implemented.
- Asset creation/current-location UI is missing or not visible in the frontend page.
- Pricing restrictions are backend-driven but frontend may still render unit cost field for unauthorized users when creating items.
- Tests for catalog/stock/assets/permission rules could not run locally.
- Supplier requirement is enforced in backend but not proven in UI validation.

Risk:

- Stock visibility exists, but asset tracking and permission-sensitive inventory UX are not complete.

### 19. Material Request, Reservation, and Issue Flow

Status: **Partial**

Evidence:

- Backend material request APIs exist in `backend/app/api/v1/inventory.py`: list, create, reserve, issue, cancel.
- `backend/app/services/inventory_service.py` creates material requests, creates generic approvals, reserves stock, issues stock, records movements, supports partial issue, cancellation, and blocks insufficient stock with 409.
- Material request models and approval integration exist.

Missing items:

- Frontend material request, approval, reserve, issue, partial issue, and cancel workflows are not exposed in `InventoryPage`.
- Request forms do not show availability by location.
- Approver cost visibility is not demonstrated in UI.
- Outgoing materials are not linked to daily reports in the current issue workflow.
- Transaction failure tests could not run locally.

Risk:

- The backend workflow is partially ready, but site/store users cannot operate it from the frontend.

### 20. Inventory Movements, Returns, Transfers, and Low Stock

Status: **Partial**

Evidence:

- Movement API exists at `POST /api/v1/inventory/movements` and movement list filters exist for item, location, and project.
- `backend/app/services/inventory_service.py` supports receive, reserve, issue, transfer, return, consume, adjustment, wastage, and damaged movement types; prevents negative available stock; updates asset location on transfer.
- `backend/app/tasks/approval.py` implements hourly low-stock notification checks; Celery beat schedules `check_low_stock`.
- Frontend `InventoryPage` supports receiving stock and low-stock display.

Missing items:

- Frontend movement forms for transfer, return, consume, adjustment, wastage, and damaged are missing.
- Movement history filtering UI is not implemented.
- Daily report material consumption does not automatically reduce stock.
- Low-stock notifications are implemented, but no test evidence is available locally.
- Minimum-stock setter role says Store Manager in story; no Store Manager role exists in the current fixed role set.

Risk:

- Stock can be adjusted through backend APIs, but storekeeper daily workflows and report-driven stock integrity remain incomplete.

### 21. Supplier Management and Compliance

Status: **Partial**

Evidence:

- Supplier APIs exist in `backend/app/api/v1/suppliers.py`: list, create, patch, TDS upload/download, deactivate.
- `backend/app/services/supplier_service.py` supports search/filter, compliance fields, soft delete/deactivation, TDS file storage, protected signed download URLs, and audit logging.
- Supplier model/migration and import template exist.
- Supplier create/TDS upload appears inside `frontend/src/pages/inventory/InventoryPage.tsx`, with expiring TDS highlighting.

Missing items:

- There is no dedicated supplier management page.
- Supplier list UI is embedded in inventory and is not complete for all CRUD/search/filter/deactivation needs.
- Expiry reminder hooks are not implemented beyond low-stock/approval tasks.
- Financial/tax field visibility is not clearly role-restricted in frontend.
- Backend supplier tests could not run locally.

Risk:

- Supplier data can be captured, but compliance management is not yet a complete operational surface.

### 22. Accounts, Invoices, Payments, and Budget Tracking

Status: **Partial**

Evidence:

- Finance APIs exist in `backend/app/api/v1/finance.py`: invoice list/create/detail/update, attachment upload/download, payment create, budget summary.
- `backend/app/services/finance_service.py` restricts finance roles, creates invoice approvals, records payments, updates payment status, stores protected invoice attachments, and audits file access.
- Finance models/migration include invoices and payments.
- `frontend/src/pages/finance/FinancePage.tsx` supports invoice creation, payment recording, attachment upload/open, and list display.

Missing items:

- Operation Manager second approval for invoices is not enforced as a multi-step approval chain.
- Accounts user invoice approval flow is generic/backend-only; frontend does not expose invoice approval detail well.
- Project budget summary exists as API but is not clearly surfaced in the finance page.
- Material/manpower cost integration is incomplete.
- Searchable/exportable desktop finance tables are minimal; export actions are missing.
- Backend finance tests could not run locally.

Risk:

- Finance tracking starts, but approval governance and management reporting are incomplete.

### 23. Advanced Analytics and Management Exports

Status: **Partial**

Evidence:

- Analytics APIs exist in `backend/app/api/v1/analytics.py`: summary, project-progress export, material-usage export, management-summary export.
- `backend/app/services/analytics_service.py` builds summary data, XLSX-like export content, PDF management summary, uploads exports to MinIO, and enforces management access.
- `backend/app/tasks/report.py` includes asynchronous management/export task functions.
- `frontend/src/pages/analytics/AnalyticsPage.tsx` renders charts/tables using Recharts and export buttons.

Missing items:

- Export endpoints in routes appear to run synchronously instead of returning `202 Accepted` task IDs with client polling for large exports.
- Stakeholder-approved templates are not present.
- Salary sheet/bookkeeping/P&L reports are not implemented beyond basic invoice/material/progress data.
- Active filter indicators and full filter UX are limited.
- Backend analytics tests could not run locally.

Risk:

- Management analytics are useful for demos but not complete for executive reporting commitments.

### 24. Mobile PWA, Offline Drafts, and Photo Queue

Status: **Partial**

Evidence:

- Frontend PWA manifest, service worker, and brand icons exist in `frontend/public/manifest.json`, `frontend/public/sw.js`, and `frontend/public/brand/*`.
- `frontend/src/api/offlineQueue.ts` uses IndexedDB for report drafts and photo queue metadata.
- `frontend/src/pages/reports/DailyReportPage.tsx` saves report drafts, shows local/server-newer draft status, queues files when upload fails, tracks queued upload count, and flushes queue online.
- App shell includes mobile bottom navigation and offline indicator.

Missing items:

- Conflict handling is minimal; `server_newer` is a UI state, but there is no full server reconciliation protocol or approval-aware conflict resolution.
- No service-worker background sync; foreground retry exists only for queued photo uploads.
- Client-generated UUID/idempotency behavior is partial and not backed by Redis idempotency cache evidence.
- Mobile browser regression tests for Chrome, Edge, iOS Safari, Android Chrome, and Opera were not run.
- Offline behavior is scoped mainly to daily reports/photos and not clearly validated with weak network.

Risk:

- The app has promising offline primitives, but construction-site reliability is not yet proven.

### 25. Data Import Templates and Initial Migration

Status: **Partial**

Evidence:

- Import APIs exist in `backend/app/api/v1/imports.py`: template download, batch detail, preview, run, run async.
- `backend/app/services/import_service.py` defines templates for users, projects, suppliers, materials, documents, BOQ, and opening stock; validates columns/row values; records import batches; creates records; opening stock creates receive movements.
- CSV templates exist in `docs/import_templates`.
- `frontend/src/pages/admin/ImportPage.tsx` supports template download, CSV upload, preview, run, and result display.

Missing items:

- XLSX support is not implemented; imports are CSV-only.
- Async import job UI/polling is not implemented in frontend.
- Idempotency keys are not implemented for import runs; natural-key duplicate skipping is partial.
- Import rollback behavior and duplicate handling tests could not run locally.
- Source spreadsheets and legal decision on historical reports/documents remain external dependencies.

Risk:

- Initial data loading can be attempted, but migration safety and operator feedback are incomplete for launch.

## Top Launch Blockers

1. **Verification is not green**: backend pytest cannot collect locally, frontend lint fails, and Ruff is unavailable locally.
2. **Operational readiness is not proven**: production approval identity, monitoring, backup scheduling, and restore dry-run evidence are incomplete.
3. **Core field workflows have partial UX**: supervisor/daily report/photo flows exist but weak-network/mobile behavior and route-state coverage are incomplete.
4. **Approval governance is incomplete**: generic approval engine exists, but frontend delegation/override, exact 24h/48h reminder/escalation semantics, and multi-step finance approval are incomplete.
5. **Inventory/material workflows are backend-heavy**: material request, reserve, issue, transfer, return, and movement history need complete frontend workflows.
6. **Compliance lifecycle gaps remain**: audit retention/masking, all private-file download tracking, document active-version UX, and supplier expiry reminders are incomplete.

## Prioritized Next Implementation Order

1. Fix CI blockers: install/lock backend dev dependencies locally or document venv setup, fix frontend lint in `SupervisorUpdatePage.tsx`, and get `pytest`, `ruff`, `mypy`, `npm run lint`, `npm test`, and `npm run build` all green.
2. Close Phase 1 launch path: auth forced password/reset UI, project/member/detail workflows, supervisor mobile upload/autosave behavior, daily report form/template confirmation, report approval preview/history, and PDF/email status visibility.
3. Harden notifications/audit/operations: complete event matrix, reminder/escalation semantics, audit masking/retention/download coverage, backup schedule, restore dry-run record, and monitoring/alert routing.
4. Complete document control: controlled PDF preview, version-history UX, superseded warnings, active-version search/filter behavior, and document approval integration.
5. Finish inventory/material/supplier workflows: asset UI, movement forms/history filters, material request reserve/issue UI, low-stock tests, supplier compliance page, and expiry reminders.
6. Finish finance/analytics/import/offline: invoice multi-step approval, budget summary UI, export polling/templates, CSV/XLSX import safety, idempotency, mobile offline conflict handling, and supported-browser testing.

