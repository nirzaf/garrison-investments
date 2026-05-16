# Garrisons Internal Portal - Requirements Clarifications

Source: `Garrisons Internal Portal - Requirements Questions.docx`

This document updates the original requirements-question checklist with the answers provided in the stakeholder document and recommended implementation decisions for previously unanswered items. Items marked as remaining follow-up still need client assets, source data, or final stakeholder confirmation.

## 1. Project Scope and Phase Priority

### Confirmed Decisions

- The MVP must be a working internal portal for real use, not only a prototype.
- Material requests and approvals can wait until Phase 2.
- Documents and version control are required in the first release.
- Before Phase 3, Accounts must support manpower cost calculation, material cost calculation, and budget tracking.
- Timeline planning should be project-wise rather than a fixed global 14-week schedule.
- Initial delivery can avoid full dashboard and secondary features. The task update/reporting flow is the priority.
- Scope changes must be approved by the Operation Manager and General Manager.
- First release should include users/auth, projects, supervisor updates, engineer verification/reporting, Project Manager approval, photos, document upload/versioning, basic notifications, and basic exports.
- First-release document/version control should include upload, metadata, version history, superseded warnings, and approval before active status.
- Advanced dashboards should be postponed. Launch should include only operational summaries: pending approvals, missing/late reports, active projects, recent updates, and low-stock indicators if materials are included.

### Remaining Follow-Up

- Final stakeholder sign-off on the recommended first-release module list.
- Confirm whether material request screens are fully postponed to Phase 2 or need read-only placeholders in Phase 1.

## 2. User Roles and Permissions

### Confirmed Decisions

- A user has exactly one role.
- Project Managers can currently access all projects. In the future, assignment can become project-wise.
- Civil Engineers and Civil Supervisors can see reports submitted by others on the same project, but cannot edit them.
- Civil Supervisors do not submit the final daily report. They update attendance, work location, overtime details, and progress.
- Civil Engineers visit/check the site quality, approve the supervisor update in the system, and then add the engineer report/update.
- Store Keepers can access only material/inventory screens.
- Everyone can request material, but requests must go through final approval.
- Accounts can see all project budgets, invoices, reports, and materials.
- Operation Managers approve only items escalated from Project Managers.
- Admins cannot edit or delete approved reports.
- Users should be deactivated/renamed/reassigned rather than permanently deleted. Historical continuity should remain in the portal.
- Admins should be able to customize permissions later.
- MVP should use fixed role-based permissions, while the database design should allow customizable permissions later.
- Employee replacement should not rename or overwrite old users. The old user should be deactivated and a new user created. Historical reports, approvals, and audit logs must keep the original user reference.
- MVP roles should include Admin, General Manager, Operation Manager, Project Manager, Civil Engineer, Civil Supervisor, Store Keeper, and Accounts.

### Remaining Follow-Up

- Define exact role permissions for every module and action.
- Confirm whether General Manager needs full read-only visibility or approval authority in selected workflows.

## 3. Daily Site Report Requirements

### Confirmed Decisions

- Multiple reports per project are allowed.
- The official daily report is submitted by the Civil Engineer.
- Multiple users cannot contribute to the same draft report.
- After submission, only the submitting user can edit, subject to workflow rules.
- Approved reports cannot be edited. Any change requires resubmission or an admin delete/change request.
- Rejected reports return to draft, but rejection comments must remain visible in history.
- Approval history must be visible inside the report.
- Progress percentage can be both manual and calculated from the engineer report.
- Progress may go backward depending on the situation, so backward movement should not be blocked globally.
- Safety incidents are required in every report.
- Site visitors, inspections, WIR numbers, subcontractors, and delays are mandatory fields.
- Weather should support both manual entry/dropdown selection and automatic weather data.
- Reports should support attachments beyond photos.
- Daily reports must be printable as PDF.
- After approvals, the daily report PDF should be emailed.
- Reports must have a unique report number.
- Future-dated reports are allowed.
- Previous-date reports are not allowed by default, but can be submitted with admin approval.
- Weekends and holidays are handled differently.
- Late report submission should trigger an alert.
- Daily report approval must confirm that the target was covered and must be approved by the Project Manager.
- The official report is the final Civil Engineer report approved by the Project Manager.
- Supervisor updates are report inputs, not the official daily report.
- Weekend/holiday reports should be allowed, but the day type should be marked. Lateness checks should be skipped unless work was scheduled for that day.
- Late cutoff should default to 10:00 AM the next day. Notify the submitter first, then notify the Project Manager if still missing.
- Report number format should be `PROJECTCODE-DR-YYYYMMDD-###`.
- Required fields should include project, date, work area/location, manpower, overtime, work completed, progress, safety incidents, WIR/inspection status, delays, next-day plan, photos, and attachments.

