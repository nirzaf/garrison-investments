# Technical Specification — Construction Internal Portal

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CLIENT LAYER                             │
│  ┌──────────────────────┐  ┌──────────────────────────────┐ │
│  │   Web Admin Panel    │  │   Mobile Responsive PWA      │ │
│  │   (React + Tailwind) │  │   (Service Worker + Cache)   │ │
│  └──────────┬───────────┘  └──────────────┬───────────────┘ │
└─────────────┼─────────────────────────────┼─────────────────┘
              │         HTTPS (TLS 1.3)      │
              │         ┌──────────┐         │
              └─────────┤  Nginx   ├─────────┘
                        │ (reverse │
                        │  proxy)  │
                        └────┬─────┘
                             │
┌────────────────────────────┼────────────────────────────────┐
│                    APPLICATION LAYER                         │
│  ┌──────────────────────────┐  ┌──────────────────────────┐ │
│  │  FastAPI App (Uvicorn)   │  │  Celery Workers           │ │
│  │  ┌────────────────────┐  │  │  ┌────────────────────┐  │ │
│  │  │ Auth Middleware    │  │  │  │ Email Service      │  │ │
│  │  │ RBAC Guard         │  │  │  │ Image Processing   │  │ │
│  │  │ Rate Limiter       │  │  │  │ Report Generation  │  │ │
│  │  │ Audit Logger       │  │  │  │ Backup Execution   │  │ │
│  │  └────────────────────┘  │  │  └────────────────────┘  │ │
│  └──────────┬───────────────┘  └──────────────────────────┘ │
│             │                           │                    │
└─────────────┼───────────────────────────┼────────────────────┘
              │                           │
┌─────────────┼───────────────────────────┼────────────────────┐
│                      DATA LAYER                              │
│  ┌──────────┴───────────┐  ┌──────────┴───────────┐         │
│  │  PostgreSQL 16       │  │  Redis               │         │
│  │  (Primary + Replica) │  │  (Cache + Queue)     │         │
│  └──────────────────────┘  └──────────────────────┘         │
│  ┌──────────────────────────────────────────────┐           │
│  │  MinIO Object Storage (S3-compatible)        │           │
│  └──────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

## 2. Project Structure

```
garrison-investments/
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── deploy.yml
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app entry point
│   │   ├── config.py                # Pydantic settings (env vars)
│   │   ├── database.py              # Async SQLAlchemy engine + session
│   │   │
│   │   ├── models/                  # SQLAlchemy ORM models
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── project.py
│   │   │   ├── daily_report.py
│   │   │   ├── material.py
│   │   │   ├── document.py
│   │   │   ├── photo.py
│   │   │   ├── approval.py
│   │   │   └── notification.py
│   │   │
│   │   ├── schemas/                 # Pydantic V2 request/response schemas
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── project.py
│   │   │   ├── daily_report.py
│   │   │   ├── material.py
│   │   │   ├── document.py
│   │   │   └── common.py            # Pagination, filters, error responses
│   │   │
│   │   ├── api/                     # Route handlers
│   │   │   ├── __init__.py
│   │   │   ├── v1/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── router.py        # API v1 aggregator
│   │   │   │   ├── auth.py
│   │   │   │   ├── users.py
│   │   │   │   ├── projects.py
│   │   │   │   ├── reports.py
│   │   │   │   ├── materials.py
│   │   │   │   ├── documents.py
│   │   │   │   ├── photos.py
│   │   │   │   ├── approvals.py
│   │   │   │   ├── notifications.py
│   │   │   │   └── dashboard.py
│   │   │   └── dependencies.py      # Dependency injection (get_db, get_current_user)
│   │   │
│   │   ├── services/                # Business logic layer
│   │   │   ├── __init__.py
│   │   │   ├── auth_service.py
│   │   │   ├── report_service.py
│   │   │   ├── approval_service.py
│   │   │   ├── notification_service.py
│   │   │   ├── storage_service.py
│   │   │   └── export_service.py
│   │   │
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── rbac.py
│   │   │   ├── audit.py
│   │   │   └── rate_limit.py
│   │   │
│   │   ├── tasks/                   # Celery tasks
│   │   │   ├── __init__.py
│   │   │   ├── email.py
│   │   │   ├── image.py
│   │   │   ├── report.py
│   │   │   └── backup.py
│   │   │
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── pagination.py
│   │       ├── file_utils.py
│   │       └── security.py
│   │
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_auth.py
│   │   ├── test_reports.py
│   │   ├── test_materials.py
│   │   ├── test_approvals.py
│   │   └── factories/               # Test data factories
│   │
│   └── scripts/
│       ├── seed.py                   # Development seed data
│       └── backup.py
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
│   │   ├── sw.js                    # Service Worker for offline/PWA
│   │   └── icons/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── router.tsx               # React Router v6 config
│   │   │
│   │   ├── api/                     # API client layer
│   │   │   ├── client.ts            # Axios instance with interceptors
│   │   │   ├── auth.ts
│   │   │   ├── reports.ts
│   │   │   ├── materials.ts
│   │   │   ├── documents.ts
│   │   │   ├── approvals.ts
│   │   │   └── dashboard.ts
│   │   │
│   │   ├── hooks/                   # Custom React hooks
│   │   │   ├── useAuth.ts
│   │   │   ├── useDebounce.ts
│   │   │   ├── useFileUpload.ts
│   │   │   ├── useOfflineSync.ts
│   │   │   └── usePagination.ts
│   │   │
│   │   ├── context/                 # React Context providers
│   │   │   ├── AuthContext.tsx
│   │   │   └── ThemeContext.tsx
│   │   │
│   │   ├── components/              # Reusable UI components
│   │   │   ├── ui/                  # Primitive components
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
│   │   ├── pages/                   # Route-level page components
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
│   │   │   ├── materials/
│   │   │   │   ├── MaterialList.tsx
│   │   │   │   ├── MaterialRequest.tsx
│   │   │   │   └── SupplierList.tsx
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
│   │   ├── lib/                     # Utility functions
│   │   │   ├── constants.ts
│   │   │   ├── formatters.ts
│   │   │   ├── validators.ts
│   │   │   └── offlineStorage.ts
│   │   │
│   │   └── types/                   # TypeScript type definitions
│   │       ├── user.ts
│   │       ├── project.ts
│   │       ├── report.ts
│   │       ├── material.ts
│   │       └── common.ts
│   │
│   └── tests/
│       └── components/
│
└── storage/                         # MinIO data volume (gitignored)
```

