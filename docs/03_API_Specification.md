# API Specification — Construction Internal Portal

## Conventions

- **Base URL**: `/api/v1`
- **Content-Type**: `application/json`
- **Auth Header**: `Authorization: Bearer <access_token>`
- **Date Format**: ISO 8601 (`2026-05-14T10:30:00+05:30`)
- **Pagination**: `?page=1&per_page=20` — returns `{ items, total, page, per_page, total_pages }`
- **Soft Deletes**: `DELETE` endpoints set `deleted_at`, don't physically remove rows
- **Errors**: `{ "detail": "...", "errors": [{ "field": "...", "message": "..." }] }`

---

## Authentication

### POST `/auth/login`

```json
// Request
{
  "email": "user@example.com",
  "password": "string"
}

// Response 200
{
  "access_token": "eyJhbG...",
  "refresh_token": "eyJhbG...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "uuid",
    "full_name": "John Doe",
    "email": "user@example.com",
    "role": "project_manager"
  }
}
```

### POST `/auth/refresh`

```json
// Request
{ "refresh_token": "eyJhbG..." }

// Response 200
{ "access_token": "eyJhbG...", "expires_in": 900 }
```

### POST `/auth/logout`

Invalidates refresh token on server side.

### GET `/auth/me`

Returns current user profile with permissions.

---

## Users (Admin)

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `GET` | `/users` | List users (paginated, filterable) | Admin, OpManager |
| `GET` | `/users/{id}` | Get user detail | Admin, OpManager |
| `POST` | `/users` | Create user | Admin |
| `PATCH` | `/users/{id}` | Update user | Admin |
| `DELETE` | `/users/{id}` | Deactivate user | Admin |
| `PATCH` | `/users/{id}/role` | Change user role | Admin |

---

## Projects

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `GET` | `/projects` | List projects (paginated, filterable) | All authenticated |
| `GET` | `/projects/{id}` | Get project detail + summary stats | All authenticated |
| `POST` | `/projects` | Create project | Admin, OpManager |
| `PATCH` | `/projects/{id}` | Update project | Admin, OpManager, ProjManager |
| `GET` | `/projects/{id}/timeline` | Get timeline data | All authenticated |
| `GET` | `/projects/{id}/members` | Get project members | All authenticated |
| `POST` | `/projects/{id}/members` | Assign member to project | Admin, OpManager |

### GET `/projects/{id}` Example Response

```json
{
  "id": "uuid",
  "name": "Tower A Construction",
  "code": "TA-2026",
  "status": "active",
  "progress_percentage": 42.5,
  "budget_amount": 15000000.00,
  "start_date": "2026-01-15",
  "target_end_date": "2027-06-30",
  "summary": {
    "total_reports": 120,
    "last_report_date": "2026-05-13",
    "material_requests_pending": 3,
    "open_issues": 2
  }
}
```

---

## Daily Reports

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `GET` | `/reports` | List reports (paginated, filterable by project/date/status) | All |
| `GET` | `/reports/{id}` | Get report with manpower, equipment, materials, photos | All |
| `POST` | `/reports` | Create report (draft) | Eng, Supervisor |
| `PATCH` | `/reports/{id}` | Update report (if draft/rejected) | Eng, Supervisor |
| `POST` | `/reports/{id}/submit` | Submit for approval | Eng |
| `POST` | `/reports/{id}/approve` | Approve report | ProjManager, OpManager, Admin |
| `POST` | `/reports/{id}/reject` | Reject with reason | ProjManager, OpManager, Admin |

### POST `/reports` Request

```json
{
  "project_id": "uuid",
  "report_date": "2026-05-14",
  "weather_condition": "sunny",
  "temperature": 34.5,
  "work_completed": "Completed slab casting for 3rd floor, west wing",
  "progress_percentage": 42.5,
  "issues_delays": "Delay in steel delivery expected tomorrow",
  "next_day_plan": "Begin column shuttering for 4th floor",
  "extra_fields": {
    "safety_incidents": 0,
    "site_visitors": 2
  },
  "manpower": [
    { "labor_type": "skilled", "trade": "mason", "count": 12, "hours_worked": 8.0 },
    { "labor_type": "unskilled", "trade": "helper", "count": 20, "hours_worked": 8.0 }
  ],
  "equipment": [
    { "equipment_name": "Concrete Mixer", "quantity": 2, "hours_used": 6.0 }
  ],
  "material_consumption": [
    { "material_name": "Cement (OPC 43)", "quantity": 150, "unit": "bags" }
  ],
  "photos": ["uuid-of-uploaded-photo-1", "uuid-of-uploaded-photo-2"]
}
```