### Remaining Follow-Up

- Confirm whether 10:00 AM next-day cutoff matches site operations.
- Confirm any additional company-specific daily report fields from existing paper forms.

## 4. Approval Workflow

### Confirmed Decisions

- Daily reports, material requests, documents, invoices, payments, and project changes require approval.
- Approval is multi-level where needed.
- Project-related work is approved by the Project Manager once the project is entered.
- Material and related approvals are two-step: first Engineer approval, final Project Manager approval.
- Work completion reports should be approved by the Engineer and finally by the Project Manager.
- Approvers are determined automatically by project/role.
- Approval delegation is required.
- If an approver is inactive or unavailable, Admin controls reassignment/handling.
- Rejection reason/comment is mandatory.
- Approved items cannot be reopened or revised.
- Approval deadlines and escalation rules are required.
- Timely activities should include increment/score points.
- Users must receive notifications for pending, approved, and rejected approvals.
- Admins can override approvals.
- Approval comments are visible only to managers.
- Recommended approval chains:
  - Daily report: Supervisor update -> Civil Engineer verification/report -> Project Manager approval.
  - Material request: requester -> Engineer review -> Project Manager approval -> Operation Manager approval if above USD 1,000.
  - Documents: uploader -> Project Manager approval before active status.
  - Invoices/payments: Accounts review/create -> Operation Manager approval.
- Escalation should send a reminder after 24 hours and escalate after 48 hours.
- Admin overrides and delegated approvals must be fully audited with reason, timestamp, original approver, and acting user.

### Remaining Follow-Up

- Define whether Operation Manager approval is needed for specific high-risk/non-material items.
- Define scoring/increment-point rules for timely activities.

## 5. Material Management and Inventory

### Confirmed Decisions

- A separate material request workflow is required.
- Supervisors, Engineers, and Project Managers can create material requests.
- Admin and Project Manager approve material requests.
- Requests above USD 1,000 require Operation Manager approval.
- Material requests should reserve stock before issue.
- Stock must support both centralized/global and project/site/store/warehouse tracking.
- One material can exist in multiple locations.
- Materials need batch numbers, delivery notes, purchase order references, or supplier invoice references.
- Outgoing materials should be linked to a daily report.
- Material consumption in daily reports should automatically reduce stock.
- Stock cannot go negative.
- Stock alerts are required.
- Returns, wastage, damaged materials, transfers, and adjustments must be handled.
- These material movements should capture the handling person.
- Unit options should be selectable, including Nos, KG, TON, and SQM.
- Minimum stock and reorder points are set by the Store Manager based on requirement.
- Low-stock alerts should go to both Store Keeper and Project Manager/Operation Manager.
- Supplier ratings, supplier categories, and payment terms are required.
- Material pricing is restricted and should not be visible to all users.
- Inventory should use a multi-location model with central warehouse plus project/site stores.
- Transfer transactions should support movement between warehouses, stores, and project/site locations.
- Unit conversion should be configured per material, not globally.
- Material request lifecycle should be requested -> approved -> reserved -> issued, partially issued, or cancelled.
- Material pricing should be visible only to Admin, Accounts, Operation Manager, General Manager, and optionally Project Manager.

