# Approval Process — Full Reference

## Overview

The project has **two independent approval tracks**. They share the same notification and email infrastructure but use completely separate API routes and service logic.

| Track | Managed By | API Routes | Used For |
|---|---|---|---|
| **Daily Report** | `ReportService` | `POST /api/v1/reports/{id}/approve` etc. | Engineer daily site reports |
| **Generic Workflow** | `ApprovalService` | `POST /api/v1/approvals/{id}/approve` etc. | Material requests, invoices, documents, custom items |

---

## Email — What Gets Sent, and How

### Delivery mechanism

Every notification created in the system (approval pending, approved, rejected, reminder, escalation) automatically triggers an email via a **Celery background task** (`send_email_notification`). The flow is:

1. `NotificationService.create()` writes a `Notification` row with `email_status = "queued"`.
2. A SQLAlchemy `after_commit` event fires immediately after the DB transaction commits.
3. That hook calls `send_email_notification.delay(notification_id)` — pushing the job to the **`email` Celery queue**.
4. The task fetches the notification, resolves the recipient's email from their user record, and calls `EmailService.send()`.
5. `EmailService` opens an SMTP connection (with optional TLS + auth) and sends the message.
6. The notification row is updated to `email_status = "sent"` or `"failed"`.

> [!IMPORTANT]
> **No attachments are ever included in notification emails.** Every notification email is **plain-text only**. The subject is the notification title (e.g. "Approval pending") and the body is a one-sentence description (e.g. "Invoice #INV-001 is waiting for your approval.").

> [!NOTE]
> **Muted notifications are skipped.** If a user mutes a notification before the Celery task runs, the task marks `email_status = "skipped"` and sends no email.

### Report PDF email (post-approval only)

When a daily report is **approved** (or admin-overridden to approved), a separate chain fires:

1. `ReportService._queue_post_approval_tasks()` calls `generate_report_pdf.delay(report_id, actor_id, email_after=True)` on the **`report`** queue.
2. The `generate_report_pdf` task calls `ReportExportService.generate_pdf_export()` which:
   - Builds a full A4 PDF using **ReportLab** containing report metadata, work completed, next-day plan, manpower, equipment, material consumption tables.
   - Uploads the PDF to **MinIO object storage** at the key `reports/{project_id}/{report_id}/{report_number}.pdf`.
   - Saves a `ReportExport` row in the DB (with `object_key`, `file_name`, `status = "ready"`).
3. After that task completes, `send_report_email.delay(export_id)` fires on the **`email`** queue.
4. `send_report_email` sends a plain-text email to the address list in the `REPORT_EMAIL_RECIPIENTS` environment variable.

> [!IMPORTANT]
> **The PDF report email does NOT attach the PDF.** It is a notification-style email that contains the filename and the MinIO object key. The recipient must log into the system and download the PDF via `GET /api/v1/reports/{id}/pdf`.
>
> The email body looks like:
> ```
> A daily report export is ready.
>
> File: GIP001-DR-20250519-001.pdf
> Object key: reports/<project_id>/<report_id>/GIP001-DR-20250519-001.pdf
> Content type: application/pdf
> ```

---

## Track 1 — Daily Report Approval

### Who can do what

| Role | Can Submit | Can Approve / Reject | Can Override |
|---|---|---|---|
| Civil Engineer | ✅ | ❌ | ❌ |
| Project Manager | ❌ | ✅ (own projects only) | ❌ |
| Operation Manager | ❌ | ✅ (any project) | ❌ |
| General Manager | ❌ | ✅ (any project) | ❌ |
| Admin | ✅ (any date) | ✅ | ✅ |

### Full Lifecycle

```
[Civil Engineer]
     │
     ▼
  DRAFT ──────────────────────────────── (editable)
     │  POST /reports/{id}/submit
     ▼
SUBMITTED ◄─────────────────────────────────────────────────────────┐
     │                                                               │
     ├── POST /reports/{id}/reject  (PM / OpMgr / GM / Admin)       │
     │      • Comments required                                      │
     │      • Status → DRAFT                                         │
     │      • Rejection reason saved                                 │
     │      • In-app notification → Engineer                         │
     │      • Email → Engineer (plain text: "was rejected")          │
     │      • Engineer can edit and re-submit                        │
     │                                                            ───┘
     │
     └── POST /reports/{id}/approve  (PM / OpMgr / GM / Admin)
            • target_covered = true is REQUIRED (blocks otherwise)
            • Comments optional
            • Status → APPROVED
            • approved_by + approved_at recorded
            • DailyReportApprovalHistory entry written
            • Inventory materials consumed from stock
            • In-app notification → Engineer
            • Email → Engineer (plain text: "has been approved")
            • PDF generated and uploaded to MinIO (background task)
            • Notification email → REPORT_EMAIL_RECIPIENTS (plain text, no attachment)

[Admin only]
     │
     └── POST /reports/{id}/override
            • decision = "approved" | "rejected"
            • reason required
            • If decision = "approved": target_covered must also be true
            • If decision = "approved": same side-effects as normal approve
            • If decision = "rejected": status → DRAFT, reason saved
            • DailyReportApprovalHistory entry written with "Admin override: ..." prefix
            • In-app notification → Engineer
            • Email → Engineer (plain text: "was overridden: approved/rejected")
```

