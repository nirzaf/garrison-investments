# Garrisons portal release scope

This inventory defines the working beta scope for the Garrisons Construction Internal Portal (`launch_readiness_only`, `G-01` excluded). It is an unsigned scope baseline, not a release authorization; its unsigned state does not block unrelated beta iterations. See the [beta release policy](BETA_RELEASE_POLICY.md) and the [optional acceptance ledger](POST_RELEASE_ACTIONS.md).

| Area | Release scope | Source |
| --- | --- | --- |
| Identity | Password and emailed OTP sign-in, session management, voluntary password change and recovery, a read-only profile, and authorized account and role administration | [Authentication routes](../backend/app/api/v1/auth.py), [role matrix](ROLES_AND_PERMISSIONS.md) |
| Projects | Scoped project records, team assignment, BOQ and milestones, task dependencies, and schedule views | [Project routes](../backend/app/api/v1/projects.py), [frontend routes](../frontend/src/App.tsx) |
| Site reporting | Supervisor progress with required photographs, independent QS review where applicable, assigned engineer confirmation, correction history, official daily reports and approved PDFs | [Reporting service](../backend/app/services/report_service.py), [reporting pages](../frontend/src/pages/reports/) |
| Offline and media | Owned drafts, queued uploads and replay, conflict recovery, cumulative photo limits, classified protected media access, and eligible draft-media deletion. The current role policy blocks deleted-media listing and recovery. | [Offline queue](../frontend/src/api/offlineQueue.ts), [photo service](../backend/app/services/photo_service.py) |
| Document control | Search, filters, reasoned classification review, version uploads, approval and activation, and protected current or superseded versions | [Document service](../backend/app/services/document_service.py) |
| Inventory and approvals | Stock and movements by location, supervisor inventory registration with engineer confirmation, staged material requests, partial fulfillment, cancellation, and authorized approval inbox and outbox | [Inventory service](../backend/app/services/inventory_service.py), [approval service](../backend/app/services/approval_service.py) |
| Site attendance | Assigned worker attendance, Site Engineer review, HR verification, reasoned discrepancy corrections, frozen factual arrival indicators, and verified payroll time inputs | [Site attendance service](../backend/app/services/hr_site_attendance_service.py), [HR workforce](HR_WORKFORCE.md) |
| HR leave and celebrations | Employee leave requests use a current direct supervisor as final reviewer, with an audited HR fallback and portal/email notifications. Reviewed managed annual/casual profiles support service-year entitlements, opening-balance reconciliation, and no carry-forward. The dashboard shows names and month/day for birthdays within seven days and completed service years for anniversaries within 30 days. Leave policy values and opening balances require HR review before activation; sick and maternity rules remain to be supplied. | [HR workforce guide](HR_WORKFORCE.md), [leave accrual service](../backend/app/services/hr_leave_accrual.py), [dashboard service](../backend/app/services/dashboard_service.py) |
| Suppliers and finance | Supplier compliance and TDS, restricted supplier options, and authorized reads of invoices, recorded payments and budget summaries. The current role policy blocks finance writes. | [Supplier routes](../backend/app/api/v1/suppliers.py), [finance service](../backend/app/services/finance_service.py) |
| Analytics and import | Scoped dashboards, filtered XLSX/PDF exports, and approved-format data and metadata imports | [Analytics routes](../backend/app/api/v1/analytics.py), [import templates](import_templates/README.md) |
| Guidance and operations | Role manuals, notifications, security and audit views, and Launch readiness at the existing management-only `/delivery` route | [Portal manuals](../frontend/src/pages/manual/), [Launch readiness](../frontend/src/pages/delivery/DeliveryPlanPage.tsx), [operations runbook](OPERATIONS_AND_DEPLOYMENT.md) |

The working scope is `launch_readiness_only`. Logistics scheduling, fleet and vehicle management, delivery booking, dispatch and routing, and stock posting from a delivery workflow require a separately approved product increment. Inventory receipts and stock movements remain within the existing stores workflow.

G-01, mandatory password-change enforcement, is excluded. Existing voluntary password change, password reset, and authentication remain in scope. Verify monitoring, recovery, retention, and deployment components when a change touches them or the applicable technical runbook requires it; comprehensive operational acceptance is not a gate for every beta feature release.

## Portal System Requirements gap review

Scope and status below refer to sections 2–14 of the 23 November 2026 PDF
requirements and the corresponding local gap-closure work.

