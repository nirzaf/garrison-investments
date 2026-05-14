# Construction Internal Portal - Requirements Questions

This document lists the business, operational, and technical questions that should be clarified before full implementation. The current documentation provides a strong technical foundation, but these decisions affect database design, API behavior, UI flows, deployment planning, and long-term maintainability.

## 1. Project Scope and Phase Priority

The WBS splits the system into Phase 1 (daily reporting), Phase 2 (materials/workflows/documents), and Phase 3 (accounts/analytics/mobile enhancements). Clarify this first because it affects timeline, budget, and what "complete" means.

**Questions to ask:**

- Is Phase 1 only the first deliverable, or should the full Phase 1–3 system be built now?
- Which modules are mandatory for the first release: daily reports, dashboard, photos, projects, users, approvals, materials, documents, notifications, accounts?
- Should "MVP" mean a working internal portal for real use, or just a demo/prototype?
- Are material requests and approvals required in Phase 1, or only from Phase 2?
- Are documents and version control required in the first release, or later?
- Accounts integration is listed in Phase 3, but the Accounts role already exists. What should the Accounts Department be able to do before Phase 3?
- Is the estimated total schedule of around 70.5 development days / 14 weeks acceptable, or does the client expect a shorter timeline?
- Which features can be removed or delayed if time or budget becomes limited?
- Who has final authority to approve scope changes?

## 2. User Roles and Permissions

The documents define roles such as Admin, Operation Manager, Project Manager, Civil Engineer, Civil Supervisor, Store Keeper, and Accounts. The technical specification also includes an RBAC matrix. However, some permissions need exact confirmation.

**Questions to ask:**

- Can one user have multiple roles, or exactly one role only?
- Can a Project Manager access only assigned projects, or all projects?
- Can Civil Engineers and Civil Supervisors see reports submitted by others on the same project?
- Can Civil Supervisors submit daily reports? The RBAC matrix suggests they can submit their own reports, but the API specification says report submission is for Engineers. This needs clarification.
- Can Store Keepers see project reports, or only material/inventory screens?
- Can the Accounts Department see project budgets, invoices, reports, materials, or only financial documents?
- Should Operation Managers approve all reports, or only reports escalated from Project Managers?
- Can Admins edit or delete approved reports?
- Should users be deactivated only, or permanently deleted in rare cases?
- Should permission rules be hardcoded by role, or should Admins be able to customize permissions later?

## 3. Daily Site Report Requirements

Daily reporting is the core of the portal. The requirement document lists project, weather, work completed, manpower, equipment, materials, issues, photos, and next-day plan. The API and database define draft, submitted, approved, and rejected states.

**Questions to ask:**

- Is there exactly one daily report per project per day, or can there be multiple reports per project, site, zone, shift, or supervisor?
- Who is responsible for submitting the official daily report?
- Can multiple people contribute to the same draft report?
- Can a report be edited after submission?
- Can a report be edited after approval?
- If a report is rejected, does it return to draft status or rejected status?
- Should approval history be visible inside the report?
- Is progress percentage entered manually, automatically calculated, or both?
- Should progress percentage be validated so it cannot go backward?
- Are safety incidents required in every report?
- Are site visitors, inspections, WIR numbers, subcontractors, or delays mandatory fields?
- Is weather manually entered, selected from a dropdown, or fetched automatically from a weather service?
- Should reports support attachments other than photos?
- Should daily reports be printable as PDF?
- Should reports have a unique report number?
- Should the system prevent future-dated reports?
- Should users be able to submit reports for previous dates?
- Are weekends and holidays handled differently?
- Should late report submission trigger an alert?
- What is the exact approval flow for a daily report?

## 4. Approval Workflow

The system includes approval workflows for reports, material requests, and documents. The approval model supports generic request types and multi-level approval.

**Questions to ask:**

- Which items require approval: daily reports, material requests, documents, invoices, payments, project changes?
- Is approval single-level or multi-level?
- What is the approval chain for each item type?
- Can the approver be selected manually, or is the approver determined automatically by project/role?
- Can an approver delegate approval to someone else?
- What happens if an approver is inactive or unavailable?
- Is a rejection reason mandatory?
- Can an approved item be reopened or revised?
- Should approval deadlines or escalation rules exist?
- Should users receive notifications when approval is pending, approved, or rejected?
- Should Admins be able to override approvals?
- Should approval comments be visible to all users or only managers?

## 5. Material Management and Inventory

The requirement includes material requests, approvals, stock tracking, incoming/outgoing materials, suppliers, and low-stock alerts. The database has materials, suppliers, and material transactions, but there is no clearly defined separate material_requests table even though approvals mention material_request.

**Questions to ask:**

