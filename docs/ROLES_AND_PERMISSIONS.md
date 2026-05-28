# User Roles And Permissions

## Purpose

This document describes the user roles, privileges, features, and functional access that are currently implemented in the codebase.

Primary source of truth:

- [backend/app/utils/permissions.py](../backend/app/utils/permissions.py)
- [backend/app/api/dependencies.py](../backend/app/api/dependencies.py)
- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/components/layout/AppLayout.tsx](../frontend/src/components/layout/AppLayout.tsx)
- [docs/ARCHITECTURE.md](ARCHITECTURE.md)

This file documents current code behavior first. Where the architecture document or product intent differs from the code, the difference is called out explicitly in the Mismatches And Caveats section.

## How Access Control Works

The project uses role-based access control with permission strings.

1. Each user has exactly one role.
2. Each role maps to a fixed set of permissions in [backend/app/utils/permissions.py](../backend/app/utils/permissions.py).
3. Backend APIs typically enforce authorization with `require_permission(...)` from [backend/app/api/dependencies.py](../backend/app/api/dependencies.py).
4. The frontend uses the `permissions` array on the authenticated user to decide which routes and navigation items are visible.
5. Some important flows, especially dashboard, reports, and approvals, also apply service-layer authorization and data scoping in backend services.

## Common Authenticated Experience

All authenticated users currently have access to a baseline signed-in experience even if they have different business permissions.

- Sign in and refresh session tokens
- Change password
- View profile
- Open the dashboard route
- View notifications

Important note:

- The dashboard route itself is not frontend-gated by a permission wrapper.
- The backend dashboard service returns company-wide data for `admin`, `general_manager`, and `operation_manager`, and scoped data for other roles.

Relevant files:

- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [backend/app/services/dashboard_service.py](../backend/app/services/dashboard_service.py)

## Implemented Roles

The backend defines eight valid roles.

| Role Key | Plain-English Meaning | Notes |
|---|---|---|
| `admin` | Platform administrator | Full permission set in code |
| `general_manager` | Senior company-wide manager | Company-wide operational visibility; same permission set as operation manager in current code |
| `operation_manager` | Operations manager | Company-wide operational visibility and approvals |
| `project_manager` | Project-level manager | Scoped dashboard plus project, approvals, finance, and document access |
| `civil_engineer` | Site engineer | Can submit reports and work with project-scoped operational features |
| `civil_supervisor` | Site supervisor | Can submit supervisor updates and use project-scoped reporting features |
| `store_keeper` | Inventory and stores operator | Inventory-heavy role with supplier access |
| `accounts` | Finance and accounting user | Finance, documents, and scoped reporting visibility |

Canonical definition:

- [backend/app/utils/permissions.py](../backend/app/utils/permissions.py)

## Permission Glossary

The backend currently defines 15 permission keys.

| Permission | Meaning In The Current Codebase |
|---|---|
| `users:manage` | Create and manage users; also used to gate the imports screen and import endpoints |
| `users:read` | Read user-management data |
| `projects:manage` | Create or manage projects in backend and manage project UI controls |
| `projects:read` | View project data and access project-related screens |
| `audit:view` | Access audit and security-oriented monitoring screens |
| `dashboard:company` | Access company-wide management features such as analytics and delivery planning |
| `dashboard:scoped` | Indicates scoped dashboard access for non-company-wide roles |
| `reports:view` | View reporting-related content such as photos and report visibility flows |
| `reports:submit` | Submit daily reports or supervisor updates |
| `reports:approve` | Approve report-driven workflows and access the approvals inbox |
| `inventory:view` | View inventory and materials pages |
| `inventory:manage` | Manage inventory operations |
| `suppliers:manage` | Manage supplier records and supplier TDS document flows |
| `documents:manage` | Access document management features |
| `financial:view` | Access finance features |

Canonical definition:

- [backend/app/utils/permissions.py](../backend/app/utils/permissions.py)

## Role-Permission Matrix

The table below reflects the current implemented matrix in [backend/app/utils/permissions.py](../backend/app/utils/permissions.py).