## 3. Technology Decisions

### 3.1 Backend — FastAPI

| Concern | Solution |
|---------|----------|
| **Async ORM** | SQLAlchemy 2.0 with asyncpg driver |
| **Migrations** | Alembic (auto-generated from models) |
| **Validation** | Pydantic V2 with computed fields and model validators |
| **Auth** | OAuth2 password flow + JWT access/refresh tokens (python-jose) |
| **File handling** | python-multipart + MinIO SDK (boto3-compatible) |
| **Background tasks** | Celery with Redis broker for heavy operations |
| **API docs** | Auto-generated OpenAPI (Swagger UI + ReDoc) |
| **Rate limiting** | slowapi (Redis-backed) |
| **CORS** | FastAPI CORSMiddleware with env-configured origins |
| **Logging** | structlog for structured JSON logging |
| **Testing** | pytest + httpx (async test client) + factory_boy |

### 3.2 Frontend — React

| Concern | Solution |
|---------|----------|
| **Build tool** | Vite 5 (fast HMR, tree shaking) |
| **Language** | TypeScript (strict mode) |
| **Routing** | React Router v6 (lazy-loaded routes) |
| **State management** | React Context + useReducer (no Redux — app is moderate complexity) |
| **Server state** | TanStack Query (React Query) for API caching/refetching |
| **Forms** | React Hook Form + Zod validation |
| **HTTP client** | Axios with JWT interceptor + refresh logic |
| **Table/Grid** | TanStack Table (headless) for complex data grids |
| **Charts** | Recharts (lightweight, React-native) |
| **PWA** | Service Worker for offline caching, Web Manifest |
| **File upload** | react-dropzone + presigned URL upload to MinIO |
| **Testing** | Vitest + React Testing Library |

### 3.3 Database — PostgreSQL

| Concern | Solution |
|---------|----------|
| **Primary key** | UUID v4 (crypto-safe, no sequential guessing) |
| **Soft delete** | `deleted_at TIMESTAMP` for all user-facing entities |
| **Audit trail** | Separate audit_log table + trigger-based capture |
| **Full-text search** | PostgreSQL `tsvector` GIN indexes on documents |
| **File metadata** | Stored in DB; actual files in MinIO |
| **JSONB** | Used for flexible fields (weather data, custom form sections) |
| **Indexes** | B-tree for lookups, GIN for JSONB/arrays, GiST for geo (future) |
| **Backup** | pg_dump scheduled via Celery + WAL archiving for PITR |

### 3.4 Infrastructure

| Concern | Solution |
|---------|----------|
| **Containerization** | Docker with multi-stage builds, docker-compose for orchestration |
| **Reverse proxy** | Nginx (TLS termination, static asset caching, gzip) |
| **Object storage** | MinIO (S3 API-compatible, self-hosted, open source) |
| **Cache/Queue** | Redis 7 (session cache, rate-limit counters, Celery broker) |
| **CI** | GitHub Actions (lint → test → build → deploy) |
| **Monitoring** | Prometheus metrics endpoint + optional Grafana dashboards |

