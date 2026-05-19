# Approval Process - Code-Verified Reference

## Overview

The current implementation has **three separate approval mechanisms**. They share notification/email infrastructure, but their API routes and business logic are separate.

| Mechanism | Managed by | Primary routes | Current use |
|---|---|---|---|
| Daily report approval | `ReportService` | `/api/v1/reports/{id}/approve`, `/reject`, `/override` | Engineer daily site reports |
| Generic workflow approval | `ApprovalService` | `/api/v1/approvals` and `/api/v1/approvals/{id}/...` | Invoices and material requests |
| Document version approval | `DocumentService` | `/api/v1/documents/{id}/versions`, `/versions/{version_id}/approve` | Uploaded documents and document versions |

Documents are **not currently routed through the generic approval inbox**. `ApprovalService` contains generic document side-effect handling, but the active document routes use `DocumentService` directly.

---

## Email and Notifications

### Notification Email Flow

Most approval-related notifications are created through `NotificationService.create()`. The service writes a notification row with `email_status = "queued"` and registers an SQLAlchemy `after_commit` hook. After the transaction commits, the hook queues `send_email_notification.delay(notification_id)` on the email Celery queue.

The email task:

- skips muted notifications and marks them `email_status = "skipped"`;
- resolves the recipient email from the notification user;
- sends a plain-text email with the notification title as the subject;
- marks the row `sent` if `EmailService.send()` returns without raising;
- marks the row `failed` only when the task catches an exception.

When `FRONTEND_BASE_URL` is configured, approval-related notification bodies append an absolute in-app URL. The backend builds that URL at send time from configuration rather than hard-coding a domain, so production, staging, and local deployments can each emit the correct portal hostname.

Current link routing rules:

- approver-facing workflow emails (`Approval pending`, `Approval delegated`, `Approval reminder`, `Approval escalated`) link to `/approvals` with query params that select the workflow tab and targeted approval;
- approver-facing daily report submission emails link to `/approvals` with query params that select the report tab and targeted report;
- submitter-facing outcome emails link to the owning entity page instead of `/approvals`, because the frontend approval inbox route is still gated by `reports:approve`;
- document notifications link to `/documents` with `documentId` and `versionId` query params so the mail points to the exact uploaded or approved file version;
- if `FRONTEND_BASE_URL` is unset, the notification still sends, but without an appended link.

Important implementation caveat: `EmailService.send()` catches SMTP/network send errors, logs a warning, and returns `0`. Because that does not raise, the Celery task can still mark the notification as `sent` even when SMTP delivery failed.

Notification emails do not include attachments.

### Daily Report PDF Email

When a daily report is approved, or admin-overridden to approved, `ReportService` queues `generate_report_pdf.delay(report_id, actor_id, email_after=True)` on the report queue. The report task generates the PDF export, uploads it to MinIO, saves a `ReportExport` row, then queues `send_report_email.delay(export_id)`.

The report email is sent to `REPORT_EMAIL_RECIPIENTS`. It is plain text and contains the generated file name, MinIO object key, and content type. It does **not** attach the PDF.

Example body shape:

```text
A daily report export is ready.

File: GIP001-DR-20250519-001.pdf
Object key: reports/<project_id>/<report_id>/GIP001-DR-20250519-001.pdf
Content type: application/pdf
```

---

## Daily Report Approval

### Roles

| Role | Can create/submit reports | Can approve/reject | Can override |
|---|---:|---:|---:|
| Civil Engineer | Yes | No | No |
| Project Manager | No | Assigned projects | No |
| Operation Manager | No | Any project | No |
| General Manager | No | Any project | No |
| Admin | Yes, including past dates | Yes | Yes |

Daily report creation and editing is limited to Civil Engineer and Admin. Non-admin users cannot create past-dated reports.

### Lifecycle

```text
DRAFT
  - editable by the report owner role while draft
  - submitted with POST /api/v1/reports/{id}/submit

SUBMITTED
  - locked from editing
  - approver can reject with comments
  - approver can approve only when target_covered is true

APPROVED
  - immutable
  - records approved_by and approved_at
  - consumes reported materials from inventory
  - queues PDF export and report email

REJECTED path
  - rejection changes status back to draft
  - rejection comments are saved
  - engineer can edit and resubmit
```

Approval requires the report status to be exactly `submitted`. Rejection also requires `submitted` status and comments.

### Approval Side Effects

Normal approval:

- requires `target_covered = true`;
- sets status to `approved`;
- records `approved_by` and `approved_at`;
- writes `DailyReportApprovalHistory`;
- records an audit entry;
- consumes report materials from inventory;
- sends an in-app notification to the engineer;
- queues the notification email after commit;
- queues report PDF generation and the report export email.

Rejection:

- requires comments;
- changes status back to `draft`;
- stores the rejection comments;
- writes `DailyReportApprovalHistory`;
- records an audit entry;
- sends an in-app notification and queued email to the engineer.