---

## Photo Upload

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/photos/upload` | Upload photo(s) — multipart form data |
| `GET` | `/photos/{id}` | Get photo metadata |
| `GET` | `/photos/{id}/download` | Stream photo file |
| `GET` | `/photos/{id}/thumbnail` | Stream thumbnail |
| `DELETE` | `/photos/{id}` | Soft-delete photo |

### POST `/photos/upload`

- `multipart/form-data`
- Field: `files` (multiple, max 10 MB each)
- Field: `entity_type`, `entity_id` (optional, can link later)
- Response: `[{ "id": "uuid", "storage_path": "...", "thumbnail_url": "..." }]`

---

## Materials & Inventory

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `GET` | `/materials` | List materials (paginated, filterable) | All |
| `GET` | `/materials/{id}` | Material detail + transaction history | All |
| `POST` | `/materials` | Create material item | StoreKeeper, Admin |
| `PATCH` | `/materials/{id}` | Update material | StoreKeeper, Admin |
| `POST` | `/materials/transactions` | Record stock in/out | StoreKeeper |
| `GET` | `/materials/low-stock` | Get items at or below reorder point | StoreKeeper, ProjManager |

### POST `/materials/transactions`

```json
{
  "material_id": "uuid",
  "transaction_type": "in",
  "quantity": 500,
  "reference_type": "purchase",
  "notes": "Purchase Order #PO-2026-0451"
}
```

---

## Suppliers

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/suppliers` | List suppliers |
| `POST` | `/suppliers` | Add supplier |
| `PATCH` | `/suppliers/{id}` | Update supplier |
| `DELETE` | `/suppliers/{id}` | Deactivate supplier |

---

## Documents

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/documents` | List documents (filterable by type/project) |
| `GET` | `/documents/{id}` | Document metadata |
| `GET` | `/documents/{id}/download` | Download file |
| `POST` | `/documents` | Upload document + metadata (multipart) |
| `POST` | `/documents/{id}/versions` | Upload new version |
| `GET` | `/documents/{id}/versions` | List version history |
| `GET` | `/documents/search?q=` | Full-text search documents |

---

## Approvals

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/approvals/inbox` | Pending approvals for current user |
| `GET` | `/approvals/outbox` | Requests made by current user |
| `GET` | `/approvals/{id}` | Get approval detail |
| `POST` | `/approvals/{id}/approve` | Approve with optional comments |
| `POST` | `/approvals/{id}/reject` | Reject with reason |

---

## Notifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/notifications` | List notifications for current user |
| `GET` | `/notifications/unread-count` | Get unread count |
| `PATCH` | `/notifications/{id}/read` | Mark as read |
| `POST` | `/notifications/mark-all-read` | Mark all as read |

---

## Dashboard & Analytics

| Method | Endpoint | Description | Permission |
|--------|----------|-------------|------------|
| `GET` | `/dashboard/summary` | Overall project stats | All (scoped to role) |
| `GET` | `/dashboard/project/{id}/progress` | Project progress over time | All |
| `GET` | `/dashboard/material-usage` | Material consumption trends | StoreKeeper, Manager |
| `GET` | `/dashboard/approval-stats` | Approval pipeline metrics | Manager, Admin |

### GET `/dashboard/summary` Response

```json
{
  "active_projects": 5,
  "total_manpower_today": 320,
  "reports_submitted_today": 4,
  "reports_pending_today": 2,
  "pending_approvals": 7,
  "low_stock_items": 3,
  "recent_activity": [
    { "type": "report_submitted", "project": "Tower A", "time": "2026-05-14T09:30:00Z" }
  ]
}
```

---

## Reports Export

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/export/reports?project_id=&from=&to=` | Export reports as XLSX |
| `GET` | `/export/inventory` | Export current inventory as XLSX |
| `GET` | `/export/project/{id}/summary` | Project summary as PDF |

---

## Paginated Response Format

```json
{
  "items": [...],
  "total": 156,
  "page": 1,
  "per_page": 20,
  "total_pages": 8
}
```

### Common Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `page` | int | Page number (default 1) |
| `per_page` | int | Items per page (default 20, max 100) |
| `sort_by` | string | Field to sort by |
| `sort_order` | string | `asc` or `desc` |
| `search` | string | Search/filter text |
| `from_date` | date | Filter start (inclusive) |
| `to_date` | date | Filter end (inclusive) |
| `status` | string | Filter by status |
