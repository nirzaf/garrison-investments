# Construction Internal Portal - Requirements Questions

This document lists the business, operational, and technical questions that should be clarified before full implementation. The current documentation provides a strong technical foundation, but these decisions affect database design, API behavior, UI flows, deployment planning, and long-term maintainability.

## 1. MVP Scope & Product Direction

1. What is the exact MVP scope: Phase 1 only, or should parts of materials, approvals, documents, and accounts be included from day one?
2. Who will use the system first: office/admin users, site engineers, supervisors, store keepers, or all roles?
3. Should the first version be a real full-stack application, or should the current static blueprint become a clickable demo first?
4. What company branding is required: logo, colors, language, app name, and domain?
5. Is Arabic required in the first release, or English-only?
6. Should dates and times use Qatar timezone? The API examples should be aligned with the intended business timezone.

## 2. Roles, Permissions & Access Scope

1. For each role, what can they view, create, edit, approve, delete, and export?
2. Can project managers see all projects or only assigned projects?
3. Can civil engineers and supervisors edit reports after submission?
4. Can store keepers see project reports, or only materials and inventory?
5. What exactly can the Accounts Department do in Phase 1, if anything?
6. Should project access be based only on role, or on explicit project membership?
7. Can users be assigned to multiple projects at the same time?

## 3. Daily Reports

1. Is there exactly one daily report per project per day, or can there be multiple reports per day per project, site, shift, or supervisor?
2. Who is allowed to submit reports: civil engineer only, supervisor only, or both?
3. What fields are mandatory for a report?
4. Should progress percentage update the project progress automatically?
5. What happens if a submitted report is rejected: edit the same report, duplicate it, or create a revision?
6. Are signatures required for daily reports or approvals?
7. Can a user submit reports for more than one project on the same day?

## 4. Approval Workflows & Routing Logic

1. Are approvals strictly sequential, or can multiple approvers approve in parallel?
2. What is the required approval chain for each item type: daily report, material request, document, invoice, and stock adjustment?
3. If an item is rejected, does it return to editable draft state, stay rejected with resubmission allowed, or require a new submission?
4. Should rejection always require a reason?
5. Does the system need approval delegation for vacations, out-of-office users, or unavailable managers?
6. Can admins override, reassign, or force-approve pending approval requests?
7. Should approval history be immutable and visible to all project members, or only managers and admins?
8. Should approvals expire or escalate after a time limit?
9. Can one approver approve on behalf of another?

## 5. Inventory & Material Tracking Boundaries

1. Is inventory centralized for the company, separated by project/site, separated by warehouse, or a mix of these?
2. If stock is site-specific, should the system support site-to-site or warehouse-to-site transfers?
3. Should material consumption in daily reports automatically reduce stock, or should storekeepers confirm stock movement separately?
4. Should materials support unit conversion, such as purchase in tons but consumption in pieces, bags, bundles, or cubic meters?
5. Who can adjust stock manually, and should manual adjustments require approval?
6. Should low-stock alerts be instant, daily summaries, or both?
7. Who receives low-stock alerts: storekeeper, project manager, operation manager, or admin?
8. Are material requests part of MVP or Phase 2?
9. What units are allowed, and should unit conversion be enforced by the system or handled manually by storekeepers?

## 6. Photo Uploads & Media Handling

1. What file types and max file sizes are allowed for photos?
2. Should photos require captions, location, timestamp, or uploader metadata?
3. Should uploaded files be private per role, per project, or visible to all authenticated users?
4. Should uploaded photos be compressed automatically?
5. Should the system keep original high-resolution photos, optimized photos, thumbnails, or all three?
6. If photos fail to sync, is the report allowed to be submitted without them, or should submission stay pending?
7. What is the expected number of photos per project per month?

## 7. Offline Synchronization & Mobile PWA Edge Cases