### Remaining Follow-Up

- Confirm whether Project Manager can view material pricing.
- Define initial warehouse/site/store list for launch.

## 6. Project Management and Timeline Tracking

### Confirmed Decisions

- Project creation requires scope of work, deadline, and BOQ.
- Project code should be auto-generated.
- Projects have phases, milestones, activities, and BOQ line items.
- New project entry should provide selectable options for phases, milestones, activities, and BOQ line items.
- Timeline should be a full task/Gantt tracker.
- Project progress is calculated from Civil Engineer updates and approved WIR by the Project Manager.
- Progress can be different for civil, MEP, finishing, and other scopes.
- Dashboard does not need to show budget. Deadlines can be shown.
- Project locations only need text and a map image.
- Client portal access is not required.
- Users can be assigned to multiple projects in the initial stage.
- BOQ should support manual entry and spreadsheet import.
- BOQ fields should include item code, description, unit, quantity, rate, amount, discipline, phase, and milestone.
- Gantt/task tracking should support tasks, dependencies, start/end dates, baseline dates, actual dates, delay reason, owner, and status.
- Recommended progress formula: discipline progress = approved quantity divided by planned quantity. Project progress = weighted discipline/BOQ progress.

### Remaining Follow-Up

- Confirm company BOQ spreadsheet format.
- Confirm discipline weights for project progress calculation.

## 7. Photo Upload and Gallery

### Confirmed Decisions

- Maximum 5 photos per report.
- 10 MB per-file limit is acceptable.
- Allowed formats should include JPG, PNG, HEIC, and PDF.
- Photos should be compressed automatically.
- Thumbnails should be generated automatically.
- Captions are not required.
- Photos should be uploaded by the Supervisor.
- Users cannot delete photos after report submission.
- Deleted photos should remain recoverable by Admin.
- Photos should be watermarked with the company name.
- PDFs should be treated as report attachments or documents, not photos.
- Store the original photo, a compressed display version, and a thumbnail.
- Recommended compression: maximum 1920px longest side with JPEG/WebP quality around 75-85.
- Photo metadata should include project, report number, uploader, timestamp, original filename, file size, MIME type, and optional location.

### Remaining Follow-Up

- Confirm whether GPS/location metadata is mandatory or optional.
- Confirm whether HEIC should be converted to JPEG/WebP for browser display.

## 8. Document Management

### Confirmed Decisions

- First-release document types include MAR, MIR, WIR, and delivery notes.
- Documents require approval before becoming active.
- Civil Engineers and Project Managers can upload drawings, BOQs, contracts, WIRs, and invoices.
- Financial documents such as invoices and contracts are visible to Admin, Accounts, Project Manager, and Operation Manager.
- Old document versions remain downloadable.
- Users must be warned when viewing superseded drawings/documents.
- Document numbers, revision numbers, and approval statuses must follow company standards.
- Documents should be linked to projects, reports, materials, and approvals as applicable.
- Document search should include both file contents and titles/metadata.
- Maximum document file size is 60 MB.
- PDF previews are required inside the browser.
- Document expiry dates and renewal reminders are required.
- Recommended document number format: `PROJECTCODE-DOC_TYPE-DISCIPLINE-YYYY-###-REV`.
- CAD/DWG files should be stored and downloadable in MVP. Preview support can be added later.
- Superseded versions should be visible to managers/admins. Field staff should either not see superseded versions or must see a strong superseded warning before download/view.

### Remaining Follow-Up

- Provide company document numbering/revision standards.
- Confirm which field roles, if any, may download superseded versions.

## 9. Dashboard and Analytics

### Confirmed Decisions

