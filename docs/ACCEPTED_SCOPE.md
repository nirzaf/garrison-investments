# Garrisons portal release scope

This inventory defines the release scope for the Garrisons Construction Internal Portal (`launch_readiness_only`, `G-01` excluded). It is an unsigned scope baseline: authenticated business-sponsor approval of its frozen digest and formal release acceptance remain pending as described in [POST_RELEASE_ACTIONS.md](POST_RELEASE_ACTIONS.md) and the [operations runbook](OPERATIONS_AND_DEPLOYMENT.md#5-launch-evidence-capture--sign-off).

| Area | Release scope | Source |
| --- | --- | --- |
| Identity | Password and emailed OTP sign-in, session management, voluntary password change and recovery, a read-only profile, and authorized account and role administration | [Authentication routes](../backend/app/api/v1/auth.py), [role matrix](ROLES_AND_PERMISSIONS.md) |
| Projects | Scoped project records, team assignment, BOQ and milestones, task dependencies, and schedule views | [Project routes](../backend/app/api/v1/projects.py), [frontend routes](../frontend/src/App.tsx) |
| Site reporting | Supervisor updates, engineer verification through daily reports, reject/correct/resubmit and approval, and approved PDFs | [Reporting service](../backend/app/services/report_service.py), [reporting pages](../frontend/src/pages/reports/) |
| Offline and media | Owned drafts, queued uploads and replay, conflict recovery, cumulative photo limits, protected file access, and eligible deletion/recovery | [Offline queue](../frontend/src/api/offlineQueue.ts), [photo service](../backend/app/services/photo_service.py) |
| Document control | Search, filters, version uploads, approval and activation, and protected current or superseded versions | [Document service](../backend/app/services/document_service.py) |
| Inventory and approvals | Stock and movements by location, receipts, transfers, returns, adjustments, tagged assets, partial fulfillment, cancellation, and authorized inbox, outbox, delegation, and escalation | [Inventory service](../backend/app/services/inventory_service.py), [approval service](../backend/app/services/approval_service.py) |
| Suppliers and finance | Supplier compliance and TDS, least-privilege supplier options, invoice correction and approval, payments and budget summaries | [Supplier routes](../backend/app/api/v1/suppliers.py), [finance service](../backend/app/services/finance_service.py) |
| Analytics and import | Scoped dashboards, filtered XLSX/PDF exports, and approved-format data and metadata imports | [Analytics routes](../backend/app/api/v1/analytics.py), [import templates](import_templates/README.md) |
| Guidance and operations | Role manuals, notifications, security and audit views, and Launch readiness at the existing management-only `/delivery` route | [Portal manuals](../frontend/src/pages/manual/), [Launch readiness](../frontend/src/pages/delivery/DeliveryPlanPage.tsx), [operations runbook](OPERATIONS_AND_DEPLOYMENT.md) |

The selected release scope is `launch_readiness_only`; formal authenticated approval bound to the frozen scope digest remains outstanding. Logistics scheduling, fleet and vehicle management, delivery booking, dispatch and routing, and stock posting from a delivery workflow require a separately approved product increment. Inventory receipts and stock movements remain within the existing stores workflow.

G-01, mandatory password-change enforcement, is excluded. Existing voluntary password change, password reset, and authentication remain in scope. Configured monitoring, recovery, retention, and deployment components require executed operational evidence for the specific release and environment.