## 4. Security Architecture

### 4.1 Authentication Flow

```
User → POST /auth/login (email + password)
     → Server validates against bcrypt hash
     → Returns { access_token (15min), refresh_token (7d) }
     → Frontend stores tokens in memory (access) + httpOnly cookie (refresh)

Every request:
     → Authorization: Bearer <access_token>
     → Auth middleware decodes JWT, fetches user from DB
     → RBAC middleware checks role permissions for endpoint
     → Audit middleware logs action
```

### 4.2 RBAC Matrix

| Role | Dashboard | Reports (CRUD) | Inventory & Stores | Approvals | Docs | Users | Audit |
|------|-----------|----------------|-----------|-----------|------|-------|-------|
| **Admin** | Full | Full | Full | Full | Full | Full | Full |
| **Operation Manager** | Full | Read All | Read All | Approve | Read All | Read | Read |
| **Project Manager** | Own Projects | Own Projects | Request | Own Projects | Own Projects | — | — |
| **Civil Engineer** | Own Projects | Own (Submit) | Request | Submit | Own Projects | — | — |
| **Civil Supervisor** | Own Projects | Own (Submit) | — | — | Read | — | — |
| **Store Keeper** | Inventory | — | Full | Submit | — | — | — |
| **Accounts** | Financial | Read | — | — | Invoices | — | — |

### 4.3 Additional Security Measures

- **Password policy**: Minimum 8 chars, must contain uppercase + number + symbol
- **Rate limiting**: 5 failed logins per IP per 15 minutes → temporary lockout
- **JWT** signed with RS256; access tokens short-lived (15 min); refresh rotation
- **CORS** whitelist of allowed origins configured via environment variable
- **Helmet.js** equivalent via secure HTTP headers (Nginx layer)
- **SQL injection**: Prevented by SQLAlchemy parameterized queries
- **XSS**: React auto-escaping + Content-Security-Policy header
- **CSRF**: SameSite=Strict cookies + token-based for state-changing operations
- **File upload**: Type whitelist, size limits (10 MB per file), virus scan via ClamAV (optional)
- **Audit log**: Every CREATE/UPDATE/DELETE recorded with user_id, timestamp, old_value, new_value

### 4.4 Inventory & Stores Control

Inventory extends the materials module into location-aware stores management for consumable materials and asset-tagged tools/items.

- **Storage locations**: central warehouse, industrial store, and project site stores are first-class records with active/inactive status.
- **Stock by location**: consumables keep on-hand, reserved, and available quantities per warehouse/site.
- **Tool/item current location**: serialized tools use asset tags and show current warehouse/site, condition, status, and last movement.
- **Approval-linked movement**: issue and transfer requests require approval before the Store Keeper records movement.
- **Alerts**: low-stock checks run per item and storage location, not only at company-wide total level.
- **Auditability**: receive, reserve, issue, transfer, return, consume, and adjustment movements preserve actor, reference, approval, from/to location, and notes.

## 5. Offline-First Mobile Strategy

Since this is a mobile-responsive PWA (not a native app):

1. **Service Worker** caches the app shell (HTML/CSS/JS) for instant loads
2. **IndexedDB** (via `idb` library) stores draft daily reports when offline
3. Drafts auto-sync when connectivity returns (Background Sync API where supported)
4. Camera access via `<input capture="environment">` for direct photo capture
5. Optimistic UI updates with rollback on server rejection

## 6. Deployment Strategy

### Development
```bash
docker-compose up -d        # Starts all services with hot-reload
```

### Production
```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│  Nginx       │───▶│  FastAPI x2  │───▶│  PostgreSQL  │
│  (TLS +      │    │  (uvicorn    │    │  + Replica   │
│   static)    │    │   workers)   │    └──────────────┘
│              │    └──────┬───────┘
│  /static/ ───┤           │
│  /media/  ───┤    ┌──────┴───────┐    ┌──────────────┐
│              │    │  Celery      │───▶│  Redis        │
└─────────────┘    │  Worker x2   │    └──────────────┘
                   └──────┬───────┘
                          │
                   ┌──────┴───────┐
                   │  MinIO       │
                   └──────────────┘
```

- Frontend served as static files by Nginx (built `dist/` mounted as volume)
- Backend behind Nginx reverse proxy with `/api` prefix
- PostgreSQL with streaming replication to standby
- Redis with AOF persistence
- Daily automated backups (pg_dump → MinIO → optional offsite sync)