- Dashboard KPIs will be decided later.
- Dashboard data should be company-wide.
- Role-specific dashboard content will be decided later.
- Dashboard numbers should update live every few minutes.
- Managers should see delayed projects, missing reports, low stock, pending approvals, manpower totals, and material usage.
- Dashboard filters should include project, date range, location, and department.
- Excel/PDF exports are required in both Phase 1 and Phase 3.
- Management report format should be Excel.
- Reports should use the company's own format. If a client has a required format, the system should allow that template to be uploaded/used.
- Phase 1 KPIs should include pending approvals, late/missing reports, active projects, recent submissions, low stock, and upcoming deadlines.
- Phase 1 charts should include project progress by project, reports submitted by date, and pending approvals by type.
- Export templates should include daily report PDF, project progress Excel, and material usage Excel.
- Company-wide dashboard should be restricted to management roles. Other roles should see scoped dashboards.

### Remaining Follow-Up

- Collect company/client report templates.
- Confirm whether low-stock dashboard cards are Phase 1 or Phase 2 depending on material-module timing.

## 10. Notifications and Alerts

### Confirmed Decisions

- Notifications are required for email and in-app.
- Notification events include report submitted, report approved, report rejected, low stock, late report, new document, and pending approval.
- Assigned users should receive reminders before deadlines.
- If a required upload/report is missing, the Project Manager should receive notification.
- Users can mute notifications.
- Notification history should not be kept forever.
- Reminders should be sent for pending approvals.
- Unread notification count should be shown in the header.
- Notification retention should be 90 days for user-facing notifications. Audit logs should be retained separately for compliance.
- Recipient matrix:
  - Missing/late report: submitter first, then Project Manager.
  - Approval pending: assigned approver.
  - Approval approved/rejected: requester.
  - Low stock: Store Keeper, Project Manager, and Operation Manager.
  - New active document: relevant project team.
- Reminder timing should default to 24-hour pending reminder and 48-hour escalation.

### Remaining Follow-Up

- Confirm whether any notification must also be sent to General Manager.

## 11. Mobile and Offline Behavior

### Confirmed Decisions

- Offline draft saving can wait until Phase 3.
- Offline behavior is limited to saving draft reports offline, not full offline operation.
- Photo uploads should work offline.
- Material transactions do not need to work offline.
- Supported devices include Android phones, iPhones, tablets, and desktop.
- Supported browsers listed: Chrome, Opera, and Internet Explorer.
- Mobile does not need all desktop features. It should support the update flow and main functions.
- Minimum acceptable mobile network performance is H+.
- Field users are not expected to use low-end phones.
- Forms should autosave while the user is typing.
- Microsoft Edge should replace Internet Explorer support.
- Mobile MVP should include supervisor updates, engineer report/update, photo upload, document view, approvals, and notifications.
- Offline photo queue should save locally, retry automatically when online, and show sync status.
- Autosave should run every 30 seconds and on field blur/change.

### Remaining Follow-Up

- Confirm Edge replacement with stakeholders because Internet Explorer is end-of-life.
- Confirm whether approvals are required on mobile in MVP or desktop-only is acceptable.

## 12. Accounts and Financial Features

### Confirmed Decisions

- Accounts should track material usage, project budget, manpower, and invoicing.
- Invoice data should be structured in database fields, not only uploaded as documents.
- Payment status should be tracked.
- Accounts users can approve invoices, and Operation Manager must also approve.
- Material purchases do not need to connect to invoices.
- Project budget vs actual cost should be calculated.
- Accounting software integration is not required.
- Financial values are visible to Project Managers.
- OCR is both a future placeholder and desired capability.
- Financial reports should include bookkeeping, project-wise profit and loss, and salary sheets.
- Invoice fields should include invoice number, supplier, project, amount, tax, date, due date, status, attachment, approved by, and payment status.
- Invoice approval should be Accounts create/check -> Operation Manager approval.
- Salary sheets should be Phase 2/3 unless required immediately. Suggested fields include employee, project, days, overtime, allowance, deductions, and net salary.
- OCR should be treated as a future enhancement, not MVP.
- Financial reports should be visible to Admin, Accounts, Operation Manager, General Manager, and explicitly allowed Project Managers.

