# ARCHITECTURE.md — Construction Internal Portal

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
              |  |  PostgreSQL 16   |  |  Redis 7          |              |
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

2. Nginx terminates TLS, applies gzip, enforces security headers,
   routes /api/* to FastAPI, serves /static/* and /media/* directly

3. FastAPI middleware executes in order:
   a. CORSMiddleware          — validates origin against allowlist
   b. AuthMiddleware          — decodes JWT, attaches user to request.state
   c. RBACMiddleware          — checks role permission for endpoint
   d. RateLimitMiddleware     — checks Redis counters (via slowapi)
   e. AuditMiddleware         — logs request metadata

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
| Build Tool | Vite 8 | Fast HMR, tree shaking, code splitting |
| Styling | Tailwind CSS 3 | Utility-first responsive design |
| Routing | React Router 6 | Client-side routing with lazy loading |
| Server State | TanStack Query 5 | API caching, refetching, optimistic mutations |
| Forms | React Hook Form + Zod | Performant forms with schema validation |
| Tables | TanStack Table 8 | Headless data grid |
| Charts | Recharts 2 | Declarative React charting |
| HTTP Client | Axios | Interceptors, JWT refresh logic |
| Backend Framework | FastAPI (Python 3.12+) | Async web framework, auto OpenAPI |
| ORM | SQLAlchemy 2.0 (async) | Async ORM with 2.0-style queries |
| Migrations | Alembic | Schema versioning, auto-generated from models |
| Validation | Pydantic V2 | Request/response schemas, computed fields |
| Auth | python-jose + bcrypt | JWT signing, password hashing |
| Task Queue | Celery 5 + Redis broker | Async background tasks |
| Database | PostgreSQL 16 | Primary relational data store |
| Cache/Broker | Redis 7 | Caching, Celery broker, rate-limit counters |
| Object Storage | MinIO | S3-compatible self-hosted file storage |
| Reverse Proxy | Nginx | TLS termination, static files, security headers |
| Container Runtime | Docker + Docker Compose | Consistent dev/prod environments |
| CI/CD | GitHub Actions | Lint, test, build, deploy pipeline |
| Monitoring | Prometheus + Grafana | Metrics and dashboards (optional, Phase 2+) |
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
  - Services returning SQLAlchemy models to routes (return Pydantic schemas instead)
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
|  - Return SQLAlchemy ORM objects (return domain/Pydantic objects) |
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
|  - Cache integration (Redis get/set through repository)           |
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
# api/v1/reports.py

from fastapi import APIRouter, Depends, status
from app.api.dependencies import get_db, get_current_user
from app.schemas.daily_report import ReportCreate, ReportResponse, ReportListParams
from app.services.report_service import ReportService
from app.models.user import User

router = APIRouter(prefix="/reports", tags=["Daily Reports"])

@router.post("/", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def create_report(
    data: ReportCreate,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new daily report (draft). All business logic is in ReportService."""
    service = ReportService(db)
    report = await service.create_report(data, current_user)
    return report

@router.get("/", response_model=PaginatedResponse[ReportResponse])
async def list_reports(
    params: ReportListParams = Depends(),
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

### 2.5 Repository Layer (Example)

```python
# repositories/report_repository.py

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

### 2.6 Model Mixins

```python
# models/base.py

class TimestampMixin:
    created_at = Column(TIMESTAMPTZ, default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMPTZ, default=func.now(), onupdate=func.now(), nullable=False)

class SoftDeleteMixin:
    deleted_at = Column(TIMESTAMPTZ, nullable=True)
```

### 2.7 Middleware Stack

Middleware executes in this order for every API request:

| Order | Middleware | Responsibility | Library / Module |
|-------|-----------|---------------|-----------------|
| 1 | CORS | Validate origin against allowlist | `fastapi.middleware.cors` |
| 2 | Auth | Decode JWT, fetch user, attach to `request.state.user` | `app/middleware/auth.py` |
| 3 | RBAC | Check user role against endpoint permission | `app/middleware/rbac.py` |
| 4 | Rate Limit | Check Redis counters per IP/user/endpoint | `slowapi` (Redis-backed) |
| 5 | Audit | Log request metadata to `activity_log` | `app/middleware/audit.py` |

Auth, RBAC, and Audit are applied as router-level dependencies, not global Starlette middleware, so they only execute on API routes (not static file requests).

### 2.8 Task Layer (Celery Workers)

All operations that should not block the HTTP request/response cycle are handled by Celery:

| Task | Trigger | Queue | Retry Strategy |
|------|---------|-------|---------------|
| `send_email_notification` | Approval change, report submit, low stock | `email` | 3 retries, exponential backoff |
| `generate_thumbnail` | Photo upload | `image` | 2 retries |
| `compress_photo` | Photo upload | `image` | 2 retries |
| `generate_report_pdf` | Export endpoint | `report` | 3 retries |
| `generate_excel_export` | Export endpoint | `report` | 3 retries |
| `run_database_backup` | Celery Beat (daily) | `backup` | 2 retries |
| `cleanup_old_notifications` | Celery Beat (daily) | `maintenance` | 1 retry |
| `check_late_reports` | Celery Beat (hourly) | `maintenance` | No retry |
| `check_low_stock` | Celery Beat (hourly) | `maintenance` | No retry |

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

The full component hierarchy is detailed in [docs/05_UI_Component_Tree.md](docs/05_UI_Component_Tree.md).

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
api/auth.ts        — login, refresh, logout, me
api/reports.ts     — create, list, get, update, submit, approve, reject
api/projects.ts    — list, get, create, update, timeline, members
api/inventory.ts   — items, locations, stock, assets, movements, requests
api/documents.ts   — list, upload, download, versions, search
api/photos.ts      — upload, list, download, thumbnail
api/approvals.ts   — inbox, outbox, approve, reject
api/notifications.ts — list, unread-count, mark-read
api/dashboard.ts   — summary, progress, material-usage, approval-stats
api/export.ts      — excel, pdf exports
api/admin.ts       — users, audit-log
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

### 3.6 Component Design Principles

1. **Headless where possible**: `DataTable` uses TanStack Table (headless); `Select` and `Modal` use Radix primitives for accessibility
2. **One component, one file**: Each component is a single `.tsx` file with co-located types
3. **Composition over configuration**: Components use `children` and render props, not giant config objects
4. **Loading, empty, and error states are mandatory**: Every data-dependent component handles all three
5. **Mobile-first responsive**: Tailwind `sm:`, `md:`, `lg:` breakpoints; bottom nav on mobile; collapsible sidebar on desktop

---

## 4. Data Architecture

### 4.1 Schema Overview

23 tables organized into 7 domain groups:

| Group | Tables |
|-------|--------|
| Identity & Access | `users` |
| Projects & Planning | `projects`, `project_members`, `project_milestones`, `boq_items` |
| Daily Reporting | `daily_reports`, `report_manpower`, `report_equipment`, `report_material_consumption` |
| Inventory & Stores | `suppliers`, `storage_locations`, `inventory_items`, `inventory_location_stock`, `inventory_assets`, `inventory_movements` |
| Documents & Media | `documents`, `document_versions`, `photos` |
| Workflow & Comms | `approvals`, `notifications` |
| Accounts & Finance | `invoices`, `payments` |
| Governance | `activity_log` |

Full schema details in [docs/02_Database_Schema.md](docs/02_Database_Schema.md) and per-table references in [schema/](schema/).

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
     - access_token (JWT, RS256, 15 min expiry)
     - refresh_token (JWT, 1 day expiry, stored hashed in DB)
  4. Server returns { access_token, refresh_token, token_type, user }

TOKEN REFRESH (silent):
  1. Client detects 401 or near-expiry access token
  2. Client POST /api/v1/auth/refresh { refresh_token }
  3. Server validates refresh_token, rotates it (old invalidated)
  4. Server returns { access_token, refresh_token }

EVERY AUTHENTICATED REQUEST:
  1. Client sends Authorization: Bearer <access_token>
  2. Auth middleware decodes JWT, extracts user_id
  3. Fetches user from DB (cached in Redis for 5 minutes)
  4. Attaches user to request.state.user
  5. RBAC middleware checks role permission for endpoint

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
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
```

### 5.4 File Upload Security

1. **Type whitelist**: JPG, PNG, HEIC, PDF, XLSX, DOCX, DWG
2. **Blocked**: `.exe`, `.sh`, `.bat`, `.cmd`, `.js`, `.php`, `.html`, unknown binaries
3. **Size limits**: 10 MB per photo, 60 MB per document
4. **Validation**: Server validates MIME type by magic bytes, not just extension
5. **Storage**: Files stored in MinIO with randomized object keys; original filenames only in DB metadata
6. **Presigned URLs**: Direct upload to MinIO (no file data passes through FastAPI)
7. **Access control**: Download URLs are signed and temporary; access checked per-request
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
    volumes: [./nginx/nginx.conf, ./nginx/ssl]
    depends_on: [backend]

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
    image: postgres:16-alpine
    environment: [POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD]
    volumes: [pgdata:/var/lib/postgresql/data]
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
| Monitoring | None | Prometheus + optional Grafana |

### 7.3 CI/CD Pipeline

```
PUSH TO BRANCH
    |
    v
[LINT]
  - Backend: ruff + mypy
  - Frontend: ESLint + Prettier
    |
    v
[TEST]
  - Backend: pytest (PostgreSQL in Docker service container)
  - Frontend: Vitest + React Testing Library
    |
    v
[BUILD]
  - Frontend: vite build -> dist/
  - Backend: docker build
    |
    v
[DEPLOY TO STAGING]  (on push to develop)
  - docker-compose -f docker-compose.prod.yml up -d
  - alembic upgrade head
  - Smoke test (curl health check)
    |
    v
[DEPLOY TO PRODUCTION]  (on push to main, manual approval required)
  - Same as staging
  - Requires Operation Manager approval in GitHub
```

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

- **Backend**: `structlog` for structured JSON logging
  - Log levels: DEBUG (dev), INFO (key operations), WARNING (recoverable), ERROR (exceptions)
  - Log categories: `app.api`, `app.service`, `app.security`, `app.task`
  - Format: `{"timestamp": "...", "level": "INFO", "logger": "app.service.report", "event": "report_created", "user_id": "...", "report_id": "..."}`
- **Frontend**: Console logging in dev only; production errors captured via `POST /api/v1/logs/client-error`

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

Audit logs retained for 7 years. Admin-only access.

### 8.4 Notification System

1. **Trigger**: Service layer calls `notification_service.create(...)` or Celery task creates bulk notifications
2. **In-App**: Stored in `notifications` table; client polls `GET /notifications/unread-count` every 60 seconds
3. **Email**: Celery task `send_email_notification` via SMTP (or SendGrid/Mailgun in production)
4. **Retention**: 90 days for user-facing notifications, then purged by Celery Beat

### 8.5 Health Checks

- `GET /health` — `{"status": "ok", "database": "connected", "redis": "connected"}` for load balancer / Docker healthcheck
- `GET /health/readiness` — checks database connectivity before marking container ready
- Prometheus metrics at `/metrics` (optional, Phase 2+)

---

## 9. Directory & Project Structure

```
garrison-investments/
│
├── README.md
├── ARCHITECTURE.md
├── .env.example
├── .gitignore
├── docker-compose.yml                 # Development
├── docker-compose.prod.yml            # Production
│
├── docs/                              # Planning & design docs
│   ├── 00_README.md
│   ├── 01_Technical_Specification.md
│   ├── 02_Database_Schema.md
│   ├── 03_API_Specification.md
│   ├── 04_Work_Breakdown_Structure.md
│   └── 05_UI_Component_Tree.md
│
├── schema/                            # Per-table schema reference
│   ├── README.md
│   └── *.md                           # One file per table (23 files)
│
├── prototype/                         # Next.js interactive prototype (stakeholder demo)
│   └── ...
│
├── .github/
│   └── workflows/
│       ├── ci.yml                     # Lint + test on PR
│       └── deploy.yml                 # Deploy to staging/production
│
├── nginx/
│   ├── nginx.conf                     # Reverse proxy + TLS + security headers
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
│   │   │   ├── report_manpower.py
│   │   │   ├── report_equipment.py
│   │   │   ├── report_material_consumption.py
│   │   │   ├── supplier.py
│   │   │   ├── storage_location.py
│   │   │   ├── inventory_item.py
│   │   │   ├── inventory_location_stock.py
│   │   │   ├── inventory_asset.py
│   │   │   ├── inventory_movement.py
│   │   │   ├── document.py
│   │   │   ├── document_version.py
│   │   │   ├── photo.py
│   │   │   ├── approval.py
│   │   │   ├── notification.py
│   │   │   ├── invoice.py
│   │   │   ├── payment.py
│   │   │   └── activity_log.py
│   │   │
│   │   ├── schemas/                   # Pydantic V2 request/response schemas
│   │   │   ├── __init__.py
│   │   │   ├── common.py              # PaginatedResponse, ErrorResponse, filters
│   │   │   ├── user.py
│   │   │   ├── project.py
│   │   │   ├── daily_report.py
│   │   │   ├── inventory.py
│   │   │   ├── document.py
│   │   │   ├── photo.py
│   │   │   ├── approval.py
│   │   │   ├── notification.py
│   │   │   ├── dashboard.py
│   │   │   └── export.py
│   │   │
│   │   ├── api/                       # Route handlers (THIN — no business logic)
│   │   │   ├── __init__.py
│   │   │   ├── dependencies.py        # get_db, get_current_user, require_permission
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── router.py          # Aggregates all v1 routers
│   │   │       ├── auth.py
│   │   │       ├── users.py
│   │   │       ├── projects.py
│   │   │       ├── reports.py
│   │   │       ├── inventory.py
│   │   │       ├── suppliers.py
│   │   │       ├── documents.py
│   │   │       ├── photos.py
│   │   │       ├── approvals.py
│   │   │       ├── notifications.py
│   │   │       ├── dashboard.py
│   │   │       └── export.py
│   │   │
│   │   ├── services/                  # Business logic layer
│   │   │   ├── __init__.py
│   │   │   ├── auth_service.py
│   │   │   ├── user_service.py
│   │   │   ├── project_service.py
│   │   │   ├── report_service.py
│   │   │   ├── inventory_service.py
│   │   │   ├── supplier_service.py
│   │   │   ├── document_service.py
│   │   │   ├── photo_service.py
│   │   │   ├── approval_service.py
│   │   │   ├── notification_service.py
│   │   │   ├── dashboard_service.py
│   │   │   ├── export_service.py
│   │   │   └── storage_service.py
│   │   │
│   │   ├── repositories/              # Data access layer
│   │   │   ├── __init__.py
│   │   │   ├── user_repository.py
│   │   │   ├── project_repository.py
│   │   │   ├── report_repository.py
│   │   │   ├── inventory_repository.py
│   │   │   ├── document_repository.py
│   │   │   ├── photo_repository.py
│   │   │   ├── approval_repository.py
│   │   │   └── notification_repository.py
│   │   │
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── rbac.py
│   │   │   ├── audit.py
│   │   │   └── rate_limit.py
│   │   │
│   │   ├── tasks/                     # Celery tasks
│   │   │   ├── __init__.py
│   │   │   ├── celery_app.py          # Celery instance config
│   │   │   ├── email.py
│   │   │   ├── image.py
│   │   │   ├── report.py
│   │   │   ├── backup.py
│   │   │   └── maintenance.py
│   │   │
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── pagination.py
│   │       ├── file_utils.py
│   │       ├── security.py
│   │       └── exceptions.py
│   │
│   ├── tests/
│   │   ├── conftest.py                # Fixtures: test DB, async client, auth headers
│   │   ├── test_auth.py
│   │   ├── test_reports.py
│   │   ├── test_projects.py
│   │   ├── test_inventory.py
│   │   ├── test_approvals.py
│   │   ├── test_documents.py
│   │   └── factories/                 # Test data factories (factory_boy)
│   │
│   └── scripts/
│       ├── seed.py                    # Development seed data
│       └── backup.py                  # Manual backup script
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
│   │   └── icons/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── router.tsx
│   │   │
│   │   ├── api/                       # API client modules
│   │   │   ├── client.ts              # Axios instance + interceptors
│   │   │   ├── auth.ts
│   │   │   ├── reports.ts
│   │   │   ├── projects.ts
│   │   │   ├── inventory.ts
│   │   │   ├── documents.ts
│   │   │   ├── photos.ts
│   │   │   ├── approvals.ts
│   │   │   ├── notifications.ts
│   │   │   ├── dashboard.ts
│   │   │   ├── export.ts
│   │   │   └── admin.ts
│   │   │
│   │   ├── hooks/                     # Custom React hooks
│   │   │   ├── useAuth.ts
│   │   │   ├── useDebounce.ts
│   │   │   ├── useFileUpload.ts
│   │   │   ├── useOfflineSync.ts
│   │   │   └── usePagination.ts
│   │   │
│   │   ├── context/                   # React Context providers
│   │   │   ├── AuthContext.tsx
│   │   │   └── ThemeContext.tsx
│   │   │
│   │   ├── components/
│   │   │   ├── ui/                    # Primitive components
│   │   │   │   ├── Button.tsx
│   │   │   │   ├── Input.tsx
│   │   │   │   ├── Select.tsx
│   │   │   │   ├── Table.tsx
│   │   │   │   ├── Modal.tsx
│   │   │   │   ├── Card.tsx
│   │   │   │   ├── Badge.tsx
│   │   │   │   └── Tabs.tsx
│   │   │   ├── layout/
│   │   │   │   ├── AppLayout.tsx
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   ├── Header.tsx
│   │   │   │   └── MobileNav.tsx
│   │   │   └── shared/
│   │   │       ├── DataTable.tsx
│   │   │       ├── FileUpload.tsx
│   │   │       ├── PhotoGrid.tsx
│   │   │       ├── StatusBadge.tsx
│   │   │       ├── ProgressBar.tsx
│   │   │       ├── SignaturePad.tsx
│   │   │       └── OfflineIndicator.tsx
│   │   │
│   │   ├── pages/
│   │   │   ├── auth/
│   │   │   │   ├── LoginPage.tsx
│   │   │   │   └── ForgotPasswordPage.tsx
│   │   │   ├── dashboard/
│   │   │   │   └── DashboardPage.tsx
│   │   │   ├── reports/
│   │   │   │   ├── DailyReportList.tsx
│   │   │   │   ├── DailyReportForm.tsx
│   │   │   │   └── DailyReportDetail.tsx
│   │   │   ├── projects/
│   │   │   │   ├── ProjectList.tsx
│   │   │   │   └── ProjectTimeline.tsx
│   │   │   ├── inventory/
│   │   │   │   ├── InventoryList.tsx
│   │   │   │   ├── StockByLocation.tsx
│   │   │   │   └── MovementHistory.tsx
│   │   │   ├── documents/
│   │   │   │   └── DocumentLibrary.tsx
│   │   │   ├── photos/
│   │   │   │   └── PhotoGallery.tsx
│   │   │   ├── approvals/
│   │   │   │   └── ApprovalInbox.tsx
│   │   │   └── admin/
│   │   │       ├── UserManagement.tsx
│   │   │       └── AuditLog.tsx
│   │   │
│   │   ├── lib/                       # Utility functions
│   │   │   ├── constants.ts
│   │   │   ├── formatters.ts
│   │   │   ├── validators.ts
│   │   │   └── offlineStorage.ts
│   │   │
│   │   └── types/                     # TypeScript type definitions
│   │       ├── user.ts
│   │       ├── project.ts
│   │       ├── report.ts
│   │       ├── inventory.ts
│   │       ├── document.ts
│   │       └── common.ts
│   │
│   └── tests/
│       └── components/
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
- The workload is I/O-heavy (database queries, file uploads, external service calls) — FastAPI's async support is a good fit
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

### ADR-006: MinIO Over Cloud S3

**Decision**: Self-host MinIO for object storage rather than using AWS S3 or another cloud provider.

**Rationale**:
- The system may be deployed in environments without reliable cloud access (construction sites)
- MinIO is S3 API-compatible — switching to AWS S3 later requires only a config change
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

**Decision**: Use PostgreSQL 16 as the primary database, not MongoDB or another NoSQL store.

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
| Python | 3.12+ | Required for recent async and typing features |
| FastAPI | 0.115+ | Latest stable with Pydantic V2 integration |
| SQLAlchemy | 2.0+ | Async ORM with 2.0-style queries |
| Alembic | 1.13+ | Schema migrations |
| Pydantic | 2.x | Request/response validation |
| Celery | 5.4+ | Background task queue |
| PostgreSQL | 16 | Primary database |
| Redis | 7.x | Cache, broker, rate limiter |
| MinIO | Latest stable | Object storage |
| Nginx | 1.25+ (Alpine) | Reverse proxy |
| React | 18.x | UI framework |
| TypeScript | 5.x | Strict mode |
| Vite | 8.x | Build tool |
| Tailwind CSS | 3.x | Utility CSS framework |
| React Router | 6.x | Client-side routing |
| TanStack Query | 5.x | Server state management |
| React Hook Form | 7.x | Form state management |
| Zod | 3.x | Schema validation |
| TanStack Table | 8.x | Data tables |
| Recharts | 2.x | Charts |
| Axios | 1.x | HTTP client |
| Node.js | 20 LTS+ | Frontend runtime |
| Docker | 24+ | Container runtime |
| Docker Compose | v2 | Container orchestration |
