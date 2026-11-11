# ARCHITECTURE.md — Construction Internal Portal

Last synced with `graphify-out/` (commit `ed3f1cca`, report date 2026-05-28): 221 files · ~149,503 words · 3,248 nodes · 14,822 edges · 170 communities. Note: ~48% of edges are INFERRED and may include noise (e.g., standard Python types like `int`/`str` showing up as entities).

## Table of Contents

1. [High-Level System Architecture](#1-high-level-system-architecture)
2. [Backend Layered Architecture](#2-backend-layered-architecture)
3. [Frontend Architecture](#3-frontend-architecture)
4. [Data Architecture](#4-data-architecture)
5. [Security Architecture](#5-security-architecture)
6. [API Design Principles](#6-api-design-principles)
7. [Deployment Architecture](#7-deployment-architecture)
8. [Cross-Cutting Concerns](#8-cross-cutting-concerns)
9. [Directory & Project Structure](#9-directory--project-structure)
10. [Architectural Decisions (ADRs)](#10-architectural-decisions-adrs)
11. [Appendix: Technology Version Matrix](#11-appendix-technology-version-matrix)

---

## 1. High-Level System Architecture

### 1.1 System Context

```
                    +-------------------------------------------+
                    |              CLIENT LAYER                  |
                    |                                            |
                    |  +------------------+  +----------------+  |
                    |  |  Web Admin Panel  |  |  Mobile PWA    |  |
                    |  |  (Desktop-First)  |  |  (Responsive)  |  |
                    |  +--------+---------+  +-------+--------+  |
                    +-----------|--------------------|-----------+
                                |                    |
                                |   HTTPS (TLS 1.3)  |
                                |    +----------+    |
                                +----+  Nginx   +----+
                                     | (Reverse  |
                                     |  Proxy)   |
                                     +-----+-----+
                                           |
              +----------------------------+----------------------------+
              |                  APPLICATION LAYER                       |
              |                                                         |
              |  +--------------------------+  +-----------------------+ |
              |  |  FastAPI (Uvicorn)        |  |  Celery Workers       | |
              |  |                          |  |                       | |
              |  |  Middleware Pipeline:    |  |  - Email Service      | |
              |  |   Auth -> RBAC ->        |  |  - Image Processing   | |
              |  |   Rate Limit -> Audit    |  |  - Report Generation  | |
              |  |                          |  |  - Backup Execution   | |
              |  |  Layers:                 |  |  - Notification       | |
              |  |   Routes -> Services ->  |  |    Dispatch            | |
              |  |   Repositories -> Models |  |                       | |
              |  +------------+-------------+  +-----------+-----------+ |
              +---------------|-----------------------------|-------------+
                              |                             |
              +---------------|-----------------------------|-------------+
              |                       DATA LAYER                         |
              |                                                         |
              |  +------------------+  +------------------+              |
              |  |  PostgreSQL 18.6   |  |  Redis 7          |              |
              |  |  (Primary)       |  |  (Cache, Queue,   |              |
              |  |                  |  |   Rate Limiter)   |              |
              |  +------------------+  +------------------+              |
              |                                                         |
              |  +--------------------------------------------------+   |
              |  |  MinIO Object Storage (S3-Compatible, Self-Hosted)|   |
              |  |  - Photos (original + compressed + thumbnail)     |   |
              |  |  - Documents (all versions)                       |   |
              |  |  - Database dumps / backups                        |   |
              |  +--------------------------------------------------+   |
              +---------------------------------------------------------+
```

### 1.2 Request Lifecycle

```
1. Client sends HTTPS request with Authorization: Bearer <access_token>

2. Nginx terminates TLS, applies gzip, enforces security headers:
   - Routes `/api/*` to FastAPI
   - Serves `/assets/*` and built frontend static files directly
   - Private files (photos, documents, reports, invoices) are NEVER
     served directly by Nginx — they go through FastAPI authorization

3. FastAPI request pipeline executes in order:
   a. CORSMiddleware                 — validates origin against allowlist
   b. Request context middleware     — assigns `X-Request-ID`, measures duration
   c. Auth rate-limit middleware     — Redis-backed rate limiting for auth endpoints
   d. Audit middleware               — logs authenticated request metadata + outcome
   e. Route dependencies             — `get_current_user` and `require_permission(...)`

4. Route handler:
   a. Validates input via Pydantic V2 schema
   b. Delegates to Service layer (never contains business logic)

5. Service layer:
   a. Coordinates business workflow
   b. Uses Repository for data access
   c. May enqueue Celery tasks for async work
   d. Returns domain objects or raises typed exceptions

6. Route returns response:
   a. Pydantic schema serializes domain objects to JSON
   b. Consistent paginated envelope or single-resource envelope

7. Nginx logs access, streams response to client
```

### 1.3 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend Framework | React 18 + TypeScript | Component-based UI, strict type safety |
| Build Tool | Vite 6 | Fast HMR, tree shaking, code splitting |
| Styling | Tailwind CSS 3 | Utility-first responsive design |
| Routing | React Router 6 | Client-side routing with lazy loading |
| Server State | TanStack Query 5 | API caching, refetching, optimistic mutations |
| Forms | React Hook Form + Zod | Performant forms with schema validation |
| Charts | Recharts | Declarative React charting |
| HTTP Client | Axios | Interceptors, JWT refresh logic |
| Backend Runtime | Python 3.14 | Backend container runtime (see `backend/Dockerfile`) |
| Backend Framework | FastAPI | Async API framework, auto OpenAPI |
| ORM | SQLAlchemy 2.1 (async) + asyncpg | Async ORM and PostgreSQL driver |
| Migrations | Alembic | Schema versioning, auto-generated from models |
| Validation | Pydantic (via pydantic-settings) | Request/response schemas and settings |
| Auth | python-jose + bcrypt | JWT signing, password hashing |
| Task Queue | Celery 5 + Redis broker | Email, image, report, backup, and maintenance jobs |
| Database | PostgreSQL 18.6 | Primary relational data store |
| Cache/Broker | Redis | Caching, Celery broker, rate-limit counters |
| Object Storage | MinIO | S3-compatible self-hosted file storage |
| Reverse Proxy | Nginx | TLS termination, static files, security headers |
| Container Runtime | Docker + Docker Compose | Consistent dev/prod environments |
| CI/CD | GitHub Actions + launch-owner deployment | Lint, test, build, and Docker validation; deployment execution remains manual |
| Monitoring | Not configured | Metrics can be added later if needed |
| Logging | structlog | Structured JSON logging |

---

## 2. Backend Layered Architecture

This is the foundational architectural rule of the system. The backend is organized into four strictly separated layers. No layer may skip or bypass the layer below it.

### 2.1 The Service Layer Rule

```
THE RULE:
  Routes       -> thin controllers (validate input, call service, return response)
  Services     -> business workflows and orchestration
  Repositories -> data access through SQLAlchemy async sessions
  Models       -> SQLAlchemy ORM table definitions

THIS IS FORBIDDEN:
  - Routes containing business logic or direct database queries
  - Services importing FastAPI Request/Response objects
  - Routes accessing SQLAlchemy sessions directly (must use dependency injection)
  - Any layer importing models from outside its domain
  - Services returning HTTP-layer types (Response, status codes, HTTPException)
```

### 2.2 Layer Diagram

```
+------------------------------------------------------------------+
|                        ROUTE LAYER                                |
|  api/v1/*.py                                                     |
|                                                                   |
|  Responsibilities:                                                |
|  - Define HTTP method, path, status code                          |
|  - Declare Pydantic request/response schemas in decorators        |
|  - Call dependency injection (get_db, get_current_user)           |
|  - Delegate to service layer                                      |
|  - Return response                                                |
|                                                                   |
|  MAX FUNCTION BODY: ~15 lines                                     |
+------------------------------------------------------------------+
        |                               ^
        | calls                         | returns domain objects
        v                               |
+------------------------------------------------------------------+
|                       SERVICE LAYER                                |
|  services/*.py                                                    |
|                                                                   |
|  Responsibilities:                                                |
|  - Business workflow orchestration                                |
|  - Business rule validation (beyond schema-level validation)      |
|  - Transaction coordination (commit boundaries)                   |
|  - Authorization checks ("can this user perform this action?")    |
|  - Enqueuing async tasks (Celery)                                 |
|  - Raising typed business exceptions                              |
|                                                                   |
|  SERVICES NEVER:                                                  |
|  - Import FastAPI Request, Response, or HTTPException             |
|  - Call HTTP-related functions                                    |
|  - Return Pydantic schemas (that's the route layer's job)         |
+------------------------------------------------------------------+
        |                               ^
        | calls                         | returns ORM models
        v                               |
+------------------------------------------------------------------+
|                     REPOSITORY LAYER                               |
|  repositories/*.py                                                |
|                                                                   |
|  Responsibilities:                                                |
|  - CRUD operations with soft-delete awareness                     |
|  - Query building (filtering, sorting, pagination)                |
|  - Eager loading configuration (selectinload, joinedload)         |
|                                                                   |
|  REPOSITORIES NEVER:                                              |
|  - Contain business rules (that's the service layer)              |
|  - Access more than one aggregate root per method                 |
|  - Call external services or enqueue tasks                        |
|  - Commit transactions (that's the service layer's call)          |
+------------------------------------------------------------------+
        |                               ^
        | uses                          | maps to
        v                               |
+------------------------------------------------------------------+
|                       MODEL LAYER                                  |
|  models/*.py                                                      |
|                                                                   |
|  Responsibilities:                                                |
|  - SQLAlchemy ORM table definitions (declarative base)            |
|  - Column types, constraints, indexes                             |
|  - Relationships (with lazy loading strategy)                     |
|  - Hybrid properties (computed columns)                           |
|  - Mixins (TimestampMixin, SoftDeleteMixin)                       |
+------------------------------------------------------------------+
```

### 2.3 Route Layer (Example)

```python
# api/v1/reports.py (illustrative)

from fastapi import APIRouter, Depends, status
from app.api.dependencies import get_db, get_current_user
from app.schemas.daily_reports import DailyReportCreateRequest, DailyReportResponse
from app.services.report_service import ReportService
from app.models.user import User

router = APIRouter(prefix="/reports", tags=["Daily Reports"])

@router.post("/", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def create_report(
    data: DailyReportCreateRequest,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new daily report. All business logic is in ReportService."""
    service = ReportService(db)
    report = await service.create_report(data, current_user)
    return report

@router.get("/", response_model=PaginatedResponse[DailyReportResponse])
async def list_reports(
    params = Depends(),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ReportService(db)
    return await service.list_reports(params, current_user)
```

Key rules:
- Always inject `db` (AsyncSession) and `current_user` via FastAPI `Depends`
- Services are instantiated per-request (they receive the session)
- Never catch exceptions in routes — exception handlers translate them
- Response schemas are always Pydantic models, never SQLAlchemy models

### 2.4 Service Layer (Example)

Services contain all business logic. Each domain area gets one service class.

```python
# services/report_service.py

class ReportService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ReportRepository(db)

    async def create_report(self, data: ReportCreate, user: User) -> DailyReport:
        # Business rule validation
        await self._validate_one_report_per_day(data.project_id, data.report_date)
        await self._validate_project_active(data.project_id)
        await self._validate_user_on_project(user, data.project_id)

        # Generate unique report number
        report_number = await self._generate_report_number(data.project_id, data.report_date)

        # Create via repository
        report = await self.repo.create({
            **data.model_dump(),
            "report_number": report_number,
            "submitted_by": user.id,
            "status": "draft",
        })
        await self.repo.create_manpower_entries(report.id, data.manpower)
        await self.repo.create_equipment_entries(report.id, data.equipment)
        await self.repo.create_material_entries(report.id, data.material_consumption)

        if data.photos:
            await self.repo.link_photos(report.id, data.photos)

        await self.db.commit()
        return report

    async def submit_for_approval(self, report_id: UUID, user: User):
        report = await self.repo.get_by_id(report_id)
        self._validate_can_submit(report, user)

        approvers = await self._resolve_approval_chain(report.project_id)

        approval_service = ApprovalService(self.db)
        await approval_service.create_chain(
            request_type="daily_report",
            request_id=report_id,
            requested_by=user.id,
            approvers=approvers,
        )

        report.status = "submitted"
        await self.db.commit()

        # Async notification via Celery
        notify_approvers.delay(str(report_id))
```

Rules:
- One service class per domain (ReportService, ProjectService, InventoryService, etc.)
- Services receive `db: AsyncSession` in constructor
- Services may call other services for cross-domain operations
- Services commit transactions explicitly
- Services never touch HTTP concerns (request, response, status codes)
- **Return-type convention**: Services return SQLAlchemy ORM models. Routes declare Pydantic `response_model` with `from_attributes=True` to handle serialization. This is the pragmatic FastAPI pattern — it keeps the code simple and avoids an unnecessary mapping layer for MVP. If a domain grows complex enough to warrant separate internal DTOs, that refactor is scoped to the service layer without changing routes.

### 2.5 Repository Layer (Example)

```python
# repositories/daily_report_repository.py (illustrative)

class ReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, report_id: UUID) -> DailyReport | None:
        stmt = (
            select(DailyReport)
            .options(
                selectinload(DailyReport.manpower),
                selectinload(DailyReport.equipment),
                selectinload(DailyReport.material_consumption),
                selectinload(DailyReport.photos),
            )
            .where(DailyReport.id == report_id)
            .where(DailyReport.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def list_paginated(self, filters: dict, pagination: PaginationParams) -> tuple[list[DailyReport], int]:
        base = select(DailyReport).where(DailyReport.deleted_at.is_(None))

        if filters.get("project_id"):
            base = base.where(DailyReport.project_id == filters["project_id"])
        if filters.get("status"):
            base = base.where(DailyReport.status == filters["status"])
        if filters.get("from_date"):
            base = base.where(DailyReport.report_date >= filters["from_date"])
        if filters.get("to_date"):
            base = base.where(DailyReport.report_date <= filters["to_date"])

        # Count total matching records
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(count_stmt)).scalar()

        # Apply pagination and ordering
        stmt = (
            base.order_by(DailyReport.report_date.desc())
            .offset(pagination.offset)
            .limit(pagination.per_page)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all(), total

    async def create(self, data: dict) -> DailyReport:
        report = DailyReport(**data)
        self.db.add(report)
        await self.db.flush()  # get generated UUID without committing
        return report
```

Rules:
- Always include `deleted_at.is_(None)` in every query
- Use `selectinload` for eager loading (avoid N+1 queries)
- Use `await self.db.flush()` in create to get generated UUID
- Return SQLAlchemy ORM models, never dicts
- Never call `await self.db.commit()` — the service layer owns transaction boundaries
- Repositories are data-access only — no caching, no business rules, no external calls.
  Caching decisions belong in the service layer, using a dedicated cache module that
  encapsulates Redis get/set/invalidate. Cache aggressively for low-risk reads
  (user permission cache, dashboard summaries, reference data) but avoid caching
  inventory stock quantities, approval inboxes, audit logs, or financial records.

### 2.6 Model Mixins

```python
# models/base.py

class TimestampMixin:
    created_at = Column(TIMESTAMPTZ, default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMPTZ, default=func.now(), onupdate=func.now(), nullable=False)

class SoftDeleteMixin:
    deleted_at = Column(TIMESTAMPTZ, nullable=True)
```

### 2.7 Middleware & Dependencies

The request pipeline uses two distinct mechanisms — global Starlette middleware and FastAPI route dependencies — applied at different scopes for different purposes.

**Global middleware** (applies to every request, including health checks):

| Order | Middleware | Responsibility | Library / Module |
|-------|-----------|---------------|-----------------|
| 1 | CORS | Validate origin against allowlist | `fastapi.middleware.cors` |
| 2 | Request context | Attach `X-Request-ID` and request timing to response headers | `backend/app/main.py` |
| 3 | Auth rate limiting | Protect auth endpoints using Redis counters | `backend/app/main.py` + `app/middleware/rate_limit.py` |
| 4 | Audit logging | Persist authenticated request audit records with response status | `backend/app/main.py` + `app/middleware/audit.py` |

**Route-level dependencies** (applied via `Depends()` on API routes only):

| Order | Dependency | Responsibility | Implementation |
|-------|-----------|---------------|----------------|
| 1 | `get_current_user` | Validate JWT (Bearer token) and resolve user | `backend/app/api/dependencies.py` |
| 2 | `require_permission(...)` | Check user role against endpoint permission | `backend/app/api/dependencies.py` |

Audit logging is implemented as HTTP middleware so it can observe the final response status code.

### 2.8 Task Layer (Celery Workers)

All operations that should not block the HTTP request/response cycle are handled by Celery. Task modules live in `backend/app/tasks/`.

| Task Module | Typical Workloads |
|------------|--------------------|
| `tasks/report.py` | Generate report PDFs and exports |
| `tasks/image.py` | Photo compression + thumbnail generation |
| `tasks/email.py` | Email notifications (exception alerts, workflow emails) |
| `tasks/approval.py` | Approval reminders and background approval processing |
| `tasks/imports.py` | Bulk import execution |
| `tasks/backup.py` | Database backup creation + retention |
| `tasks/maintenance.py` | Retention cleanups, log archiving, and periodic housekeeping |

All tasks share `tasks/base.py:LoggedTask` as the task base class, which wires structured logging and request-context propagation into every Celery execution.

### 2.9 Exception Handling

Services raise typed application exceptions. FastAPI exception handlers translate them to consistent JSON error responses:

```python
# utils/exceptions.py

class AppException(Exception):
    def __init__(self, message: str, status_code: int = 400, detail: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}

class NotFoundException(AppException):
    def __init__(self, entity: str, id: UUID):
        super().__init__(f"{entity} not found", status_code=404)

class PermissionDeniedException(AppException):
    def __init__(self, action: str):
        super().__init__(f"Permission denied: {action}", status_code=403)

class BusinessRuleException(AppException):
    def __init__(self, message: str):
        super().__init__(message, status_code=409)
```

Error response format:

```json
{
  "detail": "Cannot submit report: project is on hold",
  "error_code": "PROJECT_NOT_ACTIVE",
  "errors": []
}
```

---

## 3. Frontend Architecture

### 3.1 Component Tree

```
<App>
  <QueryClientProvider>          -- TanStack Query
    <AuthProvider>               -- AuthContext (user, tokens, login/logout)
      <ThemeProvider>            -- ThemeContext (light/dark — future)
        <BrowserRouter>
          <Routes>
            // Public routes
            <LoginPage />
            <ForgotPasswordPage />

            // Protected routes (wrapped in <RequireAuth>)
            <AppLayout>
              <Sidebar />        -- Desktop navigation
              <Header />         -- Breadcrumbs, search, notifications, user menu
              <MobileNav />      -- Bottom navigation (mobile)
              <OfflineIndicator />
              <Outlet />         -- Page content
            </AppLayout>
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </AuthProvider>
  </QueryClientProvider>
</App>
```

The primary structure is visible in `frontend/src/` (router, pages, components, and API client).

### 3.2 State Management Strategy

A four-tier approach — no global store like Redux is needed:

| State Type | Tool | Scope | Example |
|-----------|------|-------|---------|
| **Auth State** | React Context (AuthContext) | Application root | User object, role, access token, login/logout |
| **Server State** | TanStack Query | QueryClient cache | Reports list, project detail, notifications, dashboard stats |
| **Form State** | React Hook Form + Zod | Local to form | Daily report form, project create form, material request |
| **UI State** | useState / useReducer | Local to component | Sidebar collapsed, modal open, active tab, filter values |
| **Offline State** | IndexedDB (via `idb`) | Browser storage | Draft reports, pending sync queue, cached reference data |

**Why no Redux:** The application's state complexity does not warrant a global store. TanStack Query handles all server-state caching, invalidation, and refetching. UI state is local and simple enough for `useState`/`useReducer`. This eliminates Redux boilerplate (actions, reducers, selectors, thunks) and simplifies the mental model.

### 3.3 Data Flow

```
User Action
    |
    v
Page Component
    |
    +---> React Hook Form (form input)
    |         |
    |         v
    |     Zod Validation (client-side)
    |         |
    |         v
    |     API Client module (api/*.ts)
    |         |
    |         v
    |     Axios Instance (JWT interceptor)
    |         |
    |         v
    |     HTTP POST/PATCH to FastAPI
    |
    +---> TanStack Query (data fetch)
              |
              v
          useQuery / useMutation hook
              |
              v
          API Client module (api/*.ts)
              |
              v
          Axios Instance
              |
              v
          HTTP GET to FastAPI
              |
              v
          Cached in QueryClient
              |
              v
          Component re-renders with data
```

### 3.4 API Client Layer

```typescript
// api/client.ts

const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

// Request interceptor: attach access token
apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor: silent token refresh on 401
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      const newToken = await refreshAccessToken();
      original.headers.Authorization = `Bearer ${newToken}`;
      return apiClient(original);
    }
    return Promise.reject(error);
  }
);
```

Domain-specific API modules:

```
api/auth.ts               — login, OTP, refresh, logout, me
api/users.ts              — user management CRUD
api/projects.ts           — list, get, create, update, timeline, members
api/reports.ts            — create, list, get, update, submit, approve, reject
api/supervisorUpdates.ts  — supervisor update submissions
api/approvals.ts          — inbox, approve, reject
api/documents.ts          — list, upload, download, versions, search
api/photos.ts             — upload, list, download, thumbnail
api/inventory.ts          — items, locations, stock, assets, movements, requests
api/finance.ts            — invoices, payments
api/analytics.ts          — summaries, Excel export
api/dashboard.ts          — summary, progress, material-usage, approval-stats
api/notifications.ts      — list, unread-count, mark-read
api/imports.ts            — bulk import preview/confirm
api/audit.ts              — audit log queries
api/fileUrls.ts           — presigned URL normalization helpers
api/offlineQueue.ts       — IndexedDB offline queue helpers
api/client.ts             — shared axios instance + interceptors
api/schema.d.ts           — OpenAPI-generated types
```

### 3.5 PWA & Offline Strategy (Phase 3)

| Capability | Implementation | Phase |
|-----------|---------------|-------|
| App Shell Caching | Service Worker caches HTML/CSS/JS | Phase 3 |
| Offline Draft Reports | IndexedDB stores drafts; auto-sync when online | Phase 3 |
| Offline Photo Queue | Photos saved to IndexedDB; uploaded on reconnect | Phase 3 |
| Install Prompt | Web App Manifest with icons, name, theme color | Phase 3 |
| Camera Capture | `<input type="file" capture="environment">` | Phase 1 |
| Form Autosave | Auto-save every 30s and on field blur | Phase 1 |
| Optimistic Updates | TanStack Query `onMutate` for instant UI feedback | Phase 1 |

#### Idempotency and Conflict Prevention

Offline submissions over weak mobile networks risk duplicate records when retries are triggered before the client receives the server's response. Every offline-originated create operation (daily reports, photo uploads) must be idempotent.

**Client-generated IDs**: Each draft created offline receives a `client_id` (UUID v4) generated by the frontend before the record is stored in IndexedDB. This ID is included in the sync payload and used by the server for deduplication.

**Idempotency key header**:

```http
POST /api/v1/reports
Idempotency-Key: <client_generated_uuid>
```

**Server-side handling**: The API endpoint checks the idempotency key against previously processed requests (cached in Redis with a 24-hour TTL). If the key was already processed successfully, the server returns the stored response (200 with the existing record) instead of creating a duplicate.

**Sync record fields** — each offline draft tracks:

```
client_id          — UUID generated client-side before first save
idempotency_key   — same UUID, sent as Idempotency-Key header on sync
sync_status        — "draft" | "pending" | "synced" | "conflict"
last_sync_attempt  — timestamp of most recent sync attempt
server_version     — server-side `updated_at` after successful sync
conflict_status    — null | "server_newer" | "rejected"
```

**Conflict resolution**: If a server record has been modified (e.g., approved by PM) since the client last synced, the sync is rejected with status 409 and `conflict_status: "server_newer"`. The client surfaces the conflict and offers the user a choice: discard the local draft or force-resubmit (which creates a new report version or resubmission request).

### 3.6 Component Design Principles

1. **Small primitives**: UI components live under `components/ui/` and are composed into pages
2. **One component, one file**: Each component is a single `.tsx` file with co-located types
3. **Composition over configuration**: Components use `children` and render props, not giant config objects
4. **Loading, empty, and error states are mandatory**: Every data-dependent component handles all three
5. **Mobile-first responsive**: Tailwind `sm:`, `md:`, `lg:` breakpoints; bottom nav on mobile; collapsible sidebar on desktop

---

## 4. Data Architecture

### 4.1 Schema Overview

Schema documentation in `docs/schema/` currently covers 32 tables organized into domain groups:

| Group | Tables |
|-------|--------|
| Identity & Access | `users`, `auth_otp_challenges`, `auth_refresh_tokens` |
| Projects & Planning | `projects`, `project_members`, `project_milestones`, `project_tasks`, `boq_items` |
| Daily Reporting | `daily_reports`, `report_manpower`, `report_equipment`, `report_material_consumption`, `daily_report_approval_history`, `report_exports`, `supervisor_updates` |
| Inventory & Stores | `suppliers`, `storage_locations`, `inventory_items`, `inventory_location_stock`, `inventory_assets`, `inventory_movements`, `material_requests`, `material_request_lines` |
| Documents & Media | `documents`, `document_versions`, `photos` |
| Workflow & Comms | `approvals`, `notifications` |
| Accounts & Finance | `invoices`, `payments` |
| Governance | `activity_log`, `import_batches` |

Full per-table details live in [schema/](schema/) and are the source of truth for the current schema.

### 4.2 Entity Relationship Summary

```
users --o< project_members >o-- projects
projects --o< project_milestones
projects --o< boq_items
projects --o< daily_reports
daily_reports --o< report_manpower
daily_reports --o< report_equipment
daily_reports --o< report_material_consumption
inventory_items --o< inventory_location_stock >o-- storage_locations
inventory_items --o< inventory_assets
inventory_items --o< inventory_movements
inventory_movements --o storage_locations (from/to)
inventory_movements --o approvals (authorized by)
documents --o< document_versions
photos -- polymorphic (entity_type + entity_id)
approvals -- polymorphic (request_type + request_id)
notifications --o users
invoices --o< payments
```

### 4.3 Cross-Cutting Schema Rules

1. **UUID Primary Keys**: Every table uses `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`. Not sequentially guessable; works across distributed systems.

2. **Soft Deletes**: All user-facing tables use `deleted_at TIMESTAMPTZ`. Every repository query filters `WHERE deleted_at IS NULL` by default. Deleted records retained 30 days before permanent cleanup (Celery task).

3. **Timestamps**: All mutable business records have `created_at` and `updated_at`. An `update_timestamp()` trigger auto-sets `updated_at = NOW()`.

4. **Immutability After Approval**: Once a record is approved (daily reports, documents), its core fields become immutable. Changes require a new version or resubmission workflow.

5. **Files in Object Storage**: PostgreSQL stores only metadata (filename, storage path, MIME type, size). Binary data lives in MinIO.

6. **Polymorphic Associations**: `photos`, `approvals`, `activity_log` use `entity_type` + `entity_id` to reference multiple parent table types.

7. **JSONB for Flexible Fields**: `daily_reports.extra_fields` for project-specific custom form sections. `activity_log.old_values` and `new_values` for audit snapshots.

### 4.4 Index Strategy

- **Partial unique indexes for soft-delete safety** — Any uniqueness constraint that should only apply to active (non-deleted) rows must use a partial unique index, not a standard UNIQUE constraint. PostgreSQL treats NULLs in a UNIQUE constraint as distinct values, so `UNIQUE(project_id, report_date, deleted_at)` would allow duplicate active rows where `deleted_at IS NULL`. Use instead:
  ```sql
  CREATE UNIQUE INDEX uq_daily_reports_project_date_active
  ON daily_reports(project_id, report_date)
  WHERE deleted_at IS NULL;
  ```
  This pattern applies wherever uniqueness must be enforced only for non-deleted records (report numbers, document revisions, inventory item codes, etc.).
- **Partial indexes** with `WHERE deleted_at IS NULL` — smaller and faster since queries always exclude soft-deleted records
- **Composite indexes** for multi-column query patterns (e.g., `(approver_id, status)` on `approvals` for inbox queries)
- **GIN indexes on JSONB** — `daily_reports.extra_fields` for querying custom form fields
- **GIN indexes on tsvector** — `documents.title` for full-text search
- **Covering indexes** — include frequently queried columns to avoid heap lookups

### 4.5 Migration Strategy

- **Alembic** for all schema migrations
- Auto-generated from SQLAlchemy models (`alembic revision --autogenerate`)
- Every migration includes `upgrade()` and `downgrade()` paths
- Migrations applied in CI before deployment and verified
- Seed data managed via `scripts/seed.py`, not migrations

---

## 5. Security Architecture

### 5.1 Authentication Flow

```
LOGIN:
  1. Client POST /api/v1/auth/login { email, password }
  2. Server validates password against bcrypt hash
  3. Server generates:
     - access_token (JWT, RS256, 15 min expiry) — returned in JSON body
     - refresh_token (JWT, 1 day expiry) — set as HttpOnly, Secure, SameSite=Strict cookie;
       stored hashed in DB for rotation/revocation
  4. Server returns { access_token, token_type, user }
     (Refresh token is never exposed to JavaScript — it arrives only as a cookie.)

TOKEN REFRESH (silent):
  1. Client detects 401 or near-expiry access token
  2. Client POST /api/v1/auth/refresh (browser sends refresh_token cookie automatically)
  3. Server validates refresh_token from cookie, rotates it (new token issued, old hashed token invalidated)
  4. Server sets new refresh_token cookie and returns { access_token }

EVERY AUTHENTICATED REQUEST:
  1. Client sends Authorization: Bearer <access_token>
  2. Auth dependency decodes JWT, extracts user_id
  3. Fetches user from DB (cached in Redis for 5 minutes)
  4. Attaches user to request.state.user
  5. RBAC dependency checks role permission for endpoint

TOKEN STORAGE RATIONALE:
  - access_token: Stored in memory only (JavaScript variable). Short 15-minute TTL limits exposure.
  - refresh_token: HttpOnly Secure SameSite=Strict cookie. Inaccessible to JavaScript,
    never sent cross-site, automatically included on /auth/refresh requests.
    This prevents token theft via XSS and reduces CSRF risk.

PASSWORD POLICIES:
  - Minimum 8 characters: uppercase + lowercase + number + symbol
  - Forced password change on first login
  - Account lockout after 3 failed attempts (30-minute cooldown)
  - Password reset via Admin or email OTP
```

### 5.2 RBAC Matrix

| Permission | Admin | OpMgr | ProjMgr | CivEng | CivSup | StoreKpr | Accounts |
|-----------|-------|-------|---------|--------|--------|----------|----------|
| Dashboard (company-wide) | Full | Full | -- | -- | -- | -- | -- |
| Dashboard (scoped) | -- | -- | Own Projects | Own Projects | Own Projects | Inventory | Financial |
| Users: Manage | Full | Read | -- | -- | -- | -- | -- |
| Projects: CRUD | Full | Full | Own Projects | Read | Read | -- | Read |
| Reports: Submit | -- | -- | -- | Yes | Updates only | -- | -- |
| Reports: Approve | Full | All | Own Projects | -- | -- | -- | -- |
| Reports: View | Full | All | Own Projects | Own Projects | Own Projects | -- | All |
| Inventory: View | Full | All | All | Request | -- | Full | -- |
| Inventory: Manage | Full | -- | -- | -- | -- | Full | -- |
| Inventory: Transfer/Issue | Full | -- | -- | -- | -- | Full | -- |
| Material Pricing: View | Full | Yes | Optional | -- | -- | Yes | Yes |
| Documents: Manage | Full | Read All | Own Projects | Upload/Read | Read | -- | Invoices |
| Approvals: Decide | Full | Escalated | Own Projects | -- | -- | Material | Invoices |
| Approvals: Override | Full | -- | -- | -- | -- | -- | -- |
| Audit Log: View | Full | -- | -- | -- | -- | -- | -- |
| Financial: View | Full | Yes | Read | -- | -- | -- | Full |
| Notifications: Receive | Yes | Yes | Yes | Yes | Yes | Yes | Yes |

### 5.3 Security Headers (Nginx)

```
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline';" always;
add_header Permissions-Policy "camera=(self), microphone=(), geolocation=()" always;
# camera=(self) allows photo capture via <input capture="environment"> for site reports.
# microphone and geolocation remain disabled until a confirmed requirement.
```

### 5.4 File Upload Security

1. **Type whitelist**: JPG, PNG, HEIC, PDF, XLSX, DOCX, DWG
2. **Blocked**: `.exe`, `.sh`, `.bat`, `.cmd`, `.js`, `.php`, `.html`, unknown binaries
3. **Size limits**: 10 MB per photo, 60 MB per document
4. **Validation**: Server validates MIME type by magic bytes, not just extension
5. **Storage**: Files stored in MinIO with randomized object keys; original filenames only in DB metadata
6. **Presigned URLs**: Direct upload to MinIO via presigned URLs (no file data passes through FastAPI)
7. **Access control**: Download URLs are signed and temporary; access is checked per-request against user permissions. Private files (photos, documents, drawings, invoices, reports) are never served directly by Nginx. The flow is: (1) Client requests file via FastAPI, (2) FastAPI checks RBAC and project access, (3) FastAPI returns a short-lived MinIO presigned URL, (4) Client downloads directly from MinIO, (5) Audit log records the download.
8. **Watermarking**: Photos watermarked with company name during Celery processing

### 5.5 Additional Measures

- **SQL Injection**: Prevented by SQLAlchemy parameterized queries
- **XSS**: React auto-escapes by default; CSP header blocks inline scripts
- **CSRF**: SameSite=Strict cookies; JWT in Authorization header (not cookies)
- **PII**: Email and phone stored; password only as bcrypt hash; audit logs never capture passwords
- **Backup encryption**: Database backups encrypted at rest in MinIO

---

## 6. API Design Principles

### 6.1 REST Conventions

| Convention | Rule |
|-----------|------|
| Base URL | `/api/v1` |
| Resource naming | Plural nouns: `/reports`, `/projects`, `/documents` |
| Nested resources | `/projects/{id}/members`, `/documents/{id}/versions` |
| HTTP methods | GET (read), POST (create), PATCH (partial update), DELETE (soft delete) |
| Content-Type | `application/json`; `multipart/form-data` for file uploads |
| Auth header | `Authorization: Bearer <access_token>` |
| Date format | ISO 8601: `2026-05-14T10:30:00+05:30` |

### 6.2 Pagination

All list endpoints use a consistent pagination contract:

**Request:** `?page=1&per_page=20&sort_by=report_date&sort_order=desc`

| Param | Type | Default | Max |
|-------|------|---------|-----|
| `page` | int | 1 | — |
| `per_page` | int | 20 | 100 |
| `sort_by` | string | varies by endpoint | — |
| `sort_order` | string | desc | — |

**Response envelope:**

```json
{
  "items": [ ... ],
  "total": 156,
  "page": 1,
  "per_page": 20,
  "total_pages": 8
}
```

### 6.3 Versioning

- URL-prefix versioning: `/api/v1/`, `/api/v2/`
- v1 is the only active version for initial release
- Breaking changes introduce a new version; old versions deprecated with 6-month sunset
- Non-breaking additions (new fields, new endpoints) can be added to v1

### 6.4 Error Response Format

```json
{
  "detail": "Human-readable error description",
  "error_code": "MACHINE_READABLE_CODE",
  "errors": [
    { "field": "report_date", "message": "Report date cannot be in the future" }
  ]
}
```

HTTP status code mapping:

| Status | Meaning | When Used |
|--------|---------|-----------|
| 200 | OK | Successful GET, PATCH |
| 201 | Created | Successful POST |
| 204 | No Content | Successful DELETE (soft) |
| 400 | Bad Request | Malformed input |
| 401 | Unauthorized | Missing or expired JWT |
| 403 | Forbidden | Valid JWT but insufficient role |
| 404 | Not Found | Resource not found or soft-deleted |
| 409 | Conflict | Business rule violation |
| 413 | Payload Too Large | File exceeds size limit |
| 422 | Unprocessable Entity | Pydantic validation errors |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Unexpected server error |

### 6.5 Filtering

List endpoints support common filter parameters:

| Param | Example | Description |
|-------|---------|-------------|
| `search` | `?search=Tower+A` | Free-text search (ILIKE or tsvector) |
| `status` | `?status=active` | Filter by enum status |
| `project_id` | `?project_id=<uuid>` | Filter by parent project |
| `from_date` | `?from_date=2026-01-01` | Inclusive start date |
| `to_date` | `?to_date=2026-05-31` | Inclusive end date |

### 6.6 Bulk Operations

- **Import**: `POST /import/users` with multipart file (CSV/XLSX), processed asynchronously via Celery
- **Export**: `GET /export/reports?project_id=&from=&to=` returns file download (XLSX or PDF)
- Large exports (>1000 rows) return `202 Accepted` with task ID; client polls `GET /export/tasks/{id}`

---

## 7. Deployment Architecture

### 7.1 Docker Compose Services

```
services:
  nginx:
    image: nginx:1.25-alpine
    ports: ["80:80", "443:443"]
    volumes: [./nginx/nginx.conf, ./nginx/ssl, frontend_dist:/usr/share/nginx/html]
    depends_on: [backend]
    # Serves: built frontend static files, /assets/*, reverse-proxies /api/* to FastAPI
    # Does NOT serve private files — those go through FastAPI → MinIO presigned URLs

  backend:
    build: ./backend
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
    environment: [DATABASE_URL, REDIS_URL, MINIO_ENDPOINT, JWT_SECRET, ...]
    depends_on: [postgres, redis, minio]
    volumes: [./backend:/app]  # Dev only: hot reload

  celery_worker:
    build: ./backend
    command: celery -A app.tasks worker -Q email,image,report,backup,maintenance --concurrency=4
    environment: [same as backend]
    depends_on: [postgres, redis, minio]

  celery_beat:
    build: ./backend
    command: celery -A app.tasks beat
    depends_on: [redis]

  postgres:
    image: postgres:18.6-alpine
    environment: [POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD]
    volumes: [pgdata:/var/lib/postgresql]
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes: [redisdata:/data]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment: [MINIO_ROOT_USER, MINIO_ROOT_PASSWORD]
    volumes: [miniodata:/data]
    ports: ["9000:9000", "9001:9001"]

volumes:
  pgdata:
  redisdata:
  miniodata:
```

### 7.2 Development vs Production

| Aspect | Development | Production |
|--------|-------------|------------|
| Backend reload | Uvicorn `--reload` | Uvicorn with 4 workers |
| Frontend serve | Vite dev server (port 3000) | Static files served by Nginx |
| Database | Single PostgreSQL | PostgreSQL with streaming replica |
| Redis | Single instance | Redis with AOF persistence |
| MinIO | Single instance | MinIO with erasure coding |
| Debug logging | Enabled (DEBUG) | Disabled (WARNING+) |
| CORS | Allow localhost origins | Strict origin allowlist |
| Rate limiting | Disabled | Enabled |
| Monitoring | None | Not configured |

### 7.3 CI Pipeline

Defined in `.github/workflows/ci.yml`. Runs on every pull request and on pushes to
`main`; in-progress runs for the same ref are cancelled when a new commit arrives.
The four jobs are independent and run in parallel — there is no lint/test/build
sequencing, because none of the jobs depend on another's output.

```
PULL REQUEST  /  PUSH TO main
    |
    +--> [backend-static]     ruff check .  +  mypy .            (Python 3.14)
    |
    +--> [frontend]           npm ci -> lint -> api:types:check
    |                         -> test (Vitest) -> build          (Node 24)
    |
    +--> [compose-validate]   docker compose config --quiet for
    |                         docker-compose.prod.yml and
    |                         docker-compose.staging.yml
    |
    +--> [backend-tests]      PostgreSQL 18.6, Redis 7, and Moto S3
                              service containers -> alembic upgrade head
                              -> pytest -q -rs
```

The jobs mirror the local verification commands documented in `README.md`, so a
clean local run predicts a clean CI run.

`backend-tests` remains advisory (`continue-on-error: true`). Check its individual
job result for integration test status. Database-backed tests skip when PostgreSQL
is unreachable.

Deployment is **not** automated. There is no deploy job, no environment gate, and no
smoke-test stage. Staging and production releases are performed manually by the
launch owner following `STAGING_DEPLOYMENT.md` and `docs/OPERATIONS_AND_DEPLOYMENT.md`,
which includes running `alembic upgrade head` against the target environment.

### 7.4 Backup Strategy

| Backup Type | Frequency | Retention | Storage |
|------------|-----------|-----------|---------|
| Full DB dump (pg_dump) | Daily (Celery Beat) | 30 days | MinIO + encrypted offsite |
| WAL archiving | Continuous | 7 days | MinIO |
| Monthly archive | Monthly | 12 months | Encrypted offsite |
| MinIO bucket sync | Daily | 30 days | Secondary MinIO or cloud |
| Restore test | Monthly | — | Verify latest backup integrity |

---

## 8. Cross-Cutting Concerns

### 8.1 Logging

- **Backend and workers**: one `structlog`/standard-library JSON pipeline configured in
  `app/observability/`, with request/task correlation, recursive sensitive-value redaction, structured
  exception traces, and an environment-controlled minimum level.
  - Production defaults to `INFO`; temporary `DEBUG` is enabled only through `LOG_LEVEL`.
  - Every record includes timestamp, severity, logger, environment, service, and instance identifiers.
  - HTTP completion records include normalized route, status, duration, and request correlation.
- **Operational aggregation**: Grafana Alloy discovers Docker containers and sends stdout to Loki.
  Loki uses TSDB indexes and a dedicated MinIO bucket with 14-day Compactor retention. Grafana uses a
  dedicated PostgreSQL database and provisioned dashboards, queries, SMTP alerts, and a Loki data source.
  Grafana is exposed only through its HTTPS Nginx virtual host; Loki and Alloy remain internal.
- **Defence in depth for log data**: the application recursively redacts sensitive keys, bearer/JWT
  patterns, credential-bearing URLs, and credential-like query parameters before JSON serialization;
  Alloy applies an additional pattern-redaction stage before Loki ingestion. Request IDs, task IDs,
  users, sessions, and endpoints remain parsed fields rather than Loki labels.
- **Failure isolation**: Grafana, Loki, and Alloy are not in the application request path. Docker's
  rotated `json-file` output remains available if collection or storage is unavailable, while
  PostgreSQL `activity_log` remains the authoritative business/audit record.
- **Centralized event log**: Stored in `activity_log` with standardized fields such as `event_type`, `severity`, `request_id`, `session_id`, `endpoint`, `source_service`, `storage_tier`, and `context_payload`
- **Remote access**: Search and real-time streaming are available through the secured log API and `backend/scripts/log_cli.py`
- **Frontend**: Console logging in dev only; production errors captured via `POST /api/v1/logs/client-error`

Operational usage is documented in [LOGGING_AND_REMOTE_CLI.md](./LOGGING_AND_REMOTE_CLI.md).

### 8.2 Error Handling (Frontend)

- **API errors**: Axios interceptor catches non-2xx. 401 triggers silent token refresh. 403 shows "Access Denied". 5xx shows error toast.
- **React errors**: `ErrorBoundary` wraps each route segment; captures crash info; shows fallback UI.
- **Form errors**: React Hook Form displays field-level errors from Zod (client) and 422 responses (server).
- **Network errors**: `OfflineIndicator` banner when `navigator.onLine` is false.

### 8.3 Audit Trail

Every auditable action is recorded in `activity_log`:

| Action | Fields Recorded |
|--------|----------------|
| Create | `user_id`, `action='create'`, `entity_type`, `entity_id`, `new_values` (JSONB) |
| Update | `user_id`, `action='update'`, `entity_type`, `entity_id`, `old_values`, `new_values` |
| Soft Delete | `user_id`, `action='delete'`, `entity_type`, `entity_id`, `old_values` |
| Login | `user_id`, `action='login'`, `ip_address`, `user_agent` |
| Logout | `user_id`, `action='logout'` |
| Approve/Reject | `user_id`, `action='approve'/'reject'`, `entity_type`, `entity_id`, `comments` |
| Download | `user_id`, `action='download'`, `entity_type='document'/'photo'`, `entity_id` |
| Admin Override | `user_id`, `action='admin_override'`, `entity_type`, `entity_id`, `comments`, `old_values`, `new_values` |

Audit and event-log access is admin-controlled through RBAC. For remote usage, filtering, and streaming examples, see [LOGGING_AND_REMOTE_CLI.md](./LOGGING_AND_REMOTE_CLI.md).

### 8.4 Notification System

1. **Trigger**: Service layer calls `notification_service.create(...)` or Celery task creates bulk notifications
2. **In-App**: Stored in `notifications` table; client polls `GET /notifications/unread-count` every 60 seconds
3. **Email**: Celery task `send_email_notification` via SMTP (or SendGrid/Mailgun in production)
4. **Retention**: 90 days for user-facing notifications, then purged by Celery Beat

### 8.5 Health Checks

- `GET /health` — `{"status": "ok"|"degraded", "database": "connected"|"unavailable", "redis": "not_checked"}` for load balancer / Docker healthcheck
- `GET /health/readiness` — checks database connectivity before marking container ready

---

## 9. Directory & Project Structure

```
garrison-investments/
│
├── README.md
├── docs/ARCHITECTURE.md
├── .env.example
├── .gitignore
├── docker-compose.yml                 # Development
├── docker-compose.staging.yml         # Staging
├── docker-compose.prod.yml            # Production
│
├── docs/                              # Planning & design docs
│   ├── README.md
│   ├── ARCHITECTURE.md
│   ├── OPERATIONS_AND_DEPLOYMENT.md
│   ├── ROLES_AND_PERMISSIONS.md
│   ├── LOGGING_AND_REMOTE_CLI.md
│   ├── PRODUCTION_READINESS_REVIEW.md
│   ├── openapi.json
│   ├── schema/                        # Per-table schema reference (32 tables)
│   └── import_templates/
│
├── nginx/
│   ├── nginx.conf                     # Reverse proxy + TLS + security headers
│   ├── nginx.prod.conf                # Production config
│   └── ssl/                           # TLS certificates (gitignored)
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI app entry point
│   │   ├── config.py                  # Pydantic Settings (env vars)
│   │   ├── database.py                # Async engine + session factory
│   │   │
│   │   ├── models/                    # SQLAlchemy ORM models
│   │   │   ├── __init__.py
│   │   │   ├── base.py                # TimestampMixin, SoftDeleteMixin
│   │   │   ├── user.py
│   │   │   ├── project.py
│   │   │   ├── project_member.py
│   │   │   ├── project_milestone.py
│   │   │   ├── boq_item.py
│   │   │   ├── daily_report.py
│   │   │   ├── approval.py
│   │   │   ├── auth.py
│   │   │   ├── document.py
│   │   │   ├── finance.py
│   │   │   ├── import_batch.py
│   │   │   ├── inventory.py
│   │   │   ├── notification.py
│   │   │   ├── photo.py
│   │   │   ├── project_task.py
│   │   │   ├── report_export.py
│   │   │   ├── supervisor_update.py
│   │   │   ├── supplier.py
│   │   │   └── activity_log.py
│   │   │
│   │   ├── schemas/                   # Pydantic V2 request/response schemas
│   │   │   ├── __init__.py
│   │   │   ├── common.py              # PaginatedResponse, ErrorResponse, filters
│   │   │   ├── analytics.py
│   │   │   ├── approvals.py
│   │   │   ├── audit.py
│   │   │   ├── auth.py
│   │   │   ├── daily_reports.py
│   │   │   ├── dashboard.py
│   │   │   ├── documents.py
│   │   │   ├── finance.py
│   │   │   ├── imports.py
│   │   │   ├── inventory.py
│   │   │   ├── notifications.py
│   │   │   ├── photos.py
│   │   │   ├── projects.py
│   │   │   ├── supervisor_updates.py
│   │   │   ├── suppliers.py
│   │   │   └── users.py
│   │   │
│   │   ├── api/                       # Route handlers (THIN — no business logic)
│   │   │   ├── __init__.py
│   │   │   ├── dependencies.py        # get_db, get_current_user, require_permission
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── router.py          # Aggregates all v1 routers
│   │   │       ├── analytics.py
│   │   │       ├── auth.py
│   │   │       ├── audit.py
│   │   │       ├── dashboard.py
│   │   │       ├── documents.py
│   │   │       ├── finance.py
│   │   │       ├── imports.py
│   │   │       ├── users.py
│   │   │       ├── projects.py
│   │   │       ├── reports.py
│   │   │       ├── inventory.py
│   │   │       ├── suppliers.py
│   │   │       ├── approvals.py
│   │   │       ├── notifications.py
│   │   │       ├── photos.py
│   │   │       ├── supervisor_updates.py
│   │   │       └── logs.py            # Centralized log-event queries + streaming
│   │   │
│   │   ├── services/                  # Business logic layer
│   │   │   ├── analytics_service.py
│   │   │   ├── auth_service.py
│   │   │   ├── audit_service.py
│   │   │   ├── approval_service.py
│   │   │   ├── dashboard_service.py
│   │   │   ├── document_service.py
│   │   │   ├── email_service.py
│   │   │   ├── exception_reporter.py
│   │   │   ├── finance_service.py
│   │   │   ├── import_service.py
│   │   │   ├── user_service.py
│   │   │   ├── project_service.py
│   │   │   ├── report_service.py
│   │   │   ├── report_export_service.py
│   │   │   ├── reporting_service.py
│   │   │   ├── inventory_service.py
│   │   │   ├── supplier_service.py
│   │   │   ├── photo_service.py
│   │   │   ├── notification_service.py
│   │   │   └── storage_service.py
│   │   │
│   │   ├── repositories/              # Data access layer
│   │   │   ├── approval_repository.py
│   │   │   ├── auth_repository.py
│   │   │   ├── daily_report_repository.py
│   │   │   ├── document_repository.py
│   │   │   ├── notification_repository.py
│   │   │   ├── photo_repository.py
│   │   │   ├── project_repository.py
│   │   │   ├── report_export_repository.py
│   │   │   ├── supervisor_update_repository.py
│   │   │   └── user_repository.py
│   │   │
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── audit.py
│   │   │   └── rate_limit.py
│   │   │
│   │   ├── observability/             # Structured logging + context propagation
│   │   │   ├── __init__.py
│   │   │   ├── context.py
│   │   │   └── logging.py
│   │   │
│   │   ├── tasks/                     # Celery tasks
│   │   │   ├── __init__.py
│   │   │   ├── approval.py
│   │   │   ├── async_utils.py
│   │   │   ├── base.py                # LoggedTask base class
│   │   │   ├── celery_app.py          # Celery instance config
│   │   │   ├── email.py
│   │   │   ├── image.py
│   │   │   ├── imports.py
│   │   │   ├── report.py
│   │   │   ├── backup.py
│   │   │   └── maintenance.py
│   │   │
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── exceptions.py
│   │       ├── links.py
│   │       ├── permissions.py
│   │       ├── request.py
│   │       └── security.py
│   │
│   ├── tests/
│   │   ├── test_auth.py
│   │   ├── test_daily_reports.py
│   │   ├── test_projects.py
│   │   ├── test_inventory.py
│   │   ├── test_approvals.py
│   │   ├── test_documents.py
│   │   └── ...                        # 25 test modules total
│   │
│   └── scripts/
│       ├── seed.py                    # Development seed data
│       ├── backup.py                  # Encrypted database backup
│       ├── restore_dry_run.py         # Backup restore validation
│       ├── health_monitor.py          # Health-endpoint alerting
│       ├── launch_evidence.py         # Launch evidence capture
│       ├── log_cli.py                 # Remote log search / tail CLI
│       ├── generate_assets.py
│       ├── dev/generate_missing_reports.py
│       ├── push_to_storage.py
│       └── validate_import_sources.py
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── index.html
│   ├── public/
│   │   ├── manifest.json
│   │   ├── sw.js                      # Service Worker (PWA)
│   │   └── brand/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx                    # Routes + RequirePermission gates
│   │   ├── i18n.ts
│   │   │
│   │   ├── api/                       # API client modules
│   │   │   ├── client.ts              # Axios instance + interceptors
│   │   │   ├── schema.d.ts            # OpenAPI-generated types
│   │   │   ├── auth.ts
│   │   │   ├── users.ts
│   │   │   ├── projects.ts
│   │   │   ├── reports.ts
│   │   │   ├── supervisorUpdates.ts
│   │   │   ├── approvals.ts
│   │   │   ├── documents.ts
│   │   │   ├── photos.ts
│   │   │   ├── inventory.ts
│   │   │   ├── finance.ts
│   │   │   ├── analytics.ts
│   │   │   ├── dashboard.ts
│   │   │   ├── notifications.ts
│   │   │   ├── imports.ts
│   │   │   ├── audit.ts
│   │   │   ├── fileUrls.ts
│   │   │   └── offlineQueue.ts
│   │   │
│   │   ├── context/                   # React Context providers
│   │   │   ├── AuthContext.tsx
│   │   │   ├── auth-context.ts
│   │   │   └── useAuth.ts
│   │   │
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── AppLayout.tsx
│   │   │   │   └── RequirePermission.tsx
│   │   │   └── shared/
│   │   │       ├── EmptyState.tsx
│   │   │       ├── ErrorBoundary.tsx
│   │   │       ├── FileDropZone.tsx
│   │   │       ├── OfflineIndicator.tsx
│   │   │       └── StatusBadge.tsx
│   │   │
│   │   ├── pages/
│   │   │   ├── auth/                  # LoginPage, PasswordResetPage, ChangePasswordPage
│   │   │   ├── dashboard/             # DashboardPage
│   │   │   ├── reports/               # DailyReportPage, SupervisorUpdatePage
│   │   │   ├── approvals/             # ApprovalInboxPage
│   │   │   ├── projects/              # ProjectListPage
│   │   │   ├── inventory/             # InventoryPage
│   │   │   ├── suppliers/             # SuppliersPage
│   │   │   ├── documents/             # DocumentsPage
│   │   │   ├── photos/                # PhotosPage
│   │   │   ├── finance/               # FinancePage
│   │   │   ├── analytics/             # AnalyticsPage
│   │   │   ├── delivery/              # DeliveryPlanPage
│   │   │   ├── notifications/         # NotificationsPage
│   │   │   ├── profile/               # ProfilePage
│   │   │   ├── security/              # SecurityPage
│   │   │   ├── roles/                 # RolesPermissionsPage
│   │   │   ├── manual/                # ManualPage + role manuals
│   │   │   └── admin/                 # UserManagementPage, AuditLogPage, ImportPage
│   │   │
│   │   └── styles/
│   │       └── index.css
│   │
│   └── scripts/
│       └── check-openapi-types.mjs    # OpenAPI type drift check
│
└── storage/                           # MinIO data volume (gitignored)
```

---

## 10. Architectural Decisions (ADRs)

### ADR-001: FastAPI as the Backend Framework

**Decision**: Use FastAPI (Python 3.12+) instead of Django, NestJS, or Go.

**Rationale**:
- The system is an API-first backend consumed by a decoupled React SPA — not a server-rendered admin panel
- FastAPI's automatic OpenAPI generation keeps the frontend/backend contract clear and testable
- Pydantic V2 provides strong request/response validation from Python type hints
- The workload is I/O-heavy (database queries, file uploads, external service calls) — FastAPI's async support is a good fit when paired with disciplined query shape, indexing, pagination, transaction boundaries, and latency monitoring
- Python excels at the reporting/export/image processing tasks this project requires (openpyxl, WeasyPrint, Pillow)
- Django would be better for admin-heavy CRUD, but this project has a custom React admin UI and complex workflows

### ADR-002: Disciplined Service Layer Pattern

**Decision**: Route handlers must be thin controllers (max ~15 lines). All business logic must live in a dedicated service layer. Services must never import HTTP concerns.

**Rationale**:
- Prevents business logic from scattering across route files as the application grows
- Services are testable in isolation without HTTP fixtures
- The same service can be called from routes, Celery tasks, and scripts
- Clear separation makes onboarding easier — a new developer knows exactly where to put business rules
- This is not optional. It is enforced in code review.

### ADR-003: Async SQLAlchemy 2.0

**Decision**: Use SQLAlchemy 2.0 with the async extension and asyncpg driver.

**Rationale**:
- FastAPI's async event loop is wasted if the ORM blocks on every query
- SQLAlchemy 2.0's new-style `select()` API is cleaner and more composable than 1.x
- asyncpg is the fastest PostgreSQL driver for Python
- Alembic integrates natively for migrations
- Repository pattern wraps async sessions, keeping async concerns out of service logic
- Async database access improves concurrency for I/O-bound work, but it does not replace query tuning, proper indexes, bounded pagination, or short transaction scopes

### ADR-004: UUID Primary Keys

**Decision**: Every table uses `UUID PRIMARY KEY DEFAULT uuid_generate_v4()`.

**Rationale**:
- IDs are not sequentially guessable (security through obscurity for enumeration attacks)
- Safe for distributed systems (no ID collisions if we later add read replicas or sharding)
- Frontend can generate optimistic IDs for offline-created records
- Costs more storage than auto-increment integers, but the trade-off is acceptable for an internal system of this scale

### ADR-005: Soft Deletes

**Decision**: All user-facing tables use `deleted_at TIMESTAMPTZ`. DELETE endpoints set this column; they do not physically remove rows.

**Rationale**:
- Construction data has audit and compliance requirements — deleted records must be recoverable
- Historical reports, approvals, and movements must retain referential integrity
- Soft-deleted records are automatically excluded from all queries via repository pattern
- Records are permanently purged after 30 days by a Celery task (configurable retention policy)
- Matches the stakeholder requirement: "Users should be deactivated, not deleted; historical continuity must remain"

### ADR-006: MinIO as S3-Compatible Object Storage

**Decision**: Self-host MinIO for S3-compatible object storage rather than binding the application directly to a cloud-provider-specific storage API.

**Rationale**:
- The system may be deployed in environments without reliable cloud access (construction sites)
- MinIO is S3 API-compatible, so moving to AWS S3 or another S3-compatible managed storage service can stay mostly configuration-driven if storage access remains isolated behind service helpers
- Moving to Azure Blob Storage is possible, but it is not a drop-in swap unless the storage abstraction avoids S3-specific assumptions in application code
- Photos and documents may contain commercially sensitive construction data
- Self-hosting avoids per-GB egress costs for frequent photo/document downloads
- Open source with no licensing costs

### ADR-007: PWA Over Native Mobile App

**Decision**: Build the mobile experience as a Progressive Web App, not a native iOS/Android app.

**Rationale**:
- The target audience is internal employees, not public app store users
- A PWA provides offline capabilities (Service Worker + IndexedDB) sufficient for field data entry
- Single codebase (React) for both desktop admin and mobile field use
- No app store approval delays for updates
- Camera access for site photos works via `<input capture="environment">`
- Native apps would require Swift (iOS) + Kotlin (Android) — doubling development effort for marginal benefit

### ADR-008: React Context + TanStack Query (No Redux)

**Decision**: Use React Context for auth state and TanStack Query for server state. Do not introduce Redux.

**Rationale**:
- The application's state is primarily server-derived (reports, projects, inventory) — TanStack Query handles caching, invalidation, and refetching better than any hand-written Redux store
- Auth state is the only truly global client state — React Context is sufficient
- UI state (sidebar, modals, filters) is local to components — `useState`/`useReducer` is sufficient
- Eliminates boilerplate: no action types, action creators, reducers, selectors, or thunks
- The team is small — the simpler mental model of Context + Query is easier to maintain

### ADR-009: PostgreSQL Over MongoDB

**Decision**: Use PostgreSQL as the primary database, not MongoDB or another NoSQL store.

**Rationale**:
- The domain is inherently relational: projects have reports, reports have manpower entries, inventory has movements, users have roles
- Approval workflows, audit trails, and inventory movements require ACID transactions
- Foreign key constraints enforce referential integrity (a report cannot reference a deleted project)
- JSONB provides NoSQL-like flexibility for semi-structured data (weather data, custom form fields) within a relational model
- PostgreSQL's mature ecosystem: GIN indexes, full-text search, window functions for analytics, triggers for audit
- The reporting and dashboard features benefit from SQL's aggregation capabilities

---

## 11. Appendix: Technology Version Matrix

| Technology | Version | Notes |
|-----------|---------|-------|
| Python | 3.14 | Backend Docker base image (`backend/Dockerfile`) |
| FastAPI | 0.136.1 | `backend/requirements.txt` |
| SQLAlchemy | 2.0.41 | `backend/requirements.txt` |
| asyncpg | 0.30.0 | Async PostgreSQL driver (`backend/requirements.txt`) |
| Alembic | 1.16.1 | `backend/requirements.txt` |
| pydantic-settings | 2.9.1 | Settings management (`backend/requirements.txt`) |
| Celery | 5.5.2 | Background task queue (`backend/requirements.txt`) |
| structlog | 25.3.0 | Structured JSON logging (`backend/requirements.txt`) |
| python-jose | 3.5.0 | JWT signing/verification (`backend/requirements.txt`) |
| bcrypt | 4.0.1 | Password hashing (`backend/requirements.txt`) |
| PostgreSQL | 16 | Primary database |
| Redis | 5.2.1 (client) | Cache, broker, rate limiter (`backend/requirements.txt`) |
| MinIO | 7.2.15 (client) | Object storage (`backend/requirements.txt`) |
| Nginx | 1.25+ (Alpine) | Reverse proxy |
| React | 18.x | UI framework |
| TypeScript | 5.8.x | `frontend/package.json` |
| Vite | 6.3.x | `frontend/package.json` |
| Tailwind CSS | 3.4.x | `frontend/package.json` |
| React Router | 6.30.x | `frontend/package.json` |
| TanStack Query | 5.77.x | `frontend/package.json` |
| React Hook Form | 7.76.x | `frontend/package.json` |
| Zod | 4.4.x | `frontend/package.json` |
| Recharts | 3.8.x | `frontend/package.json` |
| Axios | 1.9.x | `frontend/package.json` |
| Docker | 24+ | Container runtime |
| Docker Compose | v2 | Container orchestration |

### 11.1 Graph Snapshot (graphify-out)

This section summarizes the current cross-repo structure from `graphify-out/GRAPH_REPORT.md` (commit `ed3f1cca`):

- Corpus: 221 files · ~149,503 words
- Graph: 3,248 nodes · 14,822 edges · 170 communities
- Confidence mix: 52% EXTRACTED · 48% INFERRED

Top “god nodes” (highest-degree entities):

- `User` (791 edges)
- `AppException` (523 edges)
- `AuditService` (342 edges)
- `NotFoundException` (286 edges)
- `DbSession` (233 edges)
- `ProjectMember` (187 edges)
- `Project` (180 edges)
- `UserRepository` (172 edges)
- `DailyReport` (171 edges)

When interpreting graph-derived sections like “Surprising Connections”, treat INFERRED edges as hypotheses: some may be identifier collisions (e.g., built-in Python types) rather than true architectural coupling.