| Permission | Admin | GenMgr | OpMgr | ProjMgr | CivEng | CivSup | StoreKpr | Accounts |
|---|---|---|---|---|---|---|---|---|
| `users:manage` | Y | - | - | - | - | - | - | - |
| `users:read` | Y | Y | Y | - | - | - | - | - |
| `projects:manage` | Y | Y | Y | - | - | - | - | - |
| `projects:read` | Y | Y | Y | Y | Y | Y | - | Y |
| `audit:view` | Y | - | - | - | - | - | - | - |
| `dashboard:company` | Y | Y | Y | - | - | - | - | - |
| `dashboard:scoped` | Y | - | - | Y | Y | Y | Y | Y |
| `reports:view` | Y | Y | Y | Y | Y | Y | - | Y |
| `reports:submit` | Y | - | - | - | Y | Y | - | - |
| `reports:approve` | Y | Y | Y | Y | - | - | - | - |
| `inventory:view` | Y | Y | Y | Y | Y | - | Y | - |
| `inventory:manage` | Y | - | - | - | - | - | Y | - |
| `suppliers:manage` | Y | Y | Y | - | - | - | Y | - |
| `documents:view` | Y | Y | Y | Y | Y | Y | - | Y |
| `documents:manage` | Y | Y | Y | Y | Y | - | - | Y |
| `financial:view` | Y | Y | Y | Y | - | - | - | Y |

## Frontend Feature And Route Gates

The frontend is mostly permission-driven.

Primary gating points:

- [frontend/src/App.tsx](../frontend/src/App.tsx) for route protection
- [frontend/src/components/layout/AppLayout.tsx](../frontend/src/components/layout/AppLayout.tsx) for visible navigation
- [frontend/src/components/layout/RequirePermission.tsx](../frontend/src/components/layout/RequirePermission.tsx) for redirect-on-missing-permission behavior

### Route-Level Access

| Route | Frontend Permission Requirement | Notes |
|---|---|---|
| `/dashboard` | None | Always reachable after authentication; backend scopes returned data |
| `/profile` | None | Authenticated baseline feature |
| `/change-password` | None | Authenticated baseline feature |
| `/notifications` | None | Authenticated baseline feature |
| `/projects` | `projects:read` | Project list and project detail workflows |
| `/admin/users` | `users:read` | User management screen |
| `/admin/audit-logs` | `audit:view` | Audit log screen |
| `/admin/imports` | `users:manage` | Imports administration |
| `/documents` | `documents:manage` | Documents page |
| `/photos` | `reports:view` | Photo/report evidence view |
| `/materials` | `inventory:view` | Inventory and materials page |
| `/finance` | `financial:view` | Finance page |
| `/analytics` | `dashboard:company` | Management analytics |
| `/security` | `audit:view` | Security page |
| `/delivery` | `dashboard:company` | Delivery planning page |
| `/reports/daily` | `reports:submit` | Daily report workflow |
| `/reports/supervisor-update` | `reports:submit` | Supervisor update workflow |
| `/approvals` | `reports:approve` | Approval inbox |

### Navigation-Level Visibility

The left navigation in [frontend/src/components/layout/AppLayout.tsx](../frontend/src/components/layout/AppLayout.tsx) is filtered by permission.

Special behavior:

- The Reports nav item points to `/reports/supervisor-update` when the user role is `civil_supervisor`.
- For every other role with reporting access, the Reports nav item points to `/reports/daily`.
- Users with `dashboard:company` permission also see the dashboard-related tabs `Analytics` and `Delivery` at the end of the navigation.

### Component-Level UI Differences

The codebase contains a small amount of permission-aware UI inside pages.

- [frontend/src/pages/projects/ProjectListPage.tsx](../frontend/src/pages/projects/ProjectListPage.tsx) checks `projects:manage` to decide whether project-management controls should be available.

## Backend Enforcement Overview

Backend authorization is split between explicit route-level permission decorators and service-layer business rules.

### Explicit Route-Level Permission Enforcement

| Module | Enforcement Style | Effective Permission |
|---|---|---|
| Users | `require_permission(...)` | `users:read`, `users:manage` |
| Projects | `require_permission(...)` | `projects:read`, `projects:manage` |
| Inventory | `require_permission(...)` | `inventory:view`, `inventory:manage` |
| Documents | `require_permission(...)` | `documents:manage` |
| Finance | `require_permission(...)` | `financial:view` |
| Audit | `require_permission(...)` | `audit:view` |
| Imports | `require_permission(...)` | `users:manage` |
| Suppliers | `require_permission(...)` | `suppliers:manage` |

Relevant files:

