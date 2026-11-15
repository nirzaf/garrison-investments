# HR and workforce

The HR workspace at `/hr` uses the existing portal sign-in. Its API lives under
`/api/v1/hr`. An employee record has its own ID and can exist without a portal
account. The optional account link requires an active user with the same verified
work email. It never grants a project membership or changes a portal role.

## Who can use it

| Actor | Access |
| --- | --- |
| HR Manager | Workforce records, recruiting and onboarding, employment decisions, protected employee data, HR documents, time and leave, service requests, and offboarding. |
| Managing Director and Operations Director | Review and fulfill the account handoff using the existing user service. The handoff does not grant access to the HR directory or private files. |
| Linked employee | Own profile and contact updates, attendance, leave, shared active documents, policy acknowledgments, and HR service requests in `/me/hr`. |

HR Manager is the single HR role. User mutations, platform-wide audit access
and generic project-document viewing remain separate permissions. Workflows
that require independent HR review use two distinct accounts with the same
HR Manager role. The original workbook matrix remains a historical fixture.

## Core workflows

The status column describes source implementation and role policy, not live
user acceptance. `CODED` means the API/UI path exists; `PARTIAL` means a known
workflow gap remains; `ROLE_GATED` means no current role has the required grant.
Actual use still requires an active authorized account, linked employee data
where relevant, approved policy values, and the workflow's own checks.