### Remaining Follow-Up

- Confirm whether salary sheets are required in Phase 1 or later.
- Confirm which Project Managers can view financial reports.

## 13. Data Model and Business Rules

### Confirmed Decisions

- Employee codes are mandatory.
- Phone numbers are mandatory.
- Project codes are auto-generated and unique.
- Material codes are mandatory for tools, but not required for all materials.
- Supplier records are required before creating materials.
- Supplier records should include TDS.
- Soft delete should be used for records.
- Deleted records remain recoverable for 30 days.
- Audit logs should record view/download actions and create/update/delete/login/approve actions.
- Audit logs are visible only to Admin.
- Retention rules are required for reports, photos, documents, and logs.
- Old projects should not be archived.
- Inactive users should remain represented in historical tasks/reports.
- The system should support multiple companies or branches later.
- Supplier TDS fields should include TDS certificate/file, tax registration number, expiry date, uploaded document, and compliance status.
- Retention recommendation: reports, documents, and photos are retained permanently for active/completed projects; deleted records are recoverable for 30 days; audit logs retained for 7 years.
- Multi-company/branch should be designed into the schema with optional `company_id` and `branch_id`, but only one company should be enabled first.
- Completed/old projects should become read-only and searchable, not hidden.

### Remaining Follow-Up

- Confirm legal retention period if contracts require longer than 7 years.
- Confirm whether branch support is needed in initial data model or only future-ready.

## 14. API and Integration Requirements

### Confirmed Decisions

- API access should support future mobile/native apps as well as the web app.
- Future integration with ERP, accounting, HR, attendance, or inventory systems is expected.
- API responses can be English initially.
- In the future, support 3 additional languages.
- Arabic/other localized field values are future requirements.
- Bulk import/export APIs are required.
- External integrations should not be included in MVP unless a confirmed system is provided now.
- Webhooks should not be included in MVP.
- Pagination defaults should be `page=1`, `per_page=20`, with maximum `per_page=100`.
- Large file/photo uploads should use presigned MinIO/S3 URLs. Direct API upload can be used only for small/simple files.
- MVP rate limits should be stricter for auth and upload endpoints, with standard limits for normal API calls. Heavy role-based rate-limit variation can wait.

### Remaining Follow-Up

- Identify the target ERP/accounting/HR/attendance/inventory systems.
- Confirm whether any of those target systems must be connected in MVP.

## 15. UI/UX and Branding

### Confirmed Decisions

- Existing company logo, brand color, typography, or design standard exists and should be used.
- Dark mode can wait until later.
- UI should be English in the first release.
- Users should be able to print forms exactly like company templates.
- Arabic/RTL should be design-ready but not implemented in the first release.
- Forms should match existing paper forms where users already rely on them.
- UX should prioritize mobile site users for update/report flows and desktop users for admin, accounts, documents, and management screens.
- Management tables should support search, filters, sorting, export, and saved filters.
- Validation should use clear field-level messages and never expose raw technical errors.

### Remaining Follow-Up

- Collect logo, colors, typography, and design standards.
- Collect required dashboard mockups, if any.
- Define mandatory fields for every form.
- Collect existing paper forms/templates.

## 16. Security, Compliance, and Access Control

### Confirmed Decisions

- Two-factor authentication is required.
- Admin should be able to reset accounts.
- Admin creates user accounts.
- Users should be forced to change password on first login.
- Password reset should happen through Admin or OTP.
- Account lockout should happen after 3 failed login attempts.
- Sessions should remain active for 1 day.
- Proposed 15-minute access token and 7-day refresh token is not acceptable.
- Downloads should be logged.
- No company network/IP restriction should be required for MVP unless the company explicitly requires it.
- Session design should support a 1-day session using a short-lived access token, silent refresh, and forced logout after inactivity if configured.
- Block executable/script file types by default, including `.exe`, `.sh`, `.bat`, `.cmd`, `.js`, `.php`, `.html`, and unknown binaries.
- Backups should be encrypted and stored off-server/cloud, with local database backup also retained.
- Backup restore testing should happen monthly.
- MVP 2FA should use email OTP. Authenticator-app support can be added later.