Admin override:

- is Admin-only;
- requires a reason;
- accepts `decision = "approved"` or `decision = "rejected"`;
- requires `target_covered = true` for approved overrides;
- uses the same material consumption and PDF/email side effects as normal approval when approved;
- changes the report back to `draft` when rejected;
- writes approval history and audit records.

### Frontend Behavior

The `/approvals` page has a **Report approvals** tab. It loads submitted daily reports and displays report metadata, work completed, next-day plan, safety summary, history count, comments textarea, target-covered checkbox, approve/reject buttons, and an Admin-only override panel.

The frontend blocks report approval if the target-covered checkbox is not selected. Reject comments are required.

Email deep links target `/approvals?tab=reports&reportId=<report-id>` for approvers. Engineer-facing outcome emails target `/reports/daily?reportId=<report-id>`. Both pages now scroll the matching report card into view and visually highlight it.

---

## Generic Workflow Approval

### Current Producers

The generic workflow is implemented by `ApprovalService`. The current code paths that create generic approvals are:

| Request type | Current producer | Entity side effect |
|---|---|---|
| `invoice` | Finance service when an invoice is created | Approve sets invoice approved and records approver/time; reject sets invoice rejected |
| `material_request` | Inventory service when a material request is created | Approve sets request approved; reject sets request cancelled |

`ApprovalService` also contains entity side-effect branches for `daily_report` and `document`, but those types are not currently produced by the report or document services through the generic approval API.

### Direct API Creation

`POST /api/v1/approvals` is authenticated. It blocks direct creation of entity-backed approval types:

- `material_request`
- `invoice`
- `daily_report`
- `document`

Those types require an internal service call. Other request types, such as `payment` or `project_change`, are not currently role-gated by the route beyond authentication and service validation.

### Approver Resolution

When `ApprovalService.create_approval()` creates a generic approval, it selects an approver in this order:

1. `invoice` -> first active Operation Manager.
2. `material_request` with amount greater than `1000` -> first active Operation Manager.
3. `material_request` or `project_change` submitted by a Project Manager -> first active Operation Manager.
4. Project-scoped request -> active Project Manager assigned to the project, excluding the submitter.
5. Fallback -> first active Operation Manager.
6. Final fallback -> first active Admin.

The service also assigns `escalation_user_id` to the first active Operation Manager.

### Statuses and Actions

Actionable statuses are:

- `pending`
- `delegated`
- `escalated`

Terminal statuses are:

- `approved`
- `rejected`
- `override_approved`
- `override_rejected`

Approve:

- allowed for the original approver or delegated user;
- comments are optional;
- sets status to `approved`;
- records `decided_at`;
- applies entity side effects;
- notifies the submitter;
- records an audit entry.

Reject:

- allowed for the original approver or delegated user;
- comments are required;
- sets status to `rejected`;
- applies entity side effects;
- notifies the submitter;
- records an audit entry.

Delegate:

- allowed for the original approver or current delegate;
- requires an active target user;
- sets status to `delegated`;
- saves `delegated_to_id` and `delegation_reason`;
- notifies the delegate;
- records an audit entry.

Delegation is **not exclusive**. The original approver remains allowed to approve, reject, or delegate again after delegation because the actor check accepts either `approver_id` or `delegated_to_id`.

Admin override:

- Admin-only;
- requires `decision` and reason;
- sets status to `override_approved` or `override_rejected`;
- applies the same entity side effects as normal approval/rejection;
- notifies the submitter;
- records an audit entry.

### Reminders and Escalation

The `process_approval_reminders` Celery task runs hourly.

Reminder behavior:

- finds `pending` or `delegated` approvals where `due_at <= now` and `reminded_at IS NULL`;
- sends a notification to the current actor, using the delegate if one exists, otherwise the original approver;
- sets `reminded_at`;
- email is queued by the normal notification email hook.

Escalation behavior:

- finds `pending` or `delegated` approvals where `due_at <= now - 24 hours` and `escalated_at IS NULL`;
- because `due_at` is created as `submitted_at + 24 hours`, escalation happens about 48 hours after submission;
- sets status to `escalated`;
- sets `escalated_at`;
- notifies `escalation_user_id`;
- email is queued by the normal notification email hook.

Reminder and escalation processing does not currently write approval audit-log entries.

### Generic Approval Frontend

The `/approvals` page has a **Workflow approvals** tab. It currently loads:

```ts
listApprovals({ box: 'inbox', status: 'pending' })
```

That means the frontend shows pending inbox approvals by default. It does not expose a generic approval outbox UI.

When the page is opened with `approvalId` in the query string, the frontend also calls `GET /api/v1/approvals/{approval_id}` and inserts that record into the workflow list if needed. This allows delegated or escalated approval links from email to resolve even though they are not part of the default `status=pending` query.

