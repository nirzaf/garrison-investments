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

- **Directory.** Create a draft and record verified work details. Employee edits
  use the displayed record revision. Reporting lines reject cycles and never
  determine project access. An HR Manager reviews activation.
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
- **Offboarding.** Record a real separation date and clearance references.
  Where the employee has a linked user, fulfill the deactivation through the
  account queue before closing the case. Closure verifies the director's
  recorded action and that the account is inactive.
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
Use the [production maintenance procedure](OPERATIONS_AND_DEPLOYMENT.md#production-maintenance)
to prepare and apply it. Retain the existing schema and HR records on an
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

- Approve the line-manager and self-time policies before enabling them in a
  release environment. Live attendance sources require an approved format.
- Approve and verify the reminder window and recipient policy before enabling
  the scheduled job in a release environment.
- Complete workbook reconciliation in the restricted environment. Supply
  missing verified work emails and approve explicit job-title mappings before
  affected accounts can be provisioned.
- Record approved retention, clearance owners and leave/attendance policy values.
  Verify an isolated restore of the database, HR object versions and encryption
  key. Capture HR Manager and operator acceptance for the candidate
  before closing HR release verification.