- Is a separate material request workflow required, or only direct stock in/out transactions?
- Who can create material requests?
- Who approves material requests?
- Should material requests reserve stock before issue?
- Should stock be tracked globally, by project, by site, by store, or by warehouse?
- Can one material exist in multiple locations?
- Do materials need batch numbers, delivery notes, purchase order references, or supplier invoice references?
- Should outgoing materials be linked to a daily report?
- Should material consumption in daily reports automatically reduce stock?
- Can stock go negative?
- How should returns, wastage, damaged materials, transfers, and adjustments be handled?
- Should the system track unit conversions, such as bags to kilograms or tons to kilograms?
- Who sets minimum stock and reorder points?
- Should low-stock alerts go to Store Keeper only, or also Project Manager/Operation Manager?
- Are supplier ratings, supplier categories, or payment terms needed?
- Should material pricing be visible to all users or restricted?

## 6. Project Management and Timeline Tracking

The documents include project list, detail, timeline, project members, progress tracking, and dashboard summaries. The UI tree also includes project timeline and Gantt-style views.

**Questions to ask:**

- What data is required when creating a project?
- Is project code manually entered or auto-generated?
- Do projects have phases, milestones, activities, or BOQ line items?
- Should the timeline be a simple date range, or a full task/Gantt tracker?
- How is project progress calculated?
- Can progress be different for civil, MEP, finishing, and other scopes?
- Should the dashboard show the project budget and cost?
- Are project locations plain text, maps, GPS coordinates, or all three?
- Should clients have access later through the future client portal?
- Can users be assigned to multiple projects?

## 7. Photo Upload and Gallery

The plan requires daily site photo uploads, direct camera upload, gallery, and progress archive. The API supports photo upload, metadata, thumbnails, download, and soft deletion.

**Questions to ask:**

- How many photos can be uploaded per report?
- Is the 10 MB per-file limit acceptable?
- Which formats are allowed: JPG, PNG, HEIC, PDF?
- Should photos be compressed automatically?
- Should thumbnails be generated automatically?
- Should photos include captions?
- Should users be allowed to delete photos after report submission?
- Should deleted photos remain recoverable by Admin?
- Should photos be watermarked with project name, date, user, or location?

## 8. Document Management

The requirement includes drawings, BOQ, contracts, WIR, invoices, version control, approval workflow, search, and filters. The database and API define document types, versions, search, upload/download, and metadata.

**Questions to ask:**

- Which document types are required in the first release?
- Are document approvals required before a document becomes active?
- Who can upload drawings, BOQs, contracts, WIRs, and invoices?
- Who can view financial documents such as invoices and contracts?
- Should old document versions remain downloadable?
- Should users be warned when viewing superseded drawings?
- Should document numbers, revision numbers, and approval statuses follow a company standard?
- Should documents be linked to projects only, or also to reports/materials/approvals?
- Should document search include file contents, or only titles and metadata?
- What is the maximum file size for documents?
- Are PDF previews required inside the browser?
- Should document expiry dates or renewal reminders be supported?

## 9. Dashboard and Analytics

The API defines dashboard summary, project progress, material usage, approval stats, and export endpoints. The UI tree includes stat cards, recent activity, project progress charts, and pending approval widgets.

**Questions to ask:**

- What KPIs should appear on the main dashboard?
- Should dashboard data be company-wide or role-scoped?
- What should each role see on their dashboard?
- Should dashboard numbers update live, every few minutes, or only on refresh?
- What charts are required for Phase 1?
- Should managers see delayed projects, missing reports, low stock, pending approvals, manpower totals, and material usage?
- Should dashboard filters include project, date range, location, and department?
- Are exports to Excel/PDF required in Phase 1 or Phase 3?
- What exact format is required for management reports?
- Should reports match an existing company template?

## 10. Notifications and Alerts

Notifications are part of the planned system and have their own API. The technical specification includes Celery workers for email service and background tasks.

**Questions to ask:**

- Which notifications are required: report submitted, report approved, report rejected, low stock, late report, new document, approval pending?
- Should notifications be in-app only, email only, or both?
- Who receives each notification type?
- Should users be able to mute notifications?
- Should notification history be kept forever?
- Should reminders be sent for pending approvals?
- Should unread notification count be shown in the header?

## 11. Mobile and Offline Behavior

The requirement mentions responsive mobile design, camera upload, offline draft saving, and fast loading. The technical specification describes a PWA with service worker, IndexedDB, background sync, and camera capture. But the WBS places major PWA/mobile enhancements in Phase 3. This is a key ambiguity.

**Questions to ask:**

- Is offline draft saving required in Phase 1, or can it wait until Phase 3?
- Is the app expected to work fully offline, or only save draft reports offline?
- Should photo uploads work offline?
- Should material transactions work offline?
- Which devices must be supported: Android phones, iPhones, tablets, desktop?
- Which browsers must be supported?
- Should the mobile version have the same features as desktop?
- What is the minimum acceptable performance on mobile networks?
- Are field users expected to use low-end phones?
- Should forms autosave while the user is typing?

## 12. Accounts and Financial Features

