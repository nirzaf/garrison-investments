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
| Workforce roster | CODED LOCALLY | In Attendance, HR can plan one published workday or shift per employee and allocate it to a project. The roster retains cancellations and rejects overlaps, including overnight shifts. Revision 037 is pending production activation. |
| Attendance | CODED | HR entry and CSV import, employee correction requests, HR review and period locks. |
| Timesheets and overtime | PARTIAL | HR entry and decisions are available. Employee submission and advisory manager review require the corresponding settings. Payroll processing has no active role grant. |
| Leave and self-service | CODED | HR catalog, policy and ledger functions. Linked employees can view balances, submit requests and use authorized cancellation. |
| Service requests | CODED | Employee submission, explicit HR handoff, response and completion with an optional issued letter, and owner reopening. Overdue reminders require a configured SLA threshold and supporting release. |
| Letters and acknowledgments | CODED | HR Managers can create templates, retain drafts and independently issue letters to linked employees. The workspace also supports policy publishing and My HR acknowledgments. |
| Offboarding | CODED | HR workspace clearance and closure, director fulfillment for linked-account deactivation, and inventory-owner custody receipts. Local revisions 028–032 add store custody, independently reviewed rehire, IT handover and Finance settlement evidence. |
| Reporting | CODED | HR aggregates and filtered CSV, XLSX and PDF exports. |
| CLI | CODED | Registered remote commands use the same API permission boundaries. See [workforce CLI commands](CLI_ADMINISTRATION.md#workforce-administration). |
| Training | CODED | HR Manager manages courses and enrollments and verifies approved employee certificate versions. My HR shows each linked employee their own training and expiry status. Local revisions 033 and 034 retain verification receipts and configure mandatory training by position or site. |
| Performance | CODED | HR Manager opens narrative review cycles. The employee and authorized direct manager acknowledge goals and submit their assessments. HR calibrates the result, the employee acknowledges it, and corrections are retained as addenda. |
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
- **Reviewed employment changes.** In **Directory & Org**, inspect an employee
  and open **Reviewed employment changes**. Propose a transfer (department,
  reporting manager or work location), promotion (position), category
  amendment, or profile name correction. Another HR Manager reviews the
  specific fields and effective date.
  HR applies the approved proposal on or after that date. An intervening employee
  edit requires a fresh proposal. Application adds one dated history entry,
  checks available position headcount, and clears the former manager's review
  authority when the reporting manager changes. Reporting changes leave portal
  roles and project membership unchanged. Current employees' first, last and
  full names use **Profile name correction**. Contact updates use the directory
  or My HR. Private-vault and self-service saves require the revision from
  their last read. After a conflict, reload the latest values before saving.
  Name corrections affect the current employee record and employment history.
  Previously issued letters retain their recorded contents, and linked portal
  accounts keep their existing identity and permissions.
- **Contract renewals.** For an employee in the contract employment category,
  upload the current contract and renewal as separate dated contracts in the HR
  vault. Each needs an approved version. In **Reviewed employment changes**,
  choose the exact versions and a start date one day after the current contract
  expires. The new end date comes from the renewal document. A different HR
  Manager reviews the proposal and can open the exact evidence. When due,
  apply the approved renewal to append the term and evidence to employment
  history. The next renewal starts from the last recorded contract term. If a
  newer renewal-document version is approved before application, submit a fresh
  proposal. Dates in this workflow record reviewed terms. Contract expiry itself
  does not change employment status, payroll or portal access.
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
  an accepted offer once to an employee onboarding case while the requisition
  is open and has a vacancy. The final conversion marks the requisition filled
  in the same transaction. Retrying a successful conversion returns the same
  onboarding case. Use **Mark closed** to end recruitment with vacancies still
  open. Record checklist
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
- **Application shortlist.** Under **Recruitment → Applications and
  interviews**, find applications by candidate name or code and optionally
  filter by stage. Move an applied application to screening, then select
  **Shortlist application** to record the decision. The selected page supplies
  eligible choices in the interview and offer forms. An interview can be
  scheduled after shortlisting. Evaluation requires a completed interview,
  and offer drafting requires evaluation. Open **Application stage history**
  for recorded stage decisions and actors. Existing records already at
  interview or evaluation keep that stage and their earlier history.
  When scheduling, search for an active **Portal interviewer** to send that
  account an in-app invitation. The notification asks the interviewer to
  contact HR for details. It contains no candidate, date, or feedback and
  opens no recruitment record. Cancelling an assigned interview sends a
  similarly limited notice to the interviewer. Leave **No invitation**
  selected for a round without an assigned portal account.
  Use **Candidate offer files** to upload a confidential PDF for a candidate.
  A different HR Manager reviews the upload. Select the approved PDF on the
  offer form. **Download offer file** opens the exact approved version
  attached to that offer. To reissue an offer with a file, approve a
  different PDF and select it for the new offer. The superseded offer keeps
  its original file.
- **Application withdrawal.** Under **Recruitment → Applications and
  interviews**, open **Withdraw application** on the relevant application.
  Record the reason and either the approved retention policy reference and
  review date or the need for a retention policy review. Withdrawal cancels
  scheduled interviews and closes outstanding offers for that application.
  An accepted offer requires a separate disposition. Completed interviews,
  historical offers, the candidate record, the CV and the candidate's other
  applications remain available under their existing permissions. The review
  date is for follow-up. Files remain retained until the authorized records
  process decides their disposition.
- **Candidate rejection correspondence.** Create a **Candidate rejection**
  template under **Policies & Requests** using the approved wording and
  optional `{candidate_name}` and `{position_title}` placeholders. In
  **Recruitment**, reject the application with an internal reason. This
  closes its scheduled interviews and open offers. An accepted offer
  requires separate resolution. Open **Candidate correspondence** to
  prepare a draft. Another HR Manager reviews and approves the retained
  text for manual handoff. Rejected drafts remain in history. The internal
  rejection reason, interview feedback, and candidate contact details are
  outside the template. Approval records a decision without sending mail
  or recording delivery.
- **Files.** An upload creates a pending version. A different HR Manager
  reviews it. Active versions stay available while a replacement awaits
  approval. The API authorizes every download and issues a short-lived URL.
  My HR personnel documents show active ordinary versions explicitly shared
  with the linked employee.
- **Company policy editions.** In **Docs & Compliance**, select
  **Upload company policy file** for a company-wide ordinary file. Another
  HR Manager approves the file version. In **Policies & Requests**, publish
  an edition with its own policy code, edition label, effective date and
  summary. Select the exact approved file or publish a text-only policy.
  To replace an existing edition, select it under **Replaces policy edition**.
  The new edition becomes current on its effective date. Uploading a new
  file version leaves existing publications pinned to their original files.
  Employees acknowledge each required edition in **My HR** and can reopen
  earlier editions they acknowledged. For an old file link with an
  unknown version, HR republishes the approved version after review.
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
  independent HR Manager approves or returns entries. Review attendance,
  pending corrections and overtime before locking a timesheet period.
  Staff can submit their own
  leave. Paid balances use an auditable ledger and the approval transaction.
  A cancellation after approval reverses the debit. An employee can cancel their
  own draft or submitted request from My HR before the approval decision.
  For a draft or rejected request they submitted, they can choose **Edit leave
  request** in My HR, correct the fields and resubmit the same record.
  Rejected requests show HR's reason before editing. Resubmission rechecks
  attachment eligibility and date overlap, uses the current manager-review
  assignment and leaves the balance unchanged until HR approves.
  My HR previews the leave days from the published work schedule. A shift's
  calendar takes precedence for its dates, followed by the employee calendar,
  site calendar and company default. Only workdays that are free of holidays
  count. A permitted half day counts as 0.50 on a single scheduled workday.
  Requests need calendar coverage for every date and must stay within one
  calendar year. HR should publish missing calendar periods before rollout.
  The server recalculates on submit or resubmit and stores the resulting units.
  Existing submitted requests and ledger entries retain their recorded units.
  In **Leave → Leave policy proposals**, an HR Manager enters an inclusive
  effective window and entitlement terms. A different HR Manager approves or
  rejects the proposal. Approved windows for the same leave type and
  employment category cannot overlap. A category-specific policy takes
  precedence over the all-categories fallback. An approved policy must permit
  a negative balance for every date in the requested interval before approval
  can overdraw it. Existing undated approvals remain visible as legacy
  fallback rules and carry no independently reviewed effective dates.
  In **Leave → Post approved leave accrual**, preview an employee, paid leave
  type and closed calendar year or month. A dated, independently approved
  policy must cover the entire period, and employment history must show
  continuous eligibility in one category. Monthly accrual uses differences
  between rounded cumulative totals so twelve months equal the annual
  entitlement. Set **Catch-up end month** to review a range of closed months
  in the same year. The preview shows posted ledger references and days still
  due. An ineligible month prevents posting the range. Confirmation credits
  all missing months together, and an identical retry returns the same ledger
  references.
  Reconcile years with opening balances or manual accruals before using this
  workflow. Policies default to full periods. HR can propose calendar-day
  proration for monthly or annual accrual, subject to independent policy
  approval. The prorated credit is the full period's credit multiplied by the
  fraction of calendar days employed and eligible, rounded to two decimals.
  The join date counts, and the recorded termination date does not. One
  approved policy still has to cover the full requested period. The employee
  must have continuous eligible history in one category for the credited
  dates. The preview and receipt show the credited date range.

  Scheduled posting is disabled by default. After HR has approved and
  selected dated policies for automation, configure
  `HR_SCHEDULED_LEAVE_POLICY_IDS` as a JSON array of those policy UUIDs in
  both Celery worker and beat. The daily 05:15 UTC job considers the latest
  closed business month and the prior calendar year. It applies the same
  eligibility and balance checks as a manual posting. If a different policy
  applies to an employee, that policy must be selected separately. Older
  missing periods use the existing catch-up workflow.
  The job reports aggregate posting and blocked counts. Each credit has
  a ledger receipt and a scheduled audit event. Set the array to `[]` to
  disable future automatic credits.
  In **Leave → Review year-end leave rollover**, reconcile posted accrual,
  outstanding leave and both years' balances before previewing the transfer.
  The dated policy effective on 31 December sets the carry cap. Excess days
  expire only when that policy explicitly authorizes year-end expiry. The
  preview uses the posted ledger and does not calculate missing accrual.
  Confirming the preview posts the transfer and expiry together and closes
  the source year for the selected employee and leave type. A later change
  to a closed year requires an audited correction workflow.
  If an HR approval or cancellation response is interrupted, reload the request
  and check its saved status and balance. Replaying a committed decision with
  the old revision returns a conflict and leaves the ledger intact.
- **Performance reviews.** HR creates the review cycle and drafts the goals in
  **Performance**. Before opening the draft, link the employee and authorize
  their current direct manager through the employee directory. The employee
  and manager use **My HR → Performance reviews** to acknowledge the retained
  goals, record progress and submit their respective assessments. HR calibrates
  the review. The employee sees the assessment at that stage and acknowledges
  the final text. HR can append corrections to the closed record. This workflow
  uses narrative assessments by default. To use ratings, enter the agreed
  scale when creating the cycle. The employee, manager and HR choose from those
  labels. HR records the final label during calibration. The portal applies no
  default weights or scoring formula.

  If the direct manager changes before calibration, authorize the replacement
  in the employee directory, then use **Hand off to current manager** on the
  review and record the reason. The replacement acknowledges the goals and
  submits a separate assessment. The employee’s submission is retained and
  the former assessment stays in HR history. Published reviews keep the
  original handoff and assessment history.
- **Training.** In **Training**, create a course and enroll a current
  employee. Upload their ordinary training-certificate PDF with the issue date
  and optional expiry. A different HR Manager approves the file version in
  **Docs & Compliance**. Choose that exact approved version and the completion
  date, then verify the enrollment. Refresh the training view if approval was
  recorded in a separate session. A renewal uses a new enrollment and new
  approved evidence. Existing receipts retain the exact version used at
  verification. **My training** shows the linked employee’s own completion
  and expiry dates.
  Open **Mandatory training rules** to require a course for a job position,
  primary project site, or both. A combined rule requires both to match. Rules
  show the current requirement to HR and to the linked employee. Overlapping
  rules show one requirement per course. A valid verified certificate meets it,
  an open enrollment shows Enrolled, and an expired certificate without a new
  enrollment shows Expired. Rule changes leave enrollment and certificate
  history intact.
- **Offboarding.** Record a real separation date and clearance references.
  Where the employee has a linked user, fulfill the deactivation through the
  account queue before closing the case. Closure verifies the director's
  recorded action and that the account is inactive. Open **Inventory custody
  evidence** and give the inventory owner the case ID. The owner records receipts
  against posted stock returns, then attests that custody is cleared or explicitly
  waived. A flag or newly recorded return requires fresh sign-off. Use **Refresh
  custody evidence** to reload the receipts and clearance before closing. Legacy
  completed cases keep their history. Open cases with legacy clearance require
  the inventory owner's attestation. The inventory owner verifies the physical
  handover and records exceptions under the approved operating process.
  For IT clearance, give a director the case ID from **IT handover evidence**.
  The director opens **Access & Workbook → Offboarding IT handover** and records
  an opaque evidence reference for each returned or outstanding device.
  An unresolved device requires a return or a documented exception specific to
  that device. The director signs off after all devices are resolved and any
  linked portal account has a verified deactivation. This sign-off attests
  to external credentials and custody handled by the operator. HR can inspect
  the receipts and close the case after sign-off.
  For Finance clearance, open **Finance settlement evidence** and give a
  director with Finance access the case ID. In **Access & Workbook**, open the
  case, then propose the externally verified outcome and enter an opaque
  evidence reference. A different director approves or rejects the current
  proposal with a review reference. An approved outstanding balance, a rejected
  record or a pending proposal blocks closure. An approved reconciled settlement
  or nothing due clears Finance. A newer proposal reopens that clearance and
  requires review. HR can view the receipt before closing. Keep monetary
  calculations, advance details and payment proof in the controlled Finance
  record. The portal retains the reviewed outcome and its references.
- **Rehire.** At offboarding closure, record the approved rehire eligibility.
  In **Directory & Org**, inspect the former employee and open **Reviewed
  employment changes**. Propose rehire against the latest eligible separation
  with a new start date and category. A different HR Manager approves it. Apply
  the approved proposal on or after its start date. The returning employee retains
  their employee code and historical records and starts a fresh onboarding
  checklist. Review their current assignment and any remaining portal project
  memberships before initiating a new access request for director fulfillment.
  The recorded periods show the original end date and the new start. A missing
  historical start remains unrecorded.
- **Letters.** In **Policies & Requests**, save a template, search for the
  employee by name or code, and preview the letter. Employee name, code, join
  date, and employment status come from the employee record. Save the preview
  as a draft for independent review. A different HR Manager selects the employee,
  opens the saved letter and issues it or rejects it with a reason. If employee
  data changed, prepare a new draft. Issued letters appear in **My HR → My issued
  HR letters** for the active linked recipient. Saved text and rejection reasons
  are encrypted with the HR key. Salary confirmation remains preview-only
  pending an approved compensation source. Portal issuance creates no electronic
  signature or external delivery.
- **Service requests.** In **Policies & Requests**, starting an unassigned
  review claims it. Use **Assign request** or **Reassign request** to hand an
  open, in-review or approved request to an active HR user. Enter an operational
  reason without employee details. The audit saves the actor, previous and new
  assignees, and reason. Handoffs preserve the current status and response.
  The current assignee starts review or completes an assigned request. Use
  **Attach issued letter** to preview and attach an already-issued letter for
  the same employee during completion. In **My HR**, the employee can open
  that exact letter from the request and reopen a completed or rejected request.
  Reopening returns it to the unassigned queue and keeps any previously shared
  document or letter and the audit trail.

Run `python -m scripts.garrisonctl hr --help` for available commands. See the
[CLI guide](CLI_ADMINISTRATION.md) for authentication and mutation previews.

## Payroll verification

An authorized payroll preparer can preview time inputs for an explicit roster
and payroll period of up to 31 days, then download the reconciled CSV using
the preview digest. One row represents one locked timesheet. Attendance is
checked for outstanding review and retained schedule evidence. Approved
overtime must match the hours on its timesheet and is counted once. The
preview lists blocking record IDs and issue codes. It does not infer missing
days from a partial timesheet or calculate pay. Review roster and date
coverage before using the extract, and investigate legacy locked records
with inconsistencies through the approved correction process.
[CLI commands](CLI_ADMINISTRATION.md).

Payroll permissions have no active portal role grant. The protected run API
supports review of a fixed-base monthly calculation. A policy must explicitly
declare `calculation_basis: base_salary_only`, `pay_frequency: monthly`, a
three-letter uppercase `currency`, `rounding` as `half_up` or `half_even`,
and `employee_deduction_rate` as a decimal string from zero to one. A
second actor must approve the policy. These fields are configuration inputs,
and approved worked examples are still required for live adoption.

Calculate an empty draft for a closed month using the explicit employee
roster. Each employee needs complete eligible employment history and a
whole-period approved monthly term in the policy currency. Mid-period
changes, missing or ambiguous terms, and allowances outside this formula
stop calculation. The run preserves the approved policy reference, source
term IDs and encrypted lines. An authorized reviewer reads the protected
snapshot and reconciles gross, deductions and net. A different approver
confirms the same snapshot digest. Approval locks the period against a
competing run. Protected readbacks are audited.

After approval, the reviewer can explicitly publish payslips for that exact
locked snapshot. The linked employee opens their own statement in
**My HR → My payslips**. Before publication, the run is absent from the
employee's list. The statement shows the scheduled pay date and the
published gross, deductions and net. It does not acknowledge payment or
send email. Access is checked on every request and each statement view
is audited.

The approver can register a Finance handoff from the locked snapshot after
reviewing the totals and exact CSV digest. The protected CSV contains opaque
payment references, currency and positive net amounts. Zero-net lines are
counted in the preview and excluded from the file. The protected payroll
snapshot retains the employee-to-reference mapping for an authorized
reconciliation. Retain the receipt and verify the checksum at handoff.

After payment execution outside HR, an authorized operator records the
result against the exported payment reference and approved CSV digest.
Each source event needs a stable UUID and a unique opaque evidence
reference. A failed attempt records zero. A successful event can cover
part or all of the outstanding amount. A reversal references the original
successful event and can only reverse its unreversed balance. Retries
return the same event and cannot duplicate the recorded payment. The
summary reports recorded net paid and outstanding amounts. A reversal
can reopen a previously reconciled balance.

The CSV is an internal handoff. Bank format selection, recipient mapping,
operator authorization, actual execution, closure sign-off, and approval
of earning or deduction rules for allowances, time or statutory items
remain pending.

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
since submission. Reassignment and reopening preserve the original
submission time. The named active, authorized assignee receives reminders for
their assigned requests. Unassigned requests and those with an unavailable
assignee remain in the shared reminder queue for eligible HR users. The task
sends at most one in-app reminder per recipient per business date, with no
email, request details or links.

Probation reminders are opt-in through `HR_PROBATION_REVIEW_REMINDER_DAYS`.
The worker and scheduler use the approved lead time and remind active
authorized HR Managers once per business date when a review is approaching or
overdue. The notice contains no employee details. Recording a probation
decision remains a manual action.

## Workforce roster

In **HR & Workforce → Attendance → Workforce roster**, search for an employee
and project, enter the allocation date, and select **Allocate shift**. The
employee's published calendar determines whether the date is a workday. A
published shift provides its scheduled interval and elapsed hours. Without a
shift override, the roster uses the calendar's start, end, and configured
daily hours. The selected project is the planned work location.

Use **View roster** with a date range of up to 31 days to review active and
cancelled allocations. To correct an allocation, cancel it with a reason and
create the replacement. Each row retains its originally planned times, hours,
calendar, and shift. The roster records planning only. Project access,
attendance, stock transactions, and payroll remain separate workflows.

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
decryption of a synthetic identifier. The revision 042 drill also recovered
distinct receipts and exact PDF bytes for current and superseded policy editions
and decrypted independently approved candidate correspondence. A wrong HR key
and a tampered backup artifact were rejected. Release acceptance still requires the approved off-host
destination, production key custody and an operator-led exercise described in
the [recovery runbook](OPERATIONS_AND_DEPLOYMENT.md#3-operations-backup--restore).

The retention default preserves HR rows and versions. Payroll, statutory
calculation, compensation/benefits and disciplinary cases
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