- [backend/app/api/v1/users.py](../backend/app/api/v1/users.py)
- [backend/app/api/v1/projects.py](../backend/app/api/v1/projects.py)
- [backend/app/api/v1/inventory.py](../backend/app/api/v1/inventory.py)
- [backend/app/api/v1/documents.py](../backend/app/api/v1/documents.py)
- [backend/app/api/v1/finance.py](../backend/app/api/v1/finance.py)
- [backend/app/api/v1/audit.py](../backend/app/api/v1/audit.py)
- [backend/app/api/v1/imports.py](../backend/app/api/v1/imports.py)
- [backend/app/api/v1/suppliers.py](../backend/app/api/v1/suppliers.py)

### Service-Layer Authorization And Scoping

Some important modules rely on authenticated access at the route layer and enforce detailed behavior deeper in services.

| Module | Current Behavior |
|---|---|
| Dashboard | Route is available to authenticated users; [backend/app/services/dashboard_service.py](../backend/app/services/dashboard_service.py) scopes project visibility by role |
| Reports | Submission and approval logic is enforced in [backend/app/services/report_service.py](../backend/app/services/report_service.py), including engineer-only submission, approver checks, and admin-only override |
| Approvals | Approval capabilities are tied to reporting approval rules and project context rather than a dedicated frontend permission beyond `reports:approve` |
| Projects | [backend/app/services/project_service.py](../backend/app/services/project_service.py) allows unrestricted access for higher-privilege roles and project-member-only access for scoped roles |

## Role-By-Role Functional Access

This section explains what each role can do in practical terms.

### Admin

**Permissions**

- All 15 permissions

**Frontend Features**

- Baseline authenticated features: dashboard, profile, notifications, password change
- Projects
- Users
- Audit logs
- Imports
- Documents
- Photos
- Materials
- Finance
- Analytics
- Security
- Delivery
- Reports
- Approvals

**Backend And Workflow Capabilities**

- Full user administration
- Full project read and management access
- Full reporting visibility and approval rights
- Can override daily report approvals in [backend/app/services/report_service.py](../backend/app/services/report_service.py)
- Full inventory visibility and management
- Full supplier management
- Full document management
- Full finance visibility
- Full audit visibility
- Full import administration

### General Manager

**Permissions**

- `users:read`
- `projects:read`
- `projects:manage`
- `dashboard:company`
- `reports:view`
- `reports:approve`
- `inventory:view`
- `suppliers:manage`
- `documents:manage`
- `financial:view`

**Frontend Features**

- Baseline authenticated features
- Projects
- Users
- Documents
- Photos
- Materials
- Finance
- Analytics
- Delivery
- Approvals

**Backend And Workflow Capabilities**

- View user-management data but cannot manage users
- Create and manage projects
- Receive company-wide dashboard visibility in backend services
- Approve reporting workflows
- View inventory
- Manage suppliers
- Manage documents
- View finance data

**Current Code Note**

- `general_manager` currently has the same permission set as `operation_manager`.

### Operation Manager

**Permissions**

- `users:read`
- `projects:read`
- `projects:manage`
- `dashboard:company`
- `reports:view`
- `reports:approve`
- `inventory:view`
- `suppliers:manage`
- `documents:manage`
- `financial:view`

**Frontend Features**

- Baseline authenticated features
- Projects
- Users
- Documents
- Photos
- Materials
- Finance
- Analytics
- Delivery
- Approvals

**Backend And Workflow Capabilities**

- Same effective permission coverage as general manager in the current codebase
- Company-wide dashboard visibility
- Project management
- Reporting approvals
- Inventory visibility
- Supplier management
- Document management
- Finance visibility

### Project Manager

**Permissions**

- `dashboard:scoped`
- `projects:read`
- `reports:view`
- `reports:approve`
- `inventory:view`
- `documents:manage`
- `financial:view`

**Frontend Features**

- Baseline authenticated features
- Projects
- Documents
- Photos
- Materials
- Finance
- Approvals

**Backend And Workflow Capabilities**

- Scoped dashboard visibility for owned or assigned project context
- Read project data
- Approve report workflows for the relevant project context
- View inventory data
- Manage documents
- View finance data

**Limitations**

- Cannot manage users
- Cannot use imports
- Cannot use analytics or delivery planning
- Cannot submit reports directly through the `reports:submit` permission path

### Civil Engineer

**Permissions**

- `dashboard:scoped`
- `projects:read`
- `reports:view`
- `reports:submit`
- `inventory:view`
- `documents:manage`

**Frontend Features**

