# Work Breakdown Structure — Construction Internal Portal

## Phase 1: Foundation & Daily Reporting (Core MVP)

**Goal**: Authentication, dashboard, and daily site reporting with photo uploads — the minimum viable system.

### 1.1 Project Setup & Infrastructure

| # | Task | Est. (days) | Depends On | Deliverable |
|---|------|-------------|------------|-------------|
| 1.1.1 | Initialize repo, Docker Compose dev environment | 0.5 | — | docker-compose.yml with all services |
| 1.1.2 | Scaffold FastAPI app with project structure | 0.5 | 1.1.1 | Running app with health check |
| 1.1.3 | Setup PostgreSQL, Alembic, initial migration | 0.5 | 1.1.1 | Users table created |
| 1.1.4 | Scaffold React app with Vite + TypeScript + Tailwind | 0.5 | 1.1.1 | Running frontend with router skeleton |
| 1.1.5 | Setup GitHub Actions CI pipeline (lint + test) | 0.5 | 1.1.2, 1.1.4 | Green CI on PR |
| 1.1.6 | Configure MinIO container + connect to backend | 0.5 | 1.1.1 | Photo upload test passing |

**Subtotal: 3 days**

### 1.2 Authentication & User Management

| # | Task | Est. (days) | Depends On | Deliverable |
|---|------|-------------|------------|-------------|
| 1.2.1 | Implement user model + migrations | 0.5 | 1.1.3 | Users table with roles |
| 1.2.2 | Build auth endpoints (login, refresh, logout, me) | 1.0 | 1.2.1 | JWT-based auth working |
| 1.2.3 | Implement RBAC middleware | 1.0 | 1.2.2 | Role-based endpoint protection |
| 1.2.4 | Build login page UI | 0.5 | 1.1.4 | Login form with validation |
| 1.2.5 | Implement AuthContext + protected routes | 0.5 | 1.2.4, 1.2.2 | Frontend auth flow complete |
| 1.2.6 | User CRUD admin page | 1.0 | 1.2.3 | Admin can manage users |
| 1.2.7 | Seed script with sample users per role | 0.5 | 1.2.1 | `python scripts/seed.py` working |

**Subtotal: 5 days**

### 1.3 Projects Module

| # | Task | Est. (days) | Depends On | Deliverable |
|---|------|-------------|------------|-------------|
| 1.3.1 | Project model + migration | 0.5 | 1.1.3 | Projects + project_members tables |
| 1.3.2 | Project CRUD API endpoints | 1.0 | 1.3.1, 1.2.3 | Full project API |
| 1.3.3 | Project list + detail pages | 1.0 | 1.3.2, 1.1.4 | Project screens in frontend |

**Subtotal: 2.5 days**

### 1.4 Daily Report System

| # | Task | Est. (days) | Depends On | Deliverable |
|---|------|-------------|------------|-------------|
| 1.4.1 | Daily Report model + all sub-tables | 1.0 | 1.3.1 | Reports, manpower, equipment, material_consumption tables |
| 1.4.2 | Report CRUD API with validation | 1.5 | 1.4.1, 1.2.3 | Report create/read/update endpoints |
| 1.4.3 | Report submission + approval workflow | 1.0 | 1.4.2 | Approve/reject flow working |
| 1.4.4 | Report list page with filters | 1.0 | 1.4.2 | Data table with date/project/status filters |
| 1.4.5 | Report form (create/edit) with dynamic sections | 1.5 | 1.4.4 | Full form — weather, work done, manpower grid, equipment, material used |
| 1.4.6 | Report detail view (read-only with status) | 0.5 | 1.4.5 | Single report view with all sub-sections |

**Subtotal: 6.5 days**

### 1.5 Photo Management (Phase 1)

| # | Task | Est. (days) | Depends On | Deliverable |
|---|------|-------------|------------|-------------|
| 1.5.1 | Photo upload API (MinIO integration) | 1.0 | 1.1.6 | Multipart upload to MinIO, thumbnail generation |
| 1.5.2 | Photo list + download/thumbnail endpoints | 0.5 | 1.5.1 | GET endpoints for photos |
| 1.5.3 | File upload component (drag-drop + camera) | 1.0 | 1.5.1 | Reusable upload component |
| 1.5.4 | Integrate photos into report form | 0.5 | 1.5.3, 1.4.5 | Photos attachable to reports |

**Subtotal: 3 days**