### Frontend — How the Approver Acts

The approver navigates to **Approval Inbox** (`/approvals`) in the frontend.

On the **Report approvals** tab, each submitted report card shows:
- Report number, date, work location, progress percentage
- Work completed, next-day plan, safety summary, history event count
- A **comments textarea** (optional for approve, required for reject)
- A **"Target covered confirmation"** checkbox — must be ticked before the Approve button works; the frontend blocks submission and shows an inline error if not checked
- **Approve** and **Reject** buttons
- **Admin-only override panel** (hidden for non-admins): decision dropdown (approve/reject), reason text input, second "target covered" checkbox, and an "Override report" button

### Key Constraints

- A report can only be approved while status is exactly `"submitted"`.
- Approved reports are **immutable** — editing is blocked.
- Submitted reports are also locked — the engineer cannot edit until the approver rejects.
- Engineers cannot submit past-dated reports; only Admin can.

---

## Track 2 — Generic Workflow Approval

### Approval types and who triggers them

| `request_type` | Triggered by | Notes |
|---|---|---|
| `material_request` | Inventory service when a request is submitted | |
| `invoice` | Finance service when an invoice is created | Always routes to Operation Manager |
| `document` | Document service when a new version is uploaded | |
| `payment`, `project_change` | Any user with appropriate role | Manually created via `POST /approvals` |

> [!NOTE]
> `material_request`, `invoice`, `document`, and `daily_report` are **entity-backed** — they can only be created by their owning service. Direct API creation of these types is blocked with `403 APPROVAL_TYPE_FORBIDDEN`.

### Approver Resolution (automatic)

When an approval is created, the system automatically selects the approver using this priority order:

1. **Invoice** → Operation Manager (always)
2. **Material request with amount > $1,000** → Operation Manager
3. **Material request or project change submitted by a Project Manager** → Operation Manager
4. **Project-scoped request** → The active Project Manager of the project who is not the submitter
5. **Fallback** → First active Operation Manager
6. **Final fallback** → First active Admin

Additionally, the system always assigns an `escalation_user_id` — always the first active Operation Manager — to be notified if the approval sits too long.

### Status State Machine

```
PENDING
   │
   ├─► DELEGATED  (approver hands off to another user)
   │       │
   │       └─► (delegated user can now approve or reject)
   │
   ├─► ESCALATED  (system auto-escalates after 24h past due_at)
   │
   ├─► APPROVED
   ├─► REJECTED
   ├─► OVERRIDE_APPROVED   (Admin only)
   └─► OVERRIDE_REJECTED   (Admin only)
```

Any status in `{pending, delegated, escalated}` is considered "actionable". Terminal statuses `{approved, rejected, override_*}` are final and cannot be acted on.

### Full Lifecycle