- Baseline authenticated features
- Projects
- Reports
- Documents
- Photos
- Materials

**Backend And Workflow Capabilities**

- Scoped dashboard visibility
- Read project data
- Submit daily reports
- View reporting content
- View inventory data
- Manage documents

**Important Behavior**

- Report submission is further checked in [backend/app/services/report_service.py](../backend/app/services/report_service.py). The service ensures the submitting user is the right engineer and project member for the report.

### Civil Supervisor

**Permissions**

- `dashboard:scoped`
- `projects:read`
- `reports:view`
- `reports:submit`

**Frontend Features**

- Baseline authenticated features
- Projects
- Reports

**Backend And Workflow Capabilities**

- Scoped dashboard visibility
- Read project data
- Submit supervisor-update style reporting flows
- View reporting content

**Important Behavior**

- In the frontend navigation, the Reports link routes this role to `/reports/supervisor-update` instead of `/reports/daily`.

### Store Keeper

**Permissions**

- `dashboard:scoped`
- `inventory:view`
- `inventory:manage`
- `suppliers:manage`

**Frontend Features**

- Baseline authenticated features
- Materials

**Backend And Workflow Capabilities**

- Scoped dashboard visibility
- View and manage inventory workflows
- Manage suppliers and supplier TDS document flows in the backend APIs

**Frontend Caveat**

- There is no standalone Suppliers page in the current frontend navigation.
- Supplier APIs exist and supplier data is used indirectly in parts of the UI, such as finance workflows.

### Accounts

**Permissions**

- `dashboard:scoped`
- `projects:read`
- `reports:view`
- `documents:view`
- `documents:manage`
- `financial:view`

**Frontend Features**

- Baseline authenticated features
- Projects
- Documents
- Photos
- Finance

**Backend And Workflow Capabilities**

- Scoped dashboard visibility
- Read project data
- View reporting content
- Manage documents
- View finance features and finance-linked project data

## Staging Role Verification Accounts

For UAT, smoke testing, and role-based walkthroughs, staging currently includes one test account for each implemented role.

Source reference:

- [STAGING_DEPLOYMENT.md](../STAGING_DEPLOYMENT.md)

These accounts are environment-specific and do not change the RBAC model described above. They exist to help testers verify that each role sees the correct routes, navigation items, and workflows.

### Staging Login Details

Shared staging login OTP:

- `123456`

Role-specific staging accounts:

| Role | Email |
|---|---|
| Admin | `stg-admin@garrisons.qa` |
| General Manager | `stg-general-manager@garrisons.qa` |
| Operation Manager | `stg-operation-manager@garrisons.qa` |
| Project Manager | `stg-project-manager@garrisons.qa` |
| Civil Engineer | `stg-civil-engineer@garrisons.qa` |
| Civil Supervisor | `stg-civil-supervisor@garrisons.qa` |
| Store Keeper | `stg-store-keeper@garrisons.qa` |
| Accounts | `stg-accounts@garrisons.qa` |

### What These Accounts Are For

These staging users are suitable for validating:

- role-specific frontend navigation visibility
- route access controlled by `RequirePermission`
- backend permission enforcement for the main feature areas
- role-specific workflow differences such as report submission versus approval access
- the civil supervisor redirect to the supervisor update report flow

### Staging Verification Already Completed

The staging deployment notes confirm the following:

- one active staging user exists for each implemented role
- login was verified successfully for `stg-civil-engineer@garrisons.qa`
- the verified staging login used the shared OTP `123456`
- `must_change_password=false` was confirmed for the tested account so UAT users are not blocked by forced password reset
- the updated staging deployment document was synced back to the staging server path

Password note:

- Staging passwords should be provided via environment configuration (see `SEED_DEFAULT_PASSWORD` in `scripts/seed.py`) and should not be committed to this repository.

### Usage Note

These credentials are intended for staging only. They should be rotated, changed, or removed before any production release process.

## Functional Access By Business Area

This table summarizes which permission drives each major functional area.

