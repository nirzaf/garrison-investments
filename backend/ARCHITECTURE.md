# Backend Architecture — Garrison Investments Construction Portal

> Auto-generated from the graphify knowledge graph (1,194 nodes · 6,505 edges · 40 communities)

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Runtime | Python 3.14 | Async-first backend |
| Framework | FastAPI | Async HTTP API with dependency injection |
| ORM | SQLAlchemy 2.1 (async) + asyncpg | Database access via `AsyncSession` |
| Database | PostgreSQL 18.6 | Primary data store (asyncpg driver) |
| Cache / Broker | Redis | Rate limiting, Celery task queue |
| Object Storage | MinIO (S3-compatible) | Provider-isolated file storage for photos, documents, and exports |
| Task Queue | Celery | Background jobs for email, image, report, backup, and maintenance workloads |
| Auth | JWT (RS256) + OTP | Access/refresh tokens, TOTP challenge-response |
| Logging | structlog | Structured JSON logging |
| Log aggregation | Grafana + Loki + Alloy | Search, dashboards, retention, and SMTP alerting |
| Migrations | Alembic | Schema versioning (19 migrations) |

## Directory Structure

```
backend/
├── app/
│   ├── api/v1/           # Route handlers (thin — delegate to services)
│   │   ├── router.py     # Central router aggregation
│   │   ├── auth.py       # Login, OTP, password reset
│   │   ├── users.py      # User CRUD
│   │   ├── projects.py   # Project + members + milestones + tasks
│   │   ├── reports.py    # Daily reports CRUD + PDF export
│   │   ├── approvals.py  # Approval workflows
│   │   ├── documents.py  # Document versioning
│   │   ├── photos.py     # Photo upload + thumbnails
│   │   ├── inventory.py  # Inventory items + stock + movements
│   │   ├── finance.py    # Invoices
│   │   ├── suppliers.py  # Supplier management
│   │   ├── imports.py    # Bulk data import (CSV/Excel)
│   │   ├── analytics.py  # Summaries + Excel export
│   │   ├── dashboard.py  # Role-based dashboard aggregations
│   │   ├── notifications.py
│   │   ├── supervisor_updates.py
│   │   ├── audit.py      # Activity log queries
│   │   └── logs.py       # Centralized log-event queries + streaming
│   ├── models/           # SQLAlchemy ORM models (21 files)
│   │   ├── base.py       # Base, TimestampMixin, SoftDeleteMixin, UUIDPrimaryKeyMixin
│   │   ├── user.py       # User — central entity (503 edges in graph)
│   │   ├── project.py    # Project + ProjectMember
│   │   ├── daily_report.py
│   │   ├── approval.py
│   │   ├── inventory.py
│   │   ├── finance.py
│   │   ├── document.py
│   │   ├── photo.py
│   │   ├── supplier.py
│   │   ├── notification.py
│   │   ├── auth.py       # AuthOtpChallenge, AuthRefreshToken
│   │   ├── activity_log.py
│   │   └── ...
│   ├── repositories/     # Data access layer (10 files)
│   │   ├── user_repository.py
│   │   ├── auth_repository.py
│   │   ├── project_repository.py
│   │   ├── daily_report_repository.py
│   │   ├── approval_repository.py
│   │   ├── document_repository.py
│   │   ├── photo_repository.py
│   │   ├── notification_repository.py
│   │   ├── report_export_repository.py
│   │   └── supervisor_update_repository.py
│   ├── services/         # Business logic layer (20 files)
│   │   ├── auth_service.py
│   │   ├── user_service.py
│   │   ├── project_service.py
│   │   ├── report_service.py
│   │   ├── report_export_service.py
│   │   ├── reporting_service.py
│   │   ├── approval_service.py
│   │   ├── inventory_service.py
│   │   ├── finance_service.py
│   │   ├── document_service.py
│   │   ├── photo_service.py
│   │   ├── supplier_service.py
│   │   ├── analytics_service.py
│   │   ├── dashboard_service.py
│   │   ├── notification_service.py
│   │   ├── import_service.py
│   │   ├── storage_service.py     # MinIO abstraction
│   │   ├── email_service.py       # SMTP email sending
│   │   ├── audit_service.py       # Activity log writer
│   │   └── exception_reporter.py  # Unhandled exception → email alerts
│   ├── schemas/          # Pydantic request/response models (17 files)
│   ├── tasks/            # Celery background tasks (10 files)
│   │   ├── celery_app.py
│   │   ├── base.py       # Shared task base class
│   │   ├── report.py     # PDF generation
│   │   ├── email.py      # Async email dispatch
│   │   ├── image.py      # Thumbnail generation
│   │   ├── approval.py   # Reminder processing
│   │   ├── backup.py     # Database backups
│   │   ├── imports.py    # Bulk import execution
│   │   ├── maintenance.py
│   │   └── async_utils.py
│   ├── middleware/        # FastAPI middleware
│   │   ├── audit.py      # Per-request audit logging
│   │   └── rate_limit.py # Redis-backed auth rate limiter
│   ├── observability/    # Structured logging + request context
│   │   ├── context.py    # Request/task context propagation
│   │   └── logging.py    # structlog configuration + recursive/pattern redaction
│   ├── utils/            # Shared utilities
│   │   ├── exceptions.py # AppException hierarchy
│   │   ├── permissions.py # RBAC permission checks
│   │   ├── security.py   # Password hashing, JWT helpers
│   │   ├── links.py      # Frontend URL builders
│   │   └── request.py    # Client IP extraction
│   ├── config.py         # Pydantic Settings (env-driven)
│   ├── database.py       # AsyncSession factory + health check
│   └── main.py           # FastAPI app factory + middleware wiring
├── alembic/              # Database migrations
│   ├── env.py
│   └── versions/         # 19 migration files
├── scripts/              # Operational scripts
│   ├── backup.py
│   ├── generate_assets.py
│   ├── dev/generate_missing_reports.py
│   ├── health_monitor.py
│   ├── launch_evidence.py
│   ├── log_cli.py        # Remote log search / tail CLI
│   ├── push_to_storage.py
│   ├── restore_dry_run.py
│   ├── seed.py
│   └── validate_import_sources.py
├── tests/                # Test suite
└── Dockerfile
```

