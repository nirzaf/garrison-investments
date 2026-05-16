# Construction Internal Portal TO-DO User Stories

This folder breaks the Construction Internal Portal into implementation-ready user stories. The sequence follows [../ARCHITECTURE.md](../../ARCHITECTURE.md) as the implementation baseline and treats `REQUIREMENTS_QUESTIONS.md` as the latest requirement clarification where it overrides the earlier work breakdown.

## Source References

- [Documentation Index](../00_README.md)
- [Architecture](../../ARCHITECTURE.md)
- [Technical Specification](../01_Technical_Specification.md)
- [API Specification](../03_API_Specification.md)
- [UI Component Tree](../05_UI_Component_Tree.md)
- [Requirements Clarifications](../REQUIREMENTS_QUESTIONS.md)
- [Schema Reference](../schema/README.md)

## Recommended Build Sequence

### Phase 1 - First Release Foundation

1. [Project Foundation and Dev Environment](01-project-foundation-and-dev-environment.md)
2. [CI/CD, Staging, Production, and Operations](02-ci-cd-staging-production-operations.md)
3. [Authentication, 2FA, and Session Security](03-authentication-2fa-and-session-security.md)
4. [User Roles, Permissions, and Admin Management](04-user-roles-permissions-and-admin-management.md)
5. [Project Setup, BOQ, and Team Assignment](05-project-setup-boq-and-team-assignment.md)
6. [App Shell, Navigation, and Responsive Layout](06-app-shell-navigation-and-responsive-layout.md)
7. [Supervisor Site Update Flow](07-supervisor-site-update-flow.md)
8. [Engineer Daily Report Flow](08-engineer-daily-report-flow.md)
9. [Daily Report Approval, Rejection, and History](09-daily-report-approval-rejection-and-history.md)
10. [Report PDF Export and Email Delivery](10-report-pdf-export-and-email-delivery.md)
11. [Photo and Attachment Upload Management](11-photo-and-attachment-upload-management.md)
12. [Document Upload, Versioning, and Approval](12-document-upload-versioning-and-approval.md)
13. [Basic Notifications and Alerts](13-basic-notifications-and-alerts.md)
14. [Operational Dashboard Summary](14-operational-dashboard-summary.md)
15. [Audit Log and Download Tracking](15-audit-log-and-download-tracking.md)
16. [Seed Data, UAT, and Launch Readiness](16-seed-data-uat-and-launch-readiness.md)

### Phase 2 - Workflows, Inventory, and Finance

17. [Generic Approval Engine, Delegation, and Escalation](17-generic-approval-engine-delegation-and-escalation.md)
18. [Inventory Catalog, Locations, and Stock](18-inventory-catalog-locations-and-stock.md)
19. [Material Request, Reservation, and Issue Flow](19-material-request-reservation-and-issue-flow.md)
20. [Inventory Movements, Returns, Transfers, and Low Stock](20-inventory-movements-returns-transfers-and-low-stock.md)
21. [Supplier Management and Compliance](21-supplier-management-and-compliance.md)
22. [Accounts, Invoices, Payments, and Budget Tracking](22-accounts-invoices-payments-and-budget-tracking.md)

### Phase 3 - Analytics, Mobile, and Migration

23. [Advanced Analytics and Management Exports](23-advanced-analytics-and-management-exports.md)
24. [Mobile PWA, Offline Drafts, and Photo Queue](24-mobile-pwa-offline-drafts-and-photo-queue.md)
25. [Data Import Templates and Initial Migration](25-data-import-templates-and-initial-migration.md)

## Implementation Notes

- Implementation must follow `../../ARCHITECTURE.md`: FastAPI routes stay thin, services own business workflows and transactions, repositories own async SQLAlchemy data access, Pydantic V2 serializes responses, React uses Context + TanStack Query, forms use React Hook Form + Zod, files use MinIO metadata plus presigned access, and background work runs through Celery.
- Each story is intentionally small enough to implement, review, and test independently.
- Document management is included in Phase 1 because the clarified requirements require upload, metadata, version history, superseded warnings, and approval before active status in the first release.
- Full material request and inventory operations are Phase 2. Phase 1 dashboard low-stock indicators should be included only if the inventory slice is pulled forward.
- Remaining stakeholder confirmations are captured inside story dependencies instead of being silently decided.