### 1.6 Dashboard (Phase 1)

| # | Task | Est. (days) | Depends On | Deliverable |
|---|------|-------------|------------|-------------|
| 1.6.1 | Dashboard summary API (role-scoped stats) | 1.0 | 1.4.2 | `/dashboard/summary` endpoint |
| 1.6.2 | Dashboard UI — stat cards, recent activity, charts | 1.5 | 1.6.1 | Dashboard page with KPIs |
| 1.6.3 | Project progress timeline component | 1.0 | 1.3.2 | Gantt-style project timeline |

**Subtotal: 3.5 days**

### 1.7 App Shell & Navigation

| # | Task | Est. (days) | Depends On | Deliverable |
|---|------|-------------|------------|-------------|
| 1.7.1 | AppLayout — sidebar, header, responsive shell | 1.0 | 1.1.4 | Layout with collapsible sidebar |
| 1.7.2 | Mobile responsive navigation (bottom nav) | 0.5 | 1.7.1 | Mobile-friendly nav bar |
| 1.7.3 | Role-based menu visibility | 0.5 | 1.2.5 | Menu items filtered by role |

**Subtotal: 2 days**

### 1.8 Testing & Polish (Phase 1)

| # | Task | Est. (days) | Depends On | Deliverable |
|---|------|-------------|------------|-------------|
| 1.8.1 | Backend unit + integration tests (auth, reports) | 1.5 | 1.4.3 | >80% coverage on critical paths |
| 1.8.2 | Frontend component tests (login, report form) | 1.0 | 1.4.6 | Key components tested |
| 1.8.3 | End-to-end smoke test (login → create report → submit) | 0.5 | 1.8.1, 1.8.2 | E2E test passing |
| 1.8.4 | Bug fixes and polish from testing | 1.0 | 1.8.3 | Release-ready Phase 1 |

**Subtotal: 4 days**

### Phase 1 Total: ~29.5 days

---

## Phase 2: Supply Chain & Workflows

**Goal**: Inventory & Stores, approval workflows, notifications, document control.

### 2.1 Inventory & Stores

| # | Task | Est. (days) | Depends On |
|---|------|-------------|------------|
| 2.1.1 | Storage locations model (warehouse/site) + seed data | 0.5 | Phase 1 |
| 2.1.2 | Inventory catalog for consumable materials and tools/items | 1.0 | 2.1.1 |
| 2.1.3 | Stock by location matrix with on-hand/reserved/available quantities | 1.0 | 2.1.2 |
| 2.1.4 | Asset-tagged tool/item tracking with current warehouse/site location | 1.0 | 2.1.2 |
| 2.1.5 | Approval-controlled issue/transfer request workflow | 1.0 | 2.1.3, 2.2.2 |
| 2.1.6 | Store Keeper receive/reserve/issue/transfer/return/consume forms | 1.0 | 2.1.5 |
| 2.1.7 | Movement history and current-location UI | 0.75 | 2.1.6 |
| 2.1.8 | Low-stock by location alerts + API | 0.5 | 2.1.3 |
| 2.1.9 | Supplier management page retained for purchasing context | 0.75 | 2.1.2 |

**Subtotal: 7.5 days**

### 2.2 Approval Workflow Engine

| # | Task | Est. (days) | Depends On |
|---|------|-------------|------------|
| 2.2.1 | Approval model + API (generic, multi-type) | 1.0 | Phase 1 |
| 2.2.2 | Multi-level approval chain logic | 1.0 | 2.2.1 |
| 2.2.3 | Approval inbox page (pending/rejected/approved tabs) | 1.0 | 2.2.2 |
| 2.2.4 | Approval detail view with action buttons | 0.5 | 2.2.3 |
| 2.2.5 | Integrate approvals into report workflow (enhance Phase 1) | 0.5 | 2.2.2 |
| 2.2.6 | Integrate approvals into material requests | 0.5 | 2.2.2 |

**Subtotal: 4.5 days**

### 2.3 Notifications System

| # | Task | Est. (days) | Depends On |
|---|------|-------------|------------|
| 2.3.1 | Notification model + API | 0.5 | Phase 1 |
| 2.3.2 | Notification triggers (report approved/rejected, low stock) | 1.0 | 2.3.1, 2.2.2, 2.1.4 |
| 2.3.3 | Email notification service (Celery task) | 0.5 | 2.3.2 |
| 2.3.4 | Notification bell + dropdown in header | 1.0 | 2.3.2 |
| 2.3.5 | Notification list page (full history) | 0.5 | 2.3.4 |