| PDF section | Implementation | Primary evidence |
| --- | --- | --- |
| 2 and 10 · Role scope | Ten business roles. Site supervisors submit for assigned projects, assigned MEP Project Managers provide technical reviews, assigned Quantity Surveyors verify measurements, and HR Managers check attendance. | [Role rules](ROLES_AND_PERMISSIONS.md#authorization-rules), [authorization tests](../backend/tests/test_authorization_matrix.py) |
| 3 and 7 · Daily progress and QS | Supervisor submissions retain structured progress and photos. Required QS review precedes technical confirmation. Management totals include technically confirmed reviews. | [Supervisor service](../backend/app/services/reporting_service.py), [progress tests](../backend/tests/test_supervisor_updates.py), [report browser regression](../frontend/e2e/daily-report.e2e.ts) |
| 4 and 8 · Material workflow | Site Engineer verification then Group Project Manager approval bind to an immutable submission revision. Correction restarts the sequence. Authorized stock processing uses a separate operational revision. Incomplete line valuation remains unknown, and the submission freezes that state with any required director stages. When configured thresholds are met, Operations Director and Managing Director stages follow GPM approval. | [Inventory service](../backend/app/services/inventory_service.py), [approval service](../backend/app/services/approval_service.py), [inventory tests](../backend/tests/test_inventory.py) |
| 5 · Inventory registration | Supervisors stage materials, tools and equipment with photographs. Authorized engineer approval records confirmed inventory and a single stock receipt in one transaction. | [Registration service](../backend/app/services/inventory_registration_service.py), [inventory tests](../backend/tests/test_inventory.py) |
| 6 · Attendance | Assigned worker attendance progresses through engineer and HR decisions. Reasoned corrections preserve history. A resolvable published schedule produces a frozen factual arrival variance without a grace rule or payroll deduction. Payroll preparation checks the current submitted version for both decisions. | [Site attendance service](../backend/app/services/hr_site_attendance_service.py), [attendance tests](../backend/tests/test_site_attendance.py) |
| 9 · Financial access | Directors have company-wide financial reads. Group Project Managers have assigned-project financial reads. Financial mutations and company-wide cost tools retain their own authorization boundaries. | [Role rules](ROLES_AND_PERMISSIONS.md#authorization-rules), [finance tests](../backend/tests/test_finance.py), [analytics tests](../backend/tests/test_analytics.py) |
| 11 and 12 · Status, audit and control | Site workflows show pending stages and decisions, notify responsible actors, and preserve corrections with actor and timestamp. Scoped dashboards distinguish pending from confirmed activity. | [Architecture](ARCHITECTURE.md#approvals-inventory-and-finance), [business-role browser cases](../frontend/e2e/business-roles.e2e.ts) |
| 13 and 14 · Operational outcome and constraints | Separate workflows use the existing roles and PostgreSQL transactions. Release and production verification are recorded against the deployed SHA. New approval categories or thresholds need an approved policy. | [Schema index](schema/README.md), [deployment procedure](OPERATIONS_AND_DEPLOYMENT.md#fast-beta-release-path) |


### November 24 PDF follow-up

- MEP Project Managers can start unpriced Planning projects with milestones.
  Budget and initial BOQ pricing are director-only. The HR Executive report
  grant is removed in code per PDF §10. Owner sign-off remains pending under
  [D11](BUSINESS-ROLE-DECISIONS.md#decision-register).
- Overdue staged material approvals notify Operations Directors once. Directors
  can read the flagged approvals while the assigned engineer and Group Project
  Manager retain authority over their assigned stages. Optional Operations and
  Managing Director decisions require configured thresholds, which default to disabled.
  The submission freezes its required stages. Stock fulfillment requires a distinct
  approved decision for each frozen stage. Intermediate notices identify the next stage.
- Site attendance shows eligible, recorded, missing and independently confirmed
  workers. Missing required site attendance and unreconciled site overtime block
  payroll time preparation. Findings identify the project and work date. Historical
  eligibility uses recorded employment dates and effective assignments. Unresolved
  employment dates require review. [HR workforce guide](HR_WORKFORCE.md#site-attendance)
- Approved progress corrections preserve the original and run independent reviews
  on the successor. The latest independently confirmed version of an unlinked
  chain can be included in an official report. A chain with an existing binding
  keeps that report and its PDF. Inventory registration corrections preserve item
  identity and post only the necessary stock delta. Supervisors can save and resume
  material requests and corrections with revision checks. Correction drafts retain
  new evidence separately until submission, while earlier evidence stays linked
  to its original submission revision. Stock-bearing material corrections use the director's
  unissued-remainder replacement action.
- Historical inventory and attendance findings can be inspected with the
  [read-only reconciliation report](../backend/scripts/report_legacy_site_workflows.py).
- Reasoned historical site-attendance exceptions use effective employment and
  project-assignment evidence, retain both review stages, and continue to honor
  locked timesheet periods. Unknown material valuations remain null and are
  reported for manual review.
- Documents and uploaded media use explicit, audited classifications. New uploads
  default to restricted `unclassified`; the uploader can declare operational
  evidence, while contracts and invoices are always financial. Unclassified and
  financial metadata, previews and new download URLs require the existing scoped
  `financial:view` grant. Non-financial depositors receive an opaque receipt.
  Existing signed URLs remain usable until expiry. A read-only report identifies
  unclassified legacy evidence for manual review.