| Area | Status | Available path or boundary |
| --- | --- | --- |
| Organization and employee directory | CODED | HR workspace departments, positions, reporting lines, work locations, primary membership status, employment history and project assignment requests. Approval remains with an authorized project manager or director. |
| Sensitive records | CODED | HR Manager private profile and category-gated documents. Encrypted fields require a dedicated `HR_ENCRYPTION_KEY` and approved key custody. |
| Recruitment and onboarding | CODED | HR workspace requisitions (including requested headcount and persisted HR-authorized rejection reasons), applications, interviews, offers (with optional validity deadlines, `expired` transitions, and immutable versioned terms on reissue), candidate CVs, onboarding checklists and probation decisions. Pending migration `202605310014` adds the rejection-reason and offer expiry/versioning schema columns (not yet deployed to production). |
| Portal access handoff | CODED | HR request and independent HR review followed by fulfillment through an authorized director account. |
| Personnel workbook | CODED; MAPPING REQUIRED | HR workspace and CLI preview and reconcile employee drafts. Sign-in identity, verified work emails, job-title mappings and account approval require separate verification. |
| Personnel documents | CODED | HR upload, review, version history and authorized download. Linked employees can download ordinary active versions shared with them. |
| Calendars and shifts | CODED | HR workspace review and publication before assignment. Existing approved calendars determine scheduled days and timezones. |
| Attendance | CODED | HR entry and CSV import, employee correction requests, HR review and period locks. |
| Timesheets and overtime | PARTIAL | HR entry and decisions are available. Employee submission and advisory manager review require the corresponding settings. Payroll processing has no active role grant. |
| Leave and self-service | CODED | HR catalog, policy and ledger functions. Linked employees can view balances, submit requests and use authorized cancellation. |
| Service requests | CODED | Employee submission, HR response and completion, and owner reopening. Overdue reminders require a configured SLA threshold and supporting release. |
| Letters and acknowledgments | CODED | HR Managers can create templates and preview a letter using directory data. The workspace also supports policy publishing and My HR acknowledgments. |
| Offboarding | CODED | HR workspace clearance and closure, with director fulfillment for linked-account deactivation. |
| Reporting | CODED | HR aggregates and filtered CSV, XLSX and PDF exports. |
| CLI | CODED | Registered remote commands use the same API permission boundaries. See [workforce CLI commands](CLI_ADMINISTRATION.md#workforce-administration). |
| Performance and training | ROLE_GATED | API paths exist. No current role has either management permission. |
| Benefits, reimbursements, compensation and payroll | ROLE_GATED | Benefits and compensation administration, HR reimbursement review/decision, and payroll preparation/approval require payroll permissions with no current role grant. Linked employees can submit their own reimbursement claims, but an authorized reviewer cannot list or decide them under the current catalogue. Calculations also require an approved policy. |
| Restricted employee cases | ROLE_GATED | The current catalogue grants no restricted-case permission. |

Source references are the [registered HR routes](../backend/app/api/v1/hr.py),
[domain workflows](../backend/app/services/hr_workforce_service.py),
[workspace and self-service views](../frontend/src/pages/hr/), and
[role grants](../backend/app/utils/permissions.py).

### Bounded implementation follow-ups

HR-008 (requisition rejection reasons and requested headcount) and HR-010
(offer validity deadlines, `expired` transitions, and immutable versioned
reissue via `POST /api/v1/hr/offers/{offer_id}/reissue`) are implemented in
code alongside Alembic revision
[`202605310014`](../backend/alembic/versions/202605310014_hr_recruitment_followups.py),
[`HRHiringPanel`](../frontend/src/pages/hr/HRHiringPanel.tsx), and
[`HRWorkspacePage`](../frontend/src/pages/hr/HRWorkspacePage.tsx). They await
deployment under the
[production maintenance procedure](OPERATIONS_AND_DEPLOYMENT.md#production-maintenance)
and post-release acceptance verification (production remains on SHA `be61f5b`
/ revision `202605310013` until deployed).

### Production deployment and available access

The production deployment was verified on 2026-11-15 at SHA
`be61f5b74ce9701ba83f70261b03fe6219bd2d72`, with Alembic head
`202605310013`. The exact candidate passed [self-hosted CI](https://github.com/nirzaf/garrison-investments/actions/runs/43708858463)
and [production deployment](https://github.com/nirzaf/garrison-investments/actions/runs/43717032813).
Readiness returned `ready` with PostgreSQL connected; sign-in and the service
worker returned HTTP 200. Anonymous HR directory and assignment requests
returned HTTP 401, confirming the authentication boundary only.

The post-deployment read-only count showed zero active HR Manager accounts and
zero `hr_employees` rows. As a result, HR Manager workflows have no provisioned
production operator yet, and employee self-service has no employee records or
linked accounts to exercise. This is not authenticated HR UAT or business
acceptance. Do not create production identities or import employee information
without an approved account, source roster, field mapping and authorized owner.

### Operational workflow guidance

- **Directory.** Create a draft and record verified work details. Employee edits
  use the displayed record revision. Reporting lines reject cycles and never
  determine project access. An HR Manager reviews activation.
- **Project assignments.** Inspect a linked employee in **Directory & Org** to
  request adding or removing project team access. A project manager with access
  to that project, or a director, reviews the request in **Projects → Team**.
  Approval uses the normal project membership service. HR can follow the
  decision in **My requests**. The organization chart shows work location and
  whether the employee's primary project membership is active.
- **Account handoff.** One HR actor requests a provision, link, role change,
  deactivation, or reactivation. A different HR Manager approves it. A director
  completes it. Provisioning requires a verified work email, employee code,
  work phone, approved role, and securely issued temporary password. For an
  existing account, confirm its ID and matching work email before linking.
- **Workbook.** Preview the seven-column CSV/XLSX in the restricted workspace.
  Check missing emails, existing matches, and role mappings. Import applies only
  to employee drafts and optionally the HR access queue. The queue still
  requires approval and director fulfillment. Do not store real workbook rows
  in this repository.
- **Recruitment.** Open an approved requisition before adding applications.
  Record interviews and evaluation, then draft and approve the offer. Convert
  an accepted offer once to an employee onboarding case. Record checklist
  evidence and finish the checklist before activating that employee.
  In **Candidate CVs**, select a candidate and upload the confidential file.
  Another HR Manager can download the pending version for review and approve or
  reject it. A replacement keeps the last approved version available until
  review is complete.

  The recruitment API records requisition state changes, records the approval
  actor, and persists `rejection_reason` on the requisition record (omitted
  from `ActivityLog.new_values` so confidential narrative is not exposed in
  broadly visible audit feeds). Offers support an optional `valid_until`
  deadline (valid through `business_today() <= valid_until`), transition to
  `expired` after `valid_until`, enforce optimistic `expected_version_number`
  checks on decisions, and support immutable versioned reissuance
  (`version_number`, `supersedes_offer_id`, `superseded_by_id`, `superseded_at`)
  via `POST /api/v1/hr/offers/{offer_id}/reissue`.
- **Probation.** Set the agreed end date on the direct-hire case or supply the
  approved probation duration when converting an offer. After the checklist is
  complete, start probation from the case. An HR Manager records a reason and
  either extends the period or confirms employment. Confirming an employee
  whose category is still Probation requires an explicit category choice. The
  employment history records the decision and actor. Use Offboarding to handle
  a separation.
- **Files.** An upload creates a pending version. A different HR Manager
  reviews it. Active versions stay available while a replacement awaits
  approval. The API authorizes every download and issues a short-lived URL.
  Employees see only active ordinary versions explicitly shared with them.
- **Time and leave.** HR staff prepare calendars with actual workdays, effective
  dates, an IANA timezone and holidays. A different HR Manager approves, then
  an HR Manager publishes the calendar. Published periods are immutable. Use
  a new code and a nonoverlapping period for the next calendar in the same scope.
  Assign shifts within a published period. The employee schedule lookup prefers
  an assigned shift, then an applicable employee or site calendar, then the
  explicit company default. New attendance records retain the schedule used and
  validate clock-in dates in its timezone. Manual entries can be recorded when
  there is no schedule, with workday and shift information left unknown.
  Attendance CSV import validates the file before applying all rows. An
  authorized supervisor can recommend entries when the policy applies. An
  independent HR Manager approves or returns entries. Attendance and pending
  corrections must be reviewed before locking a timesheet period.
  Staff can submit their own
  leave. Paid balances use an auditable ledger and the approval transaction.
  A cancellation after approval reverses the debit. An employee can cancel their
  own draft or submitted request from My HR before the approval decision.
  If an HR approval or cancellation response is interrupted, reload the request
  and check its saved status and balance. Replaying a committed decision with
  the old revision returns a conflict and leaves the ledger intact.
- **Offboarding.** Record a real separation date and clearance references.
  Where the employee has a linked user, fulfill the deactivation through the
  account queue before closing the case. Closure verifies the director's
  recorded action and that the account is inactive.
- **Letters.** In **Policies & Requests**, save a template, search for the
  employee by name or code, and preview the letter. Employee name, code, join
  date, and employment status come from the employee record. The preview displays
  text for review and records a render audit event. Delivery uses the separate
  service-request or personnel-document workflow.
- **Service requests.** In **Policies & Requests**, start review to assign the
  request to yourself. Enter a response to share with the employee when you
  complete it.
  In **My HR**, employees can reopen their own completed or rejected request.
  Reopening returns it to the unassigned queue and keeps any previously shared
  document and the audit trail.

Run `python -m scripts.garrisonctl hr --help` for available commands. See the
[CLI guide](CLI_ADMINISTRATION.md) for authentication and mutation previews.

## Reporting and reminders

The HR overview and `hr reports summary` accept a primary site, department and
inclusive activity dates. Workforce and open queues reflect current records.
The dates apply to attendance exceptions and deadlines. With activity dates
blank, attendance covers the past 30 calendar days including today, and due
items cover today through 30 days ahead. An attendance exception counts a
recorded absence or half day unless its schedule marks it as a non-working day.
The report uses the configured business timezone and current employee assignments.

CSV, XLSX, and PDF downloads use the same filters and contain aggregate counts
and report dates. They omit department and site names, employee values, and
restricted document categories. Scheduled training stays hidden until the
viewer has the separate training permission.

Credential reminders are opt-in. After the lead time and recipients are
approved, set `HR_REMINDER_WINDOW_DAYS` in the worker and scheduler configuration.
The daily task sends active authorized HR users one generic in-app reminder per
business date when a credential is due in that window. It reads ordinary
credential records and sends no email, document link, employee detail, or count.
An unset value leaves the task disabled.

Service-request reminders are also opt-in. Set `HR_SERVICE_REQUEST_SLA_DAYS`
in the worker and scheduler after HR approves the threshold. Open, in-review
and approved requests count as overdue once that many 24-hour days have passed
since submission. Reopening preserves the original submission time. The daily
task sends each active account authorized to process requests one in-app
reminder per business date. It sends no email, request details or links.

Probation reminders are opt-in through `HR_PROBATION_REVIEW_REMINDER_DAYS`.
The worker and scheduler use the approved lead time and remind active
authorized HR Managers once per business date when a review is approaching or
overdue. The notice contains no employee details. Recording a probation
decision remains a manual action.

## Line-manager review and employee time submission

`HR_LINE_MANAGER_REVIEW_ENABLED` and `HR_SELF_TIME_SUBMISSION_ENABLED` both
default to `false`. Enable only the workflows approved for the deployment.
An HR Manager uses **Authorize line-manager review** on a workforce profile to
grant review to its current direct line manager. The manager needs a current
employee profile and a linked active account. Changing the reporting line
clears the authorization. A new manager must be authorized separately.

When review applies at submission, the manager sees the employee name, dates
and requested units in **My HR → Line-manager reviews** and can recommend the
request or flag it for HR. Leave types, reasons, attachments, notes and rates
remain outside that view. An independent HR Manager makes the final decision.
If an authorized reviewer is no longer available, HR can decide directly. A
previous review cannot satisfy a different reviewer's assignment. Pre-existing
requests keep their original routing.

When employee time submission is enabled, linked staff can submit their own
timesheets and overtime from **My HR → My time requests**. A returned timesheet
can be corrected and resubmitted in the same period. Resubmission clears the
previous recommendation and creates a new review when the policy applies.

## Migration and key custody

Migration [202605310007](../backend/alembic/versions/202605310007_hr_workforce_management.py)
creates HR tables without touching existing account, project or finance records.
Migration [202605310008](../backend/alembic/versions/202605310008_hr_calendar_publication.py)
preserves existing calendars as drafts. Review their dates and timezone before
submission. Migration [202605310009](../backend/alembic/versions/202605310009_hr_attendance_schedule.py)
adds schedule references to new attendance entries and leaves historic records
without a schedule association unless they had one at capture.
Migration [202605310010](../backend/alembic/versions/202605310010_hr_line_manager_review.py)
adds review authorizations and request revisions. Existing requests begin with
no line-manager recommendation requirement.
[202605310011](../backend/alembic/versions/202605310011_retire_hr_executive.py)
guards retirement of the HR Executive role. The cutover does not automatically
promote accounts. [202605310012](../backend/alembic/versions/202605310012_hr_attendance_review.py)
tracks attendance review and correction revisions. The historical marker
preserves entries in already-locked periods without inventing an approval.
[202605310013](../backend/alembic/versions/202605310013_hr_project_assignment.py)
adds the project assignment request table with no backfill and preserves
existing memberships.
[202605310014](../backend/alembic/versions/202605310014_hr_recruitment_followups.py)
adds `hr_requisitions.rejection_reason`, offer validity and versioning columns
(`valid_until`, `version_number`, `supersedes_offer_id`, `superseded_by_id`,
`superseded_at`), self-referential offer foreign keys, and
`ck_hr_offers_version_positive`.
Use the [production maintenance procedure](OPERATIONS_AND_DEPLOYMENT.md#production-maintenance)
to prepare and apply future approved revisions. Production currently runs
revision `202605310013`, so deploying `202605310014` requires that maintenance
procedure. Retain the existing schema and HR records on an
application rollback. A schema downgrade drops HR tables and must never serve
as a routine production rollback.

Set `HR_ENCRYPTION_KEY` to a dedicated Fernet key through the private deployment
environment before recording restricted identifiers. Keep the existing value
in protected key custody, separate from the database and object backup. Key
absence or decryption failure rejects access to encrypted values. Do not derive
the key from the database password, JWT material or object-store credentials.
An isolated recovery must restore the database and the referenced HR object
versions and demonstrate decryption with the recovered key.
A synthetic loopback rehearsal captured and published an authenticated format 2
backup set, then fetched and restored it with the source object service stopped
and the source database closed to new connections. It verified the bytes of
active and superseded HR document versions, authorization after restore, and
decryption of a synthetic identifier. A wrong HR key and a tampered backup
artifact were rejected. Release acceptance still requires the approved off-host
destination, production key custody and an operator-led exercise described in
the [recovery runbook](OPERATIONS_AND_DEPLOYMENT.md#3-operations-backup--restore).

The retention default preserves HR rows and versions. Payroll, statutory
calculation, compensation/benefits, disciplinary cases, performance and training
remain disabled pending policy and authorization. The code assumes no statutory
rates or entitlement schedule.

## Remaining acceptance work

The last pre-cutover configuration inspection was against production SHA
`1399710589f8f2d82bac2e79326bc9b88bbb888d` on 2026-11-15. It showed
line-manager recommendations, employee time submission, and the three
opt-in HR reminders disabled; the scheduler registered none of those optional
reminder jobs. The backend reported an HR encryption key configured. These
settings were not re-read from the deployed candidate in the post-deployment
acceptance check; verify them before enabling or claiming current behavior.
Key custody and recovery remain separate evidence requirements.

- Provision an approved HR Manager account through the authorized account
  process and confirm a secure credential handoff. No HR Manager account was
  active at the last production count.
- Provide the approved employee roster/workbook in the restricted evidence
  store. Resolve missing verified work emails, approve explicit position/job
  title mappings, and review the preview before reconciliation. Link employee
  accounts only through verified work-email identity.
- Name the HR Manager and employee test accounts, define the expected HR
  scenarios and record persisted outcomes. Current production has zero HR
  employee rows, so neither HR Manager workflows nor linked employee
  self-service have authenticated production UAT evidence.
- Approve the attendance source format, line-manager/time-submission settings,
  calendar/timezone/holiday and leave values, reminder windows/recipients,
  retention and clearance owners, and the relevant letter templates.
- Approve key custody and an off-host database/object recovery exercise; retain
  the existing isolated synthetic rehearsal as rehearsal evidence only.
- Deploy pending revision
  [`202605310014`](../backend/alembic/versions/202605310014_hr_recruitment_followups.py)
  via the [production maintenance procedure](OPERATIONS_AND_DEPLOYMENT.md#production-maintenance),
  then repeat focused authenticated HR acceptance checks on the release
  candidate before formal sign-off.