**Subtotal: 3.5 days**

### 2.4 Document Management

| # | Task | Est. (days) | Depends On |
|---|------|-------------|------------|
| 2.4.1 | Document + document_versions models | 0.5 | Phase 1 |
| 2.4.2 | Document upload/download API + version control | 1.0 | 2.4.1 |
| 2.4.3 | Full-text search API (PostgreSQL tsvector) | 0.5 | 2.4.2 |
| 2.4.4 | Document library page with type filters | 1.0 | 2.4.2 |
| 2.4.5 | Document upload form with metadata | 0.5 | 2.4.4 |
| 2.4.6 | Version history panel + download old versions | 0.5 | 2.4.4 |

**Subtotal: 4 days**

### 2.5 Testing & Polish (Phase 2)

| # | Task | Est. (days) | Depends On |
|---|------|-------------|------------|
| 2.5.1 | Backend tests (materials, approvals, notifications) | 1.5 | All Phase 2 |
| 2.5.2 | Frontend component tests | 1.0 | All Phase 2 |
| 2.5.3 | Integration testing + bug fixes | 1.0 | 2.5.1, 2.5.2 |

**Subtotal: 3.5 days**

### Phase 2 Total: ~21.5 days

---

## Phase 3: Financials, Analytics & Mobile

**Goal**: Accounts integration, advanced analytics, mobile-responsive enhancements, PWA capabilities.

### 3.1 Accounts Integration

| # | Task | Est. (days) |
|---|------|-------------|
| 3.1.1 | Invoice tracking model + accounts dashboard | 2.0 |
| 3.1.2 | Invoice upload + OCR placeholder (future AI) | 1.5 |
| 3.1.3 | Payment tracking + status updates | 1.0 |
| 3.1.4 | Financial summary reports (budget vs actual) | 1.5 |

**Subtotal: 6 days**

### 3.2 Analytics & Reporting

| # | Task | Est. (days) |
|---|------|-------------|
| 3.2.1 | Advanced dashboard charts (Recharts) | 1.5 |
| 3.2.2 | Export to Excel (reports, inventory) — openpyxl | 1.0 |
| 3.2.3 | Export to PDF (project summaries) — WeasyPrint | 1.5 |
| 3.2.4 | Material consumption trends + forecasting | 1.0 |

**Subtotal: 5 days**

### 3.3 PWA & Mobile Responsive Enhancements

| # | Task | Est. (days) |
|---|------|-------------|
| 3.3.1 | Service Worker setup (offline app shell caching) | 1.0 |
| 3.3.2 | IndexedDB for offline draft saving (reports) | 1.5 |
| 3.3.3 | Background sync for offline drafts | 1.0 |
| 3.3.4 | Camera-optimized upload flow (capture attribute) | 0.5 |
| 3.3.5 | Mobile UX polish (touch targets, gestures, loading states) | 1.0 |
| 3.3.6 | Web App Manifest + install prompt | 0.5 |

**Subtotal: 5.5 days**

### 3.4 Testing & Polish (Phase 3)

| # | Task | Est. (days) |
|---|------|-------------|
| 3.4.1 | Cross-device testing (iOS Safari, Android Chrome) | 1.0 |
| 3.4.2 | Performance audit (Lighthouse) + optimization | 1.0 |
| 3.4.3 | Final bug fixes + regression testing | 1.0 |

**Subtotal: 3 days**

### Phase 3 Total: ~19.5 days

---

## Summary

| Phase | Focus | Est. Days | Est. Weeks (5-day) |
|-------|-------|-----------|---------------------|
| **Phase 1** | Foundation & Reporting | 29.5 | ~6 weeks |
| **Phase 2** | Supply Chain & Workflows | 21.5 | ~4.5 weeks |
| **Phase 3** | Financials & Mobile | 19.5 | ~4 weeks |
| **Total** | | **70.5** | **~14 weeks** |

### Team Size Recommendation

| Team Size | Est. Calendar Time |
|-----------|-------------------|
| 1 dev (full-stack) | ~4 months |
| 2 devs (1 frontend + 1 backend) | ~2.5 months |
| 3 devs (1 frontend, 1 backend, 1 flex) | ~2 months |

---

## Task Status Legend

```
[ ] Not Started    [~] In Progress    [x] Done    [!] Blocked
```