### Remaining Follow-Up

- Confirm whether company requires IP/network restriction.
- Confirm backup storage provider/location.

## 17. Deployment, Hosting, and Operations

### Confirmed Decisions

- Deployment decisions currently require Operation Manager approval.
- Recommended MVP hosting is a cloud VPS with Docker Compose.
- Post-launch server ownership should be assigned to internal admin/IT, with development support during warranty.
- Construction-site internet reliability should be tested; the app should tolerate weak H+ networks.
- Backup retention should be daily backups for 30 days and monthly backups for 12 months.
- Basic uptime/error monitoring should be implemented in Phase 1. Full monitoring dashboards can come later.
- System error alerts should go to Admin/technical support, and Operation Manager for business-critical outages.
- Staging and production environments are required.
- Staging and production deployments should run from the approved commit, with Operation Manager approval required before production release.

### Remaining Follow-Up

- Confirm final hosting provider/VPS.
- Confirm internal server owner/contact.

## 18. Testing and Acceptance Criteria

### Confirmed Decisions

- User acceptance testing will be performed by the MD and Operation Manager.
- Launch scenarios must include login, user creation, project creation, supervisor update, engineer report, approval, rejection, photo upload, document version upload, material request if included, notification, and export.
- Phase 1 is done when all launch scenarios pass on mobile and desktop with real seed data.
- 80% backend coverage is desirable for critical modules, but launch should not depend on a global percentage. Tests are required for auth, reports, approvals, materials if included, and documents.
- Test browsers/devices should include Chrome, Edge, Safari iOS, and Android Chrome.
- Low-speed network testing should be included.
- Sample users and sample projects should be included for testing.
- Client should approve UI screens before development for each major module.
- Module sign-off is required before moving to the next phase.
- Launch blockers include login failure, data loss, wrong approval routing, broken upload, wrong permissions, missing audit trail, and failed report submission.

### Remaining Follow-Up

- Confirm final UAT checklist with MD and Operation Manager.

## 19. Data Migration and Initial Setup

### Confirmed Decisions

- Existing data import can happen later.
- Users are currently stored in Excel, HR software, or another system.
- Projects, suppliers, materials, and documents are already available in spreadsheets.
- Material opening stock should be imported.
- Source spreadsheets should be collected before final schema and import-template lock.
- Import templates should be created for users, projects, suppliers, materials, documents, BOQ, and opening stock.
- Historical reports/documents should not be migrated in MVP unless legally required. MVP should start with active projects and opening balances.

### Remaining Follow-Up

- Collect source spreadsheets and confirm data quality.
- Confirm whether historical reports/documents are legally required for migration.

## Implementation Impact Summary

These stakeholder answers change the implementation plan in several important ways:

1. The first release should prioritize real operational task/report updates over a full dashboard-heavy portal.
2. Document management and version control move into the first release.
3. Daily report flow is supervisor update -> engineer quality/update -> project manager approval.
4. Materials require a separate request workflow, reservations, multi-location stock, non-negative stock, and price visibility restrictions.
5. Project tracking needs Gantt/task support, BOQ linkage, and discipline-specific progress.
6. Accounts is more than document access; it requires structured finance, budget, manpower, invoicing, payment status, and project-wise profit/loss reporting.
7. Mobile is important, but full offline support can wait until Phase 3.
8. Security requirements include 2FA, admin/OTP password reset, 3-failure lockout, 1-day sessions, and download logging.
9. Recommended defaults now exist for most previously unanswered questions.
10. Remaining follow-up is mostly about collecting company assets/templates/data, confirming final hosting ownership, and validating a few business-specific policies.