| Business Area | Primary Permission | Current Functional Outcome |
|---|---|---|
| User administration | `users:manage` or `users:read` | Read or manage users depending on permission |
| Project portfolio | `projects:read` / `projects:manage` | View projects, with management controls enabled for `projects:manage` |
| Dashboard | `dashboard:company` / `dashboard:scoped` | Company-wide or scoped visibility, though route access is authenticated rather than explicitly permission-decorated. `dashboard:company` users also see Analytics and Delivery as dashboard tabs at the end of the main navigation. |
| Daily reports | `reports:submit` | Submit daily reports or supervisor updates |
| Approvals | `reports:approve` | Access approval inbox and approval workflows |
| Report evidence | `reports:view` | Access report-adjacent content such as photos |
| Inventory and materials | `inventory:view` / `inventory:manage` | View materials page and manage inventory operations |
| Suppliers | `suppliers:manage` | Use supplier APIs, supplier TDS upload/download flows, and supplier-backed selections in finance |
| Documents | `documents:manage` | Use documents page and document workflows |
| Finance | `financial:view` | Use finance page and financial reporting workflows |
| Imports | `users:manage` | Access import administration |
| Audit and security | `audit:view` | Access audit logs and security page |
| Analytics and delivery | `dashboard:company` | Access management-only analytics and delivery planning |

## Mismatches And Caveats

This section records places where the implemented code differs from the broader architecture narrative or where behavior is more nuanced than the permission matrix alone suggests.

### 1. Architecture Matrix Does Not Match The Current Role List Exactly

- [docs/ARCHITECTURE.md](ARCHITECTURE.md) presents a matrix without a dedicated `general_manager` column.
- The code in [backend/app/utils/permissions.py](../backend/app/utils/permissions.py) includes `general_manager` as a first-class role.

### 2. General Manager And Operation Manager Are Identical In Current Code

- The code gives `general_manager` and `operation_manager` the same permission set.
- If the business intends a stronger hierarchy, that distinction is not currently implemented in the permission matrix.

### 3. Dashboard Authorization Is Mostly Service-Scoped, Not Route-Decorated

- The frontend allows all authenticated users to open `/dashboard`.
- Backend scoping is applied inside [backend/app/services/dashboard_service.py](../backend/app/services/dashboard_service.py) rather than with an explicit route-level permission decorator.

### 4. Reports And Approvals Depend On Service Rules In Addition To Permissions

- The frontend uses `reports:submit` and `reports:approve` to gate pages.
- The backend applies more specific checks in [backend/app/services/report_service.py](../backend/app/services/report_service.py), such as engineer-only submission, approver eligibility, project membership checks, and admin-only override behavior.

### 5. Supplier Management Exists In Backend More Than In Frontend Navigation

- The backend exposes a full supplier API surface in [backend/app/api/v1/suppliers.py](../backend/app/api/v1/suppliers.py).
- The frontend does not currently expose a dedicated Suppliers page in the main navigation.
- Supplier data is still consumed by frontend finance flows.

### 6. Architecture Describes Finer-Grained Capabilities Than The Code Currently Implements

Examples from [docs/ARCHITECTURE.md](ARCHITECTURE.md):

- `Inventory: Transfer/Issue`
- `Material Pricing: View`
- More granular document and approvals distinctions

The current implemented permission set does not define separate permission keys for those capabilities. They are either folded into broader permissions or enforced through service behavior rather than a unique RBAC key.

## Recommended Source Files For Future Audits

If this document needs to be refreshed, start with these files:

- [backend/app/utils/permissions.py](../backend/app/utils/permissions.py)
- [backend/app/api/dependencies.py](../backend/app/api/dependencies.py)
- [backend/app/api/v1/router.py](../backend/app/api/v1/router.py)
- [backend/app/api/v1/suppliers.py](../backend/app/api/v1/suppliers.py)
- [backend/app/services/dashboard_service.py](../backend/app/services/dashboard_service.py)
- [backend/app/services/report_service.py](../backend/app/services/report_service.py)
- [backend/app/services/project_service.py](../backend/app/services/project_service.py)
- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/components/layout/AppLayout.tsx](../frontend/src/components/layout/AppLayout.tsx)
- [frontend/src/components/layout/RequirePermission.tsx](../frontend/src/components/layout/RequirePermission.tsx)

## Summary

The current project is permission-driven with a single-role model.

- `admin` is the only full-access role.
- `general_manager` and `operation_manager` currently behave the same.
- `project_manager` is the strongest scoped management role.
- `civil_engineer` and `civil_supervisor` are reporting-focused execution roles.
- `store_keeper` is the inventory-focused operational role.
- `accounts` is the finance-document role.

The backend permission matrix is clear and implemented, but some important access rules still live in services instead of explicit route-level permission wrappers. This document should therefore be used together with the referenced service files when auditing real access behavior.