1. Should offline support be included in MVP, or postponed to a later phase?
2. Should offline sync upload report text first and photos later in a background queue?
3. If two users create offline reports for the same project and date, should the second sync be rejected, merged, or converted into a revision?
4. Should users be warned before creating an offline draft if another report may already exist for that project/date?
5. How long should offline drafts be stored on the device?
6. Should offline drafts be encrypted locally on the device/browser?
7. Which devices must be tested: iPhone Safari, Android Chrome, tablets, desktop?
8. Should offline mode support only draft reports, or also photos and reference data?

## 8. Document Control & Visibility Scope

1. Is document versioning required in the first release?
2. When a new document version is uploaded, should old versions be hidden from field staff or visible with a clear superseded label?
3. Which roles can upload, replace, approve, archive, or delete documents?
4. Should document version history be visible to all project members or only managers/admins?
5. What file types are allowed: PDF, image, Excel, Word, DWG/CAD, ZIP?
6. Are CAD/DWG files only stored for download, or should the app preview them?
7. Should documents require metadata such as project, document type, revision number, discipline, status, and approval state?
8. Should the app preview PDFs/images in-browser or only download them?

## 9. Multi-Project User Assignments

1. On mobile, should users select an active project first, or see an aggregated dashboard across all assigned projects?
2. Should the app remember the user's last selected project?
3. Should report, material, photo, and document forms always require an active project context?
4. If a user belongs to multiple projects with different responsibilities, should their permissions change per project?

## 10. Notifications & Alerts

1. Are notifications in-app only, email only, or both?
2. Which events should trigger notifications?
3. Are SMS or WhatsApp notifications required later?
4. Should low-stock alerts dispatch immediately when stock crosses the reorder point, or be compiled into a daily summary?
5. Should pending approvals trigger reminders or escalation notifications?

## 11. Accounts, Financials & Reporting

1. Is Accounts Department functionality required in MVP, or only in Phase 3?
2. What account-related records must be tracked: invoices, payments, purchase orders, budget, actual costs, or all of these?
3. Should financial data be visible to project managers, operation managers, admins, or only accounts users?
4. Are reports exported to PDF or Excel required in MVP?
5. What financial summaries are required for management dashboards?

## 12. Infrastructure, Deployment & Storage Lifecycle

1. Where will this be hosted: company VPS, cloud provider, local office server, or another environment?
2. Is Docker Compose enough for production, or are managed services expected?
3. Who manages backups, SSL, email SMTP, server access, and monitoring?
4. What is the expected number of users, projects, photos, documents, and reports?
5. Should the backend automate an archival policy after a project is completed?
6. Should completed-project files become read-only?
7. Are backups required daily, weekly, or in real time?
8. How long should backups and audit logs be retained?
9. Is there a legal or contractual requirement for retaining project documents/photos?
10. Should media be migrated to cold storage or compressed after project completion?

## 13. Security, Audit & Compliance

1. Are audit logs legally or operationally required for all changes?
2. Which actions must be audited: login, report changes, approvals, uploads, stock movements, user management, or all critical actions?
3. Should users be locked after failed login attempts?
4. Is two-factor authentication required for admins or managers?
5. Should files have expiring download URLs?
6. Are there any data residency or client confidentiality requirements?

## 14. Acceptance Criteria & Launch Readiness

1. What does "done" mean for Phase 1?
2. Which user journey must work perfectly for launch? Example: login -> create daily report -> upload photos -> submit -> approve -> dashboard updates.
3. Do they need sample seed data and demo users?
4. Who will approve the final UI and business workflow?
5. What test coverage or QA process is required before launch?
6. What browsers and devices must be supported at launch?
7. What production support process is expected after release?

## Highest-Priority Decisions

The most important questions to answer before implementation are:

1. MVP scope.
2. Role permissions and project access rules.
3. Approval sequencing and rejection lifecycle.
4. Inventory scope and stock movement behavior.
5. Offline sync conflict handling.
6. Document version visibility.
7. Multi-project context switching.
8. Media storage, compression, retention, and archival policy.
9. Hosting and deployment target.
10. Phase 1 acceptance criteria.