Each workflow card shows the title, status, request type, due date, optional amount/currency, submitter comments, action comments, delegate controls, Admin-only override controls, and approve/reject buttons.

Current workflow email link targets:

- approver-facing mails -> `/approvals?tab=workflow&approvalId=<approval-id>`;
- invoice outcome mails -> `/finance?invoiceId=<invoice-id>`;
- material-request outcome mails -> `/materials?materialRequestId=<request-id>`;
- `payment` and `project_change` outcome mails currently have no dedicated frontend detail page, so they do not get an entity deep link in the notification body.

---

## Document Version Approval

Documents use dedicated document routes and `DocumentService`; they do not currently create generic `Approval` rows.

### Permissions

| Action | Permission |
|---|---|
| List, view, or download documents | `documents:view` |
| Upload documents, upload versions, list versions, approve versions | `documents:manage` |

### Lifecycle

Uploading a document or new version creates a pending document/version state:

- document status becomes `pending_approval`;
- the uploaded version status is `pending_approval`;
- an audit entry is recorded;
- an in-app notification is sent to the uploader.

Approving a pending document version:

- is handled by `POST /api/v1/documents/{document_id}/versions/{version_id}/approve`;
- requires a document approver role through `DocumentService`;
- changes the approved version to `active`;
- changes any previous active version to `superseded`;
- changes the document status to `active`;
- records an audit entry;
- sends a notification to the uploader.

This approval path is separate from `/api/v1/approvals` and does not appear in the frontend workflow approval inbox.

Document emails now link to `/documents?documentId=<document-id>&versionId=<version-id>`, and the document library highlights both the matching document card and the specific version row.

---

## Visibility and Inbox Rules

### Generic Approval API

Listing approvals through `GET /api/v1/approvals` requires the approval inbox permission. The endpoint supports `box=inbox` and `box=outbox`, but the current frontend only uses pending inbox.

Repository scoping:

- `box=inbox` returns approvals where the user is `approver_id` or `delegated_to_id`.
- Admin inbox listing can include all matching approvals.
- `box=outbox` returns approvals where the user is `submitter_id`.
- Escalation users can view an approval detail, but escalation ownership is not included in the normal inbox query.

Detail/action visibility:

- Admin can view any approval.
- Submitter can view their own submitted approval.
- Approver can view assigned approvals.
- Delegate can view delegated approvals.
- Escalation user can view approvals where they are the escalation target.

Actions still require service-level authorization. Viewing an approval is broader than being allowed to approve or reject it.

The frontend route `/approvals` still requires `reports:approve`. That is why submitter-facing workflow outcome emails route to entity pages instead of the shared approval inbox.

---

## Audit Trail

Current audited approval-related actions include:

- generic approval create, approve, reject, delegate, and override;
- daily report approval, rejection, and override;
- document upload/version upload and document version approval.

Current non-audited approval automation:

- generic approval reminder notifications;
- generic approval escalation notifications/status updates.

Admins can review audit records through the audit-log feature where route permissions allow it.

---

## Email Summary

| Event | Recipient | Email content | In-app link target | Attachment |
|---|---|---|---|---|
| Generic approval created | Assigned approver | Notification title/body, e.g. approval pending | `/approvals?tab=workflow&approvalId=<approval-id>` | None |
| Generic approval approved | Submitter | Notification title/body, e.g. approval completed | Entity page when available: invoice, material request, report, or document | None |
| Generic approval rejected | Submitter | Notification title/body, e.g. approval rejected | Entity page when available: invoice, material request, report, or document | None |
| Generic approval delegated | Delegate | Notification title/body, e.g. approval delegated | `/approvals?tab=workflow&approvalId=<approval-id>` | None |
| Generic approval overridden | Submitter | Notification title/body, e.g. approval overridden | Entity page when available: invoice, material request, report, or document | None |
| Generic reminder | Current actor | Notification title/body, e.g. approval still pending | `/approvals?tab=workflow&approvalId=<approval-id>` | None |
| Generic escalation | Escalation user | Notification title/body, e.g. pending more than 48 hours | `/approvals?tab=workflow&approvalId=<approval-id>` | None |
| Daily report submitted | Approver | Notification title/body | `/approvals?tab=reports&reportId=<report-id>` | None |
| Daily report approved/rejected/overridden | Engineer | Notification title/body | `/reports/daily?reportId=<report-id>` | None |
| Daily report PDF export ready | `REPORT_EMAIL_RECIPIENTS` | File name, object key, content type | None | None |
| Document uploaded/approved | Uploader | Notification title/body | `/documents?documentId=<document-id>&versionId=<version-id>` | None |

Email status should be interpreted carefully: muted notifications are marked `skipped`, task-level exceptions are marked `failed`, but SMTP send failures swallowed by `EmailService.send()` may still be marked `sent`.
