# Roles and permissions

Use this guide to find the applicable access checks. The [role mapping](../backend/app/utils/permissions.py) defines the baseline grants. The [backend enforcement](#backend-enforcement-overview) section covers project scope, ownership, and workflow-specific rules.

## How access control works

1. The [authentication dependency](../backend/app/api/dependencies.py) verifies the bearer token and loads the active user. Each user has one application role. [Auth service](../backend/app/services/auth_service.py)
2. Routes with `require_permission` check the permission set for that role. Other authenticated routes delegate authorization directly to their service. [Versioned API routes](../backend/app/api/v1/)
3. Services decide whether the actor can access the project or record and perform the requested state transition. The shared scope helper treats an empty membership list as zero assigned projects. The domain-specific rules below identify where behavior differs. [Shared authorization](../backend/app/services/authorization.py)
4. The frontend uses the permissions returned with the session to show menus, routes, and controls. The API enforces access independently. [Application layout](../frontend/src/components/layout/AppLayout.tsx) · [Route guard](../frontend/src/components/layout/RequirePermission.tsx)

## Implemented roles

| Role ID | Display name | Typical responsibilities |
| --- | --- | --- |
| `admin` | Admin | Account administration, imports, audit, and workflow overrides |
| `general_manager` | General Manager | Company oversight, project administration, and daily report decisions |
| `operation_manager` | Operation Manager | Company operations, project administration, and invoice and document decisions |
| `project_manager` | Project Manager | Assigned projects, scoped approvals, documents, and project finance |
| `civil_engineer` | Civil Engineer | Official daily reports and review of submitted field updates |
| `civil_supervisor` | Civil Supervisor | Own site updates for assigned projects |
| `store_keeper` | Store Keeper | Inventory, stock movements, requests, and suppliers |
| `accounts` | Accounts | Invoices, payments, and company project and document visibility |

## Role-permission matrix

A check marks a baseline grant. General Manager and Operation Manager share the same baseline grants. Their workflow decision rights differ.

| Permission | Admin | GM | OM | PM | Engineer | Supervisor | Store Keeper | Accounts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `users:manage` | ✓ | | | | | | | |
| `users:read` | ✓ | ✓ | ✓ | | | | | |
| `projects:manage` | ✓ | ✓ | ✓ | | | | | |
| `projects:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `audit:view` | ✓ | | | | | | | |
| `dashboard:company` | ✓ | ✓ | ✓ | | | | | |
| `dashboard:scoped` | ✓ | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `reports:view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `reports:submit` | ✓ | | | | ✓ | ✓ | | |
| `reports:approve` | ✓ | ✓ | ✓ | ✓ | | | | |
| `inventory:view` | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | |
| `inventory:manage` | ✓ | | | | | | ✓ | |
| `suppliers:manage` | ✓ | ✓ | ✓ | | | | ✓ | |
| `documents:view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `documents:manage` | ✓ | ✓ | ✓ | ✓ | ✓ | | | ✓ |
| `financial:view` | ✓ | ✓ | ✓ | ✓ | | | | ✓ |

## Frontend feature and route gates

Sign-in and password reset are public. Dashboard, notifications, profile, password change, roles, and manual pages require a session.

| Route | Additional permission |
| --- | --- |
| `/admin/users` | `users:read`. Account changes require `users:manage`. |
| `/admin/imports` | `users:manage` |
| `/admin/audit-logs`, `/security` | `audit:view` |
| `/projects` | `projects:read` |
| `/reports/daily`, `/photos` | `reports:view` |
| `/reports/supervisor-update` | `reports:view`. Civil Supervisors author updates. Other eligible roles review scoped updates. |
| `/approvals` | `reports:approve` |
| `/materials` | `inventory:view` |
| `/suppliers` | `suppliers:manage` |
| `/documents` | `documents:view` |
| `/finance` | `financial:view` |
| `/analytics`, `/delivery` | `dashboard:company` |

The `/reports` alias redirects to `/reports/daily`. The Civil Supervisor navigation link opens the supervisor update screen. The analytics browser page requires `dashboard:company`. [Frontend routes](../frontend/src/App.tsx) · [Application navigation](../frontend/src/components/layout/AppLayout.tsx)

## Backend enforcement overview

| Area | Effective access |
| --- | --- |
| Projects and dashboard | Project reads are company-wide for Admin, General Manager, Operation Manager, and Accounts. Other permitted readers see assigned projects. The dashboard uses company-wide scope for Admin, General Manager, and Operation Manager, and membership scope for the other roles, including Accounts. [Project service](../backend/app/services/project_service.py) · [Dashboard service](../backend/app/services/dashboard_service.py) |
| Official daily reports | Admin, General Manager, Operation Manager, and Accounts can list and read reports, access linked evidence, and retrieve available approved PDFs company-wide. Project Managers are scoped to assigned projects. Civil Engineers are scoped to their own reports and need project membership for draft writes. Admin and Civil Engineer can create and submit official reports. Admin, General Manager, Operation Manager, and assigned Project Managers can decide submitted reports. Civil Supervisors use the separate supervisor update workflow. [Report routes](../backend/app/api/v1/reports.py) · [Report service](../backend/app/services/report_service.py) · [PDF export service](../backend/app/services/report_export_service.py) |
| Supervisor updates | Civil Supervisors create updates for their assigned projects, edit their own drafts, and submit their own drafts. Civil Engineers list updates when an assigned project is selected. Project Managers see updates for assigned projects. Admin, General Manager, Operation Manager, and Accounts have company-wide listing scope. [Supervisor update service](../backend/app/services/reporting_service.py) |
| Generic approvals | The inbox and delegate picker require `reports:approve`. Approval details are visible to Admin and the relevant workflow participants. Ordinary decisions require the assigned approver or delegate. Admin can override a pending decision with a reason. Delegation requires an eligible active recipient for the request type and checks project membership for Project Manager delegates. [Approval routes](../backend/app/api/v1/approvals.py) · [Approval service](../backend/app/services/approval_service.py) |
| Documents | Reads and downloads apply project scope. Admin, General Manager, Operation Manager, and Accounts have company-wide access, including documents without a project. Version listing and upload require `documents:manage` and document scope. Admin and Operation Manager can approve company-wide versions. Assigned Project Managers can also approve versions for their projects. [Document routes](../backend/app/api/v1/documents.py) · [Document service](../backend/app/services/document_service.py) |
| Photos and attachments | View routes require `reports:view`. Upload and deletion require `reports:submit`. Entity listing, individual reads, signed links, uploads, and deletions check the relevant owner scope. In the recent feed, Project Managers see reports for assigned projects and Civil Engineers see their own reports in assigned projects. Civil Supervisors access permitted files through their supervisor updates. Report uploads require draft status. Admin can remove report files after submission and recover recently deleted files. [Photo routes](../backend/app/api/v1/photos.py) · [Photo service](../backend/app/services/photo_service.py) |
| Inventory and suppliers | `inventory:view` permits stock and material request reads and creation of material requests. `inventory:manage` permits stock management, reservation, and issue. The requester or an inventory manager can cancel an eligible request. Item responses mask `unit_cost` outside the configured price-visible roles, subject to the inventory route grant. Supplier routes require `suppliers:manage`. [Inventory routes](../backend/app/api/v1/inventory.py) · [Inventory service](../backend/app/services/inventory_service.py) · [Supplier routes](../backend/app/api/v1/suppliers.py) |
| Finance | `financial:view` gates invoice, attachment, payment, and budget routes. Project Managers are scoped to assigned projects. Invoice approval requires Admin or Operation Manager. Admin, Operation Manager, and Accounts can reject eligible invoices. Recording a payment requires an approved invoice and enough outstanding balance. [Finance routes](../backend/app/api/v1/finance.py) · [Finance service](../backend/app/services/finance_service.py) |
| Analytics and management exports | Admin, General Manager, Operation Manager, and Accounts have company-wide API access. Project Managers see assigned projects and their material movements in summaries, XLSX exports, and the management PDF. Unassigned Project Managers see an empty collection. An explicit out-of-scope project filter returns 403. [Analytics routes](../backend/app/api/v1/analytics.py) · [Analytics service](../backend/app/services/analytics_service.py) |
| Administration and audit | Admin manages users and imports. General Manager and Operation Manager can read users. Audit and operational log routes require `audit:view`. [User routes](../backend/app/api/v1/users.py) · [Import routes](../backend/app/api/v1/imports.py) · [Audit routes](../backend/app/api/v1/audit.py) · [Log routes](../backend/app/api/v1/logs.py) |

## Verify an access change

Check the [role-permission tests](../backend/tests/test_permissions.py), [authorization matrix](../backend/tests/test_authorization_matrix.py), [scope regressions](../backend/tests/test_scope_authorization.py), and [delegation guards](../backend/tests/test_delegation_guards.py). The [Chromium role-change test](../frontend/e2e/user-role.e2e.ts) covers changes through the Admin UI. Follow the [local verification commands](../README.md#verification) for disposable test services.