## Architectural Layers

```
┌─────────────────────────────────────────────────────┐
│                    API Routes (v1)                   │  Thin — validation + HTTP concerns only
├─────────────────────────────────────────────────────┤
│                    Services                          │  Business logic + orchestration
├─────────────────────────────────────────────────────┤
│                   Repositories                       │  Data access (SQLAlchemy queries)
├─────────────────────────────────────────────────────┤
│                ORM Models (SQLAlchemy)               │  Schema definitions + relationships
└─────────────────────────────────────────────────────┘
```

### Dependency Flow

Routes → Services → Repositories → Models

Routes **never** access repositories directly. Services instantiate repositories internally. The `DbSession` dependency (`Annotated[AsyncSession, Depends(get_db)]`) is injected at the route level and threaded through.

### Dependency Injection (FastAPI)

Key injected dependencies defined in `app/api/dependencies.py`:

| Dependency | Type | Purpose |
|-----------|------|---------|
| `DbSession` | `AsyncSession` | Database session per request |
| `CurrentUser` | `User` | Authenticated user (JWT validated) |
| `RequestMetadata` | `RequestMeta` | Client IP + User-Agent for audit |
| `require_permission(perm)` | `Callable` | RBAC guard — raises `PermissionDeniedException` |

## Domain Modules

### Auth (`auth_service.py`, `auth_repository.py`)
- JWT access tokens (RS256, 15 min expiry) + refresh tokens (24 hr)
- OTP challenge-response flow for login
- Password hashing (bcrypt)
- Account lockout after 3 failed attempts
- Dev/staging OTP exposure for testing

### Daily Reports (`report_service.py`, `daily_report_repository.py`)
- One report per user per day per project
- PDF export via Celery task (`tasks/report.py`)
- Email notification on submission
- Late report detection (`tasks/email.py`)

### Projects (`project_service.py`, `project_repository.py`)
- Projects with members, milestones, tasks, BOQ items
- Role-based member assignment (engineer, supervisor, etc.)

### Approvals (`approval_service.py`, `approval_repository.py`)
- Generic approval workflow with delegation and escalation
- Reminder processing via Celery (`tasks/approval.py`)
- Concurrency-safe inventory approvals (migration `202605170001`)

### Inventory (`inventory_service.py`)
- Items, locations, stock levels, movements, material requests
- Low-stock alerts triggered via approval task
- Location-based stock tracking

### Documents (`document_service.py`, `document_repository.py`)
- Versioned document storage
- MinIO-backed file uploads with presigned URLs

### Photos (`photo_service.py`, `photo_repository.py`)
- Photo upload with thumbnail generation (Celery `tasks/image.py`)
- Compressed storage

### Finance (`finance_service.py`)
- Invoice management linked to projects and suppliers

### Suppliers (`supplier_service.py`)
- Supplier CRUD linked to projects

### Analytics (`analytics_service.py`)
- Project analytics summaries
- Excel export generation

### Notifications (`notification_service.py`, `notification_repository.py`)
- In-app notification system
- Email dispatch via Celery (`tasks/email.py`)

### Data Import (`import_service.py`)
- CSV/Excel bulk import with preview → confirm flow
- Async processing via Celery (`tasks/imports.py`)

## Cross-Cutting Concerns

### Error Handling
Custom exception hierarchy in `app/utils/exceptions.py`:

```
AppException (400)          — Base application error
├── NotFoundException (404)  — Entity not found
├── PermissionDeniedException (403) — RBAC violation
└── BusinessRuleException (409) — Domain rule violation
```

Unhandled exceptions are caught by `main.py` → reported via email (`exception_reporter.py`) → logged as `INTERNAL_SERVER_ERROR`.