The Accounts role is included in the role list, and Phase 3 includes invoice tracking, payment status, OCR placeholder, and budget-vs-actual reporting.

**Questions to ask:**

- What exactly should the Accounts Department do in the system?
- Are invoices only documents, or should invoice data be structured in database fields?
- Should payment status be tracked?
- Should account users approve invoices?
- Should material purchases connect to invoices?
- Should project budget vs actual cost be calculated?
- Is integration with accounting software required?
- Are financial values visible to Project Managers?
- Is OCR actually required, or only a future placeholder?
- What financial reports are required?

## 13. Data Model and Business Rules

The database schema is detailed and includes users, projects, reports, manpower, equipment, materials, suppliers, photos, documents, approvals, notifications, and audit logs. Some business-level rules still need confirmation.

**Questions to ask:**

- Should employee codes be mandatory?
- Should phone numbers be mandatory?
- Are project codes unique, and should they be manually entered or auto-generated?
- Are material codes mandatory?
- Are supplier records required before creating materials?
- Should all records use soft delete, as currently planned?
- How long should deleted records remain recoverable?
- Should audit logs record every view/download action, or only create/update/delete/login/approve?
- Should audit logs be visible only to Admin?
- Are there data retention rules for reports, photos, documents, and logs?
- Should old projects be archived?
- Should inactive users still appear in historical reports?
- Should the system support multiple companies or branches later?

## 14. API and Integration Requirements

The API specification defines `/api/v1`, auth endpoints, CRUD modules, pagination, soft deletes, exports, and common error format.

**Questions to ask:**

- Will any external systems integrate with this API?
- Is API access only for the web app, or also for future mobile/native apps?
- Are webhooks required?
- Is there any existing ERP, accounting, HR, attendance, or inventory system to connect later?
- Should API responses be in English only?
- Should the API support Arabic or other localized field values?
- What are the required pagination defaults and maximum limits?
- Should bulk import/export APIs be required?
- Should file upload use direct API upload or presigned MinIO/S3 URLs?
- Should API rate limits vary by role?

## 15. UI/UX and Branding

The UI component tree defines routing, layout, reusable components, reports, materials, documents, approvals, notifications, and admin screens.

**Questions to ask:**

- Is there an existing company logo, brand color, typography, or design standard?
- Should the portal support dark mode now or later?
- Should the UI be English only, or bilingual?
- Is Arabic / right-to-left layout required?
- Should forms match existing paper forms used on site?
- Should users be able to print forms exactly like company templates?
- Are there required dashboard mockups?
- Should the system be optimized more for desktop office users or mobile site users?
- Should tables support column customization?
- Should users be able to save filters?
- What fields are mandatory on each form?
- What validation messages and error handling style should be used?

## 16. Security, Compliance, and Access Control

The technical specification includes JWT auth, refresh rotation, password policy, rate limiting, CORS, secure headers, file upload restrictions, optional virus scan, audit logging, and daily backups.

**Questions to ask:**

- Is email/password login enough, or is two-factor authentication required?
- Who creates user accounts?
- Should users be forced to change password on first login?
- What is the password reset process?
- Should login be restricted by company network/IP?
- How many failed login attempts should lock an account?
- How long should sessions remain active?
- Is the proposed 15-minute access token and 7-day refresh token acceptable?
- Which file types should be blocked?
- Should downloads be logged?
- Where should backups be stored?
- How often should backups be tested?

## 17. Deployment, Hosting, and Operations

The system is designed with Docker, Nginx, PostgreSQL, Redis, MinIO, Celery, and Open Observe monitoring.

**Questions to ask:**

- Where will the system be hosted: company server, cloud server, or local office server?
- Who will manage the server after launch?
- Is internet access available reliably at construction sites?
- What backup retention period is required?
- Should monitoring dashboards be implemented in Phase 1 or later?
- Who receives system error alerts?
- Are staging and production environments required?
- Should deployment be manual or automated through GitHub Actions?

## 18. Testing and Acceptance Criteria

The WBS includes backend, frontend, integration, smoke, cross-device, performance, and regression testing. But acceptance criteria need to be defined by the client.

**Questions to ask:**

- Who will perform user acceptance testing?
- What exact scenarios must pass before launch?
- What is the definition of "done" for Phase 1?
- Is 80% backend test coverage required, as suggested in the WBS?
- Which browsers and devices must be tested?
- Should testing include low internet speed conditions?
- Should sample users and sample projects be included for testing?
- Should the client approve UI screens before development?
- Should each module require sign-off before moving to the next phase?
- What bugs are considered launch blockers?

## 19. Data Migration and Initial Setup

The README mentions seed data and sample users. Real deployment will need initial company data.

**Questions to ask:**

- Is there existing data to import?
- Are users currently stored in Excel, HR software, or another system?
- Are projects, suppliers, materials, and documents already available in spreadsheets?
- Should material opening stock be imported?