```
[Owning service or authorized user]
     │  POST /approvals  (or internal call)
     ▼
   PENDING
     • Approval row created with due_at = submitted_at + 24 hours
     • In-app notification → Assignee: "Approval pending"
     • Email → Assignee (plain text: "{title} is waiting for your approval.")

     │
     ├── POST /approvals/{id}/approve  (approver or delegated user)
     │      • Comments optional
     │      • Status → APPROVED
     │      • decided_at recorded
     │      • Entity updated atomically:
     │          material_request → status = "approved"
     │          invoice          → status = "approved", approved_by/at set
     │          document         → latest pending_approval version → "active",
     │                             previous active version → "superseded",
     │                             document.status = "active"
     │          payment/project_change → audit record only
     │      • In-app notification → Submitter: "Approval completed"
     │      • Email → Submitter (plain text: "{title} was approved.")
     │      • Audit log entry
     │
     ├── POST /approvals/{id}/reject  (approver or delegated user)
     │      • Comments REQUIRED (empty body → 422)
     │      • Status → REJECTED
     │      • Entity updated:
     │          material_request → status = "cancelled"
     │          invoice          → status = "rejected"
     │          document         → status = "rejected"
     │      • In-app notification → Submitter: "Approval rejected"
     │      • Email → Submitter (plain text: "{title} was rejected.")
     │      • Audit log entry
     │
     ├── POST /approvals/{id}/delegate  (approver only)
     │      • Payload: delegated_to_id (UUID), reason (string)
     │      • Target user must exist and be active
     │      • Status → DELEGATED
     │      • delegated_to_id and delegation_reason saved
     │      • In-app notification → Delegate: "Approval delegated to you"
     │      • Email → Delegate (plain text: "{title} was delegated to you.")
     │      • Audit log entry
     │      • Delegate can now approve or reject
     │
     └── POST /approvals/{id}/override  (Admin only)
            • Payload: decision ("approved"|"rejected"), reason (string)
            • Reason required; non-Admin gets 403
            • Status → OVERRIDE_APPROVED or OVERRIDE_REJECTED
            • Same entity side-effects as normal approve/reject
            • In-app notification → Submitter: "Approval overridden"
            • Email → Submitter (plain text: "{title} was approved/rejected by admin override.")
            • Audit log entry
```

### Automatic Reminders and Escalation (Celery Beat)

The `process_approval_reminders` Celery task runs **every hour**.

**Reminder logic:**
- Finds all `pending` or `delegated` approvals where `due_at <= now` AND `reminded_at IS NULL`.
- Sends an in-app notification to the current actor (delegate if set, otherwise original approver).
- Email is sent automatically via the notification email hook.
- Sets `reminded_at = now` so it only fires once per approval.

**Escalation logic:**
- Cutoff = `now - 24 hours`
- Finds all `pending` or `delegated` approvals where `due_at <= cutoff` AND `escalated_at IS NULL`.
- Since `due_at = submitted_at + 24h`, this means:  
  `submitted_at + 24h ≤ now - 24h` → approval escalates **48 hours after it was submitted**.
- Sets status to `"escalated"` and `escalated_at = now`.
- Sends in-app notification → `escalation_user_id` (the Operation Manager assigned at creation).
- Email → Operation Manager (plain text: "{title} has been pending for more than 48 hours.").

> [!NOTE]
> The escalation **notification message** says "more than 48 hours" — which correctly describes the actual 48-hour threshold from submission (24h due_at + 24h cutoff). The repository query itself uses a 24h rolling cutoff relative to `now`, but only against the `due_at` field which is already +24h ahead of submission. The net effect is a 48-hour window from submission.

### Frontend — How the Approver Acts

On the **Workflow approvals** tab of the Approval Inbox, each pending approval card shows:
- Title, status badge, request type, due date, optional amount/currency
- Submitter's comments
- A **comments textarea** (used for approve or reject)
- A **Delegate panel**: user UUID input, reason input, Delegate button
- An **Admin override panel** (hidden for non-admins): decision dropdown, reason input, Override button
- **Reject** and **Approve** buttons

### Inbox vs. Outbox

- **Inbox**: Shows approvals where the logged-in user is `approver_id` or `delegated_to_id`. Admins see all pending approvals.
- **Outbox**: Shows approvals where the logged-in user is `submitter_id`.

---

## Visibility Rules

| Role | Can view approval detail |
|---|---|
| Admin | Any approval |
| Submitter | Their own submissions |
| Approver | Approvals assigned to them |
| Delegate | Approvals delegated to them |
| Escalation user | Approvals they are the escalation target for |

---

## Audit Trail

Every action (create, approve, reject, delegate, override, escalation) writes a row to the `audit_log` table via `AuditService.record()`. The log captures: action name, user, entity type, entity id, old values, new values, and a comment. This is viewable by Admins on the Audit Log page.

---

## Summary of Email Behaviour

| Event | Recipient | Email content | Attachment? |
|---|---|---|---|
| Approval created | Assigned approver | "X is waiting for your approval" | ❌ None |
| Approved | Submitter | "X was approved" | ❌ None |
| Rejected | Submitter | "X was rejected" | ❌ None |
| Delegated | New delegate | "X was delegated to you" | ❌ None |
| Overridden | Submitter | "X was approved/rejected by admin override" | ❌ None |
| Reminder (hourly) | Current approver | "X is still waiting for approval" | ❌ None |
| Escalated | Operation Manager | "X has been pending for more than 48 hours" | ❌ None |
| Daily report approved | `REPORT_EMAIL_RECIPIENTS` | File name + MinIO object key | ❌ None (link to file location only) |
| Daily report approved | Engineer | "X has been approved" | ❌ None |