### Audit Logging
Every authenticated request is logged via `middleware/audit.py` → `AuditService`. The centralized event-log model also stores `event_type`, `severity`, `request_id`, `session_id`, `endpoint`, `status_code`, `source_service`, `storage_tier`, and structured `context_payload` data.

Remote operator access is exposed through:

- `GET /api/v1/log-events`
- `GET /api/v1/log-events/stream`
- `scripts/log_cli.py`

See [LOGGING_AND_REMOTE_CLI.md](file:///Users/qts/Repos/garrison-investments/docs/LOGGING_AND_REMOTE_CLI.md) for usage, search filters, and streaming examples.

### Permissions (RBAC)
8 roles: admin, general_manager, operation_manager, project_manager, civil_engineer, civil_supervisor, store_keeper, accounts.

Permission checks via `utils/permissions.py:ensure_permission(user, permission)`.

### Rate Limiting
Redis-backed rate limiter (`middleware/rate_limit.py`) applied to auth endpoints. Configurable window + max requests via `Settings`.

### Storage
MinIO S3-compatible object storage for files. Presigned URLs provide secure access,
and the public endpoint is configurable for production. Moving to another
S3-compatible managed store should remain mostly configuration-driven while the
storage service keeps provider details isolated. Azure Blob Storage would require
adapter work unless S3-specific assumptions stay out of application code.

## Infrastructure

### Database
- PostgreSQL 18.6 with asyncpg driver
- Connection pooling via SQLAlchemy `create_async_engine`
- Health check: `SELECT 1` probe at `/health`
- Readiness probe: `/health/readiness`

### Redis
- Celery broker + result backend
- Rate limiting state storage

### Celery Tasks
| Task Module | Purpose |
|------------|---------|
| `tasks/report.py` | PDF generation for daily reports |
| `tasks/email.py` | Async email dispatch |
| `tasks/image.py` | Photo thumbnail generation |
| `tasks/approval.py` | Approval reminder processing |
| `tasks/backup.py` | Database backup to MinIO |
| `tasks/imports.py` | Bulk data import execution |
| `tasks/maintenance.py` | Notification retention cleanup |

### Migrations
19 Alembic migrations covering the full schema evolution:
- `202605160001` — Users
- `202605160002` — Auth sessions
- `202605160003` — User management
- `202605160004` — Projects + BOQ
- `202605160005` — Supervisor updates
- `202605160006` — Daily reports
- `202605160007` — Daily report approvals
- `202605160008` — Report exports
- `202605160009` — Photos
- `202605160010` — Documents
- `202605160011` — Notifications
- `202605160012` — Approvals
- `202605160013` — Inventory
- `202605160014` — Suppliers
- `202605160015` — Finance
- `202605160016` — Import batches
- `202605170001` — Approval-inventory concurrency hardening
- `202605170002` — Project tasks
- `202605280001` — Centralized event logs (event_type, severity, storage tiers)

## Graph Analysis Summary

> Generated by graphify — 1,194 nodes, 6,505 edges, 40 communities

### God Nodes (Core Abstractions)
| Rank | Entity | Edges | Significance |
|------|--------|-------|--------------|
| 1 | `User` | 347 | Central domain entity — referenced by every feature module |
| 2 | `AppException` | 291 | Error handling wired into all services and routes |
| 3 | `DbSession` | 204 | Database session injected into every repository |
| 4 | `AuditService` | 159 | Activity logging across all write operations |
| 5 | `NotFoundException` | 140 | Most common error pattern |
| 6 | `InventoryService` | 99 | Complex domain with stock, movements, requests |
| 7 | `ApprovalService` | 91 | Workflow engine connecting reports, inventory, finance |
| 8 | `ReportService` | 84 | Daily report CRUD + export orchestration |
| 9 | `NotificationService` | 78 | Cross-cutting notification dispatch |
| 10 | `DailyReport` | 75 | Primary daily workflow entity |

### Community Structure (Top 15)
| Community | Nodes | Domain |
|-----------|-------|--------|
| C0 | 70 | Daily Reports API + Schemas |
| C1 | 66 | Dashboard + Project Management |
| C2 | 45 | Supervisor Updates + Activity Log |
| C3 | 55 | Inventory (items, stock, movements, locations) |
| C4 | 47 | Approvals + Auth Dependencies |
| C5 | 44 | Finance (invoices) |
| C6 | 37 | Photo Management |
| C7 | 39 | Document Management |
| C8 | 46 | Suppliers |
| C9 | 34 | Data Import Pipeline |
| C10 | 30 | Notifications |
| C11 | 31 | Analytics |
| C12 | 27 | User Management |
| C13 | 33 | Auth (login, OTP, tokens) |
| C14 | 20 | Background Tasks (Celery) |

### Cross-Community Bridges
- **`User`** bridges 18 communities — every feature module depends on the user entity
- **`AppException`** bridges 18 communities — error handling is pervasive
- **`DbSession`** bridges 14 communities — database access is universal
