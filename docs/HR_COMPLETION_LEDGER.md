# HR completion ledger

This ledger reconciles the two HR completion prompts by capability (P01–P16).
The historical HR IDs below refer to the matching requirements in the local
*Garrisons HR Atomic Implementation Spec*, section 7. The separately named
`Garrisons_HR_Full_Atomic_Implementation_Spec.md` was unavailable. The local
spec is restricted because its appendix contains staff data. Its earlier
two-role proposal is superseded by the single HR Manager decision.

## Baseline

### Current 60-finding implementation candidate (2026-11-26)

- Preflight started from local `main` at
  `7203f00f0bf504d563d63b6090c848b8da51a5e0`; `origin/main` matched this SHA at
  preflight and still matched at final review. The initial single Alembic head
  was `202605310114`.
- The pre-existing local changes were the user's `docker-compose.yml` edit and
  Celery schedule `-shm`/`-wal` sidecar files. They were preserved. The feature
  candidate is also uncommitted; its additive schema change is revision
  `202605310115`. No production account, data or host was accessed from this
  implementation task.
- The Slice 102 paragraphs below are historical evidence for their stated
  revision and test environment. They are not exact-candidate or live
  production verification for this work.

- Historical baseline for Slices 1–101: clean main worktree at
  `ec298833ccffccabf65916202894736f494a72a4`, matching
  the local `origin/main` reference and the supplied GitHub baseline. No staged,
  unstaged or untracked work was present before the changes below.
- Alembic source head `202605310014`. An empty loopback PostgreSQL 18 test
  database upgraded to head with Python 3.14.7. The frontend tooling ran on
  Node 26.13.0 locally. The hosted CI definition pins its own tool versions.
- Slice 102 resumed on `main` at `60836daac4b77fe8cf6ba7fff206bfcc6bb343a0`
  with an existing uncommitted HR implementation and migrations 113–114.
  The unrelated local Compose edit and Celery schedule sidecar files were
  preserved. The Slice 102 candidate remains uncommitted and local.
- Production activation and business acceptance are separate from the local
  engineering work below. See the [workforce guide](HR_WORKFORCE.md) for the
  last verified deployed revision and the [maintenance runbook](OPERATIONS_AND_DEPLOYMENT.md#production-maintenance)
  for the next deployment.

## Requirement register

| Packet and historical source | Local evidence and engineering status | Remaining behavior or input and acceptance check |
| --- | --- | --- |
| P01 · HR-001–004, HR-007 · organization and employee records | **Implemented and locally verified for directory, profile and name-correction workflows.** Current employees' name corrections use independent review. Private-vault and My HR edits verify the same employee revision. See Slice 27. | Verify business use of older employment periods with missing start dates. Operational use requires authorized accounts and dedicated encryption key custody. |
| P02 · HR-005/006 · workbook and access | **Implemented paths; unverified live.** `hr_workbook.py` previews and applies drafts, and the HR access workflow uses the user service for director fulfillment. Browser and CLI expose the workflow. See `test_hr_c_three_party_access_requests_and_session_revocation` and `test_hr_d_workbook_preview_and_idempotent_apply`. | The recovered account-role workbook matches the supplied digest. Its identity and role dispositions remain in the restricted reconciliation plan. Verify the approved personnel roster, account identities and final access outside Git. Verify retry creates no duplicate draft/request and neither linking nor a reporting line adds project access. |
| P03 · HR-008–011 · recruitment and onboarding | **Portal and CLI workflows verified locally.** Requisitions, CVs, applications, interviews, offers and onboarding are available in both interfaces. Offer versions can pin reviewed confidential PDFs. Internal interview invitations and cancellations use generic in-app notices. The terminal also records onboarding checklist and probation decisions. See Slices 28–30 and 33–41. | Verify with approved release test records. Confirm operational retention and correspondence wording. |
| P04 · HR-002/011 · employment changes | **Partial.** Reviewed transfers, promotions, category amendments and version-bound contract renewals apply on or after their effective date with one history entry. The portal and CLI list due changes and flag mismatched employee revisions. Manager transfer clears the former review authority. `HRProbationReview` handles confirmation and extensions. | Reviewed rehiring now records a new period and onboarding checklist. An approved automatic activation schedule and production business acceptance remain open. |
| P05 · HR-007/013 · workforce planning | **Implemented and locally verified for whole-shift allocations.** `HRWorkCalendar` resolves published calendars and shifts. The portal and CLI allocate the resolved shift to a project and keep cancellation history. `hr_project_assignment.py` handles project access separately. See Slices 25 and 71. | Verify representative rosters with the business before production activation. The local workflow assigns a single published workday or shift per employee and date. |
| P06 · HR-014/015 · attendance and time | **Implemented and locally verified for time capture, review and locked time export.** The payroll preparer can preview and export reconciled time for an explicit roster. Pending overtime prevents timesheet lock. The CSV preview shows overnight clock offsets and blocks incomplete clock pairs. See Slices 26 and 100. | Confirm the company's attendance feed and approved missing-punch handling before rollout. Employee submissions and manager recommendations need approved opt-in settings and verified links. Production payroll authorization and roster coverage review remain open. |
| P07 · HR-016/017 · leave | **Implemented in source; locally verified on Slice 102.** Managed annual/casual profiles enforce first/second/third service-year rules, the reviewed 4–14 day annual bracket contract, zero carry-forward, annual block accounting and opening-balance reconciliation. The assigned current direct supervisor is the final reviewer; HR retains visibility and uses reasoned fallback only when eligible. Portal/email events are revision-scoped. See Slices 42–45, 66, 69, 73 and 102. | No managed policy is active by default. HR must supply and independently approve the 366 second-year annual bracket values, confirm the calendar-year/service-start and rehire conventions, approve the seven-day-block basis and effective windows, set leave-type paid/evidence rules, publish work-calendar coverage, reconcile employee opening balances and configure any sick/maternity rules. Local automated verification passed; the candidate remains uncommitted, and production deployment/readback and business acceptance are unverified. |
| P08 · HR-012/018 · documents, policies and letters | **Versioned files and policy editions implemented and locally verified.** Policies link to the exact approved files and maintain separate acknowledgement receipts after replacement. `HRLettersPanel` keeps encrypted drafts for independent issuance. Salary confirmations bind the current independently approved compensation term. See Slices 31 and 72. | Reconcile any legacy policy file links. Confirm the production templates, compensation records and authorized reviewers, retention and any delivery to former employees. |
| P09 · HR-018 · service requests | **Implemented and locally verified for handoffs and response letters.** HR can assign active requests, the assignee can complete one with a same-employee issued letter, and overdue reminders follow the eligible assignee. My HR keeps the exact letter visible on reopening. | Confirm the live SLA threshold and routing. Verify representative sensitive responses and templates with business UAT. |
| P10 · HR-021/022 · compensation and obligations | **Implemented for restricted operator workflows.** The directory supports capped policies, dated coverage, private receipt review, reimbursement approval and external settlement. Advances track external disbursements and repayments through the API, CLI and directory. Compensation has independent review and effective-date history. See Slices 46–55. | Verify business policy and duties, reconcile legacy claims, and confirm payout mapping and recovery policy before activation. |
| P11 · HR-023 · payroll and settlement | **Partial and role gated.** The payroll portal proposes and independently approves monthly policies tied to a controlled record with validated worked examples, captures reviewed earnings and deductions, prepares an explicit-roster run, and rechecks compensation and attached time and leave evidence when approving the frozen snapshot. The portal, API and CLI publish or expose payslips, register an internal Finance export and reconcile external outcomes. A separate reviewer closes the locked period after payslips and reconciliation. See Slices 56–64 and 74–77. | Supply the actual approved policy and worked examples. Agree and implement Finance execution, recovery and replacement statement handling for reviewed corrections. Verify payout mapping, currency, authorized operators and production reconciliation. |
| P12 · HR-019/020 · development and learning | **Implemented and locally verified.** HR configures mandatory training, verifies exact certificate versions and opens participant-scoped reviews with optional cycle ratings. Employees and authorized managers acknowledge goals and submit assessments. HR records handoffs, calibrates and appends corrections. See Slices 21–24. | Supply the company’s approved cycle labels where ratings are required. Verify production reminder routing and business acceptance. |
| P13 · HR-024 · employee relations | **Partial and role gated.** Case reads and updates are opener-scoped, linked subjects cannot handle their own case, and new resolution notes use the HR vault. | Confirm investigator, reviewer and appeal authority before adding those workflows. Case-linked evidence and business acceptance remain open. No production role is granted the case permission. |
| P14 · HR-025 · separation and custody | **Implemented and locally verified.** Offboarding requires director access cutoff, IT handover, inventory custody and independent Finance settlement review. Explicit rehire preserves prior periods and uses independent approval. See Slices 17–20. | Verify physical handover, settlement evidence policy, director assignments and authorization in business UAT. Production activation remains open. |
| P15 · HR-026–028 · reporting and CLI | **Partial.** `hr_reporting.py`, `HRSummaryPanel` and `garrisonctl_hr.py` cover aggregate exports and multiple HR administrative workflows, including recruitment, time records, document decisions, work calendar review, roster allocation and reviewed compensation. See Slices 65 and 68–71 for recent coverage. | Compare the remaining terminal coverage with the accepted lifecycle workflows. Verify read/preview/apply/readback, actor-bound plans, export totals and field scope. |
| P16 · HR-029/030 · reliability and handover | **Synthetic recovery verified; operational acceptance pending.** HR reminders use existing tasks. Isolated restores at revision 042 and 057 recovered encrypted HR records, exact file versions and payroll evidence. See Slices 32 and 64. | Run the recovery and migration procedure with the approved off-host destination, key custody, retained data and measured recovery targets. Record retention policy and business acceptance separately. Preserve retain-only audit mode and technical CI/CD. |

Paths in the [workforce guide](HR_WORKFORCE.md#core-workflows) lead to the router,
services, frontend and role definitions. [CLI administration](CLI_ADMINISTRATION.md#workforce-administration)
owns the command reference.

## Authority to preserve

| Duty | Current boundary |
| --- | --- |
| Employee | Active linked account acts on its own eligible records. |
| Leave decision | The current linked direct supervisor makes the final leave decision for their direct report. HR Manager has leave visibility and uses the existing HR approval grant for an explicitly reasoned supervisor-unavailable fallback. Other time recommendations remain advisory. |
| HR processing and independent review | HR Manager acts under the existing action-specific grants. Where independent approval applies, the second actor must be distinct. Directors fulfill approved account handoffs through the user service. |
| Payroll preparation, approval and settlement | Separate duties require approved actor assignments and policy. Current roles have no payroll grant. |
| Confidential case participation | No active role grant. An approved design also needs record-level participant and conflict checks. |

## Slice 1 · enforce vacancies at offer conversion

P03 / historical HR-008 headcount consistency and HR-010 one-time conversion.
Use the existing conversion endpoint and browser action. Serialize decisions
on the requisition row after taking the application and offer locks in the
order used by reissue. Count persisted hired applications. A successful final
hire changes the requisition to filled and records an audit event in the same
transaction as the employee and onboarding case. Held or closed requisitions
reject conversion, and an early manual filled decision is rejected. A retry
of a converted offer returns its existing case.

The service is in `backend/app/services/hr_workforce_service.py` and the browser
action is in `frontend/src/pages/hr/HRHiringPanel.tsx`. The additive offer-detail
endpoint uses the same recruitment permission as the existing offer list.
`garrisonctl hr offers status` and `convert` use it for a minimal status view,
an actor-bound plan, and readback after conversion. See the
[CLI guide](CLI_ADMINISTRATION.md#workforce-administration). Conversion clients
keep the same request and response fields. This slice requires no new migration. Existing
historical over-capacity rows or incorrectly filled requisitions need a reviewed
read-only reconciliation before any correction.

Acceptance requires one success and one capacity conflict on concurrent
authenticated conversions for the final vacancy, one hired application,
identical case and employee IDs on replay, a 403 for a non-HR actor, and a
Chrome reload that still shows filled and converted.

The pre-fix API regression reproduced two HTTP 200 conversions for one
vacancy. The post-fix test also exercises premature filled, hold/reopen and
authorized status readback. The CLI regression covers stale plan refusal,
private note omission and confirmed status after apply with a mock transport.

Local verification on 16 November 2026 used isolated PostgreSQL 18.6,
Redis 8.10.1, Moto 5.2.2 and Google Chrome 157.0.8103.79:

- `pytest -q -rs tests/test_hr.py tests/test_hr_attendance_import.py tests/test_permissions.py tests/test_openapi_contract.py --tb=short`
  passed 50, with zero skips and a Celery deprecation warning.
- Backend Ruff lint, mypy and OpenAPI check passed. Frontend ESLint,
  generated API type check and build passed. `npm test` passed 50.
- `npm run test:browser -- --grep 'multi-headcount requisition' --workers=1`
  passed in Chrome. The scenario converted an accepted offer, verified the
  filled requisition after reload and checked the real CLI status before
  and after conversion through the isolated API.
- Full repository CI, populated backup upgrade rehearsal and production
  acceptance have no execution result for this uncommitted slice.

## Slice 2 · employee leave correction and resubmission

P07 / HR-017. My HR edits employee-submitted drafts and rejected requests
through `PUT /api/v1/hr/me/leave-requests/{request_id}/submission`. The
endpoint matches the active employee and original submitter, verifies the
record revision and repeats creation validation. It locks the request and
employee, retains the request ID, resets the current decision and
recommendation fields, and audits the status transition without copying
private reasons. Prior status transitions remain in the audit trail.
The existing ledger is affected only by the later HR decision.

`test_manager_recommendations_are_scoped_advisory_and_revision_checked`
exercises original-submitter scope, foreign employee payload rejection,
cross-year validation, concurrent resubmission, a fresh recommendation and a
single approval debit and reversal. No new database migration is required.
The same isolated backend command recorded for Slice 1 passed 50 tests with
zero skips. Frontend lint, generated contracts, 50 unit tests and build passed.
Chrome passed `npm run test:browser -- --grep 'a linked employee manages their own leave' --workers=1`.
It exercised rejection feedback, prefilled correction, same-ID persistence
after reload and cancellation.

## Slice 3 · calendar based leave units

P07 / HR-016 and HR-017. The self-service and HR quote endpoints calculate
leave days for the same dates used to submit or resubmit. A single bounded
PostgreSQL query resolves the applicable published calendar for each date,
including assigned shifts, with holidays excluded. The server fails closed
for missing coverage, ranges with no workdays and requests spanning two
years. A valid half day counts as 0.50. A supplied total is an assertion
against the schedule. The browser shows the quote and the CLI binds it to
the dry-run plan.

Rollout requires published work calendars covering the dates employees can
request. No database migration is required. Already submitted requests keep
their recorded units, including historical submissions that permitted a
caller-supplied total. Review unresolved historical requests through the
existing HR decision workflow before posting their ledger effects.

Local verification used disposable PostgreSQL 18.6, Redis and Moto. The
HR, attendance import, permission and OpenAPI suites passed 50 tests with
zero skips. The CLI plan test passed separately with a mock transport.
Frontend lint, generated types, 50 unit tests and build passed. The Chrome
leave regression passed against the isolated API and checked the displayed
quote, correction, resubmission and persisted record after reload.

## Slice 4 · effective dates and independent leave policy review

P07 / HR-016. HR Managers can propose a dated policy and a different HR Manager
can approve it or reject it with a reason. The API serializes approvals by
leave type and rejects overlapping inclusive windows for the same category.
Leave approval resolves the applicable category and date rules for every day
of the request before allowing a negative balance. Approved windows are
immutable in the portal. The browser and CLI use the same workflow.

[Revisions 015](../backend/alembic/versions/202605310015_hr_leave_policy_review.py)
and [016](../backend/alembic/versions/202605310016_validate_hr_leave_policy.py)
preserve older rows as legacy policies with their original approval metadata.
Existing approved legacy policies remain fallback balance rules. Accrual
will require a dated approval. Rehearsal on PostgreSQL 18.6 upgraded a
synthetic legacy approval from 014, validated the constraints, preserved the
15-day entitlement and rejected an undated insert from an old writer.
The application and schema require a coordinated maintenance rollout.

The isolated HR, attendance import, permissions and OpenAPI suites passed
50 tests with zero skips. They exercised self-review denial, concurrent
overlap rejection, adjacent windows, rejection and balance enforcement across
a policy boundary. The CLI proposal and independent review test passed with
a mock transport. Frontend lint, generated types, 50 unit tests and build
passed. Chrome verified draft creation, absence of a creator approval
control, independent review and persisted approval after reload in
`npm run test:browser -- --grep 'a linked employee manages their own leave' --workers=1`.

## Slice 5 · reviewed posting for closed accrual periods

HR can post one closed month or year using a dated, independently approved
policy and complete employment history for the entire period. The browser
and CLI show the server's calculation and require explicit confirmation.
The ledger credit and [receipt](../backend/alembic/versions/202605310017_hr_leave_accrual.py)
are written in one transaction under the employee lock. An exact replay
returns the same receipt, and overlapping periods or years with unreconciled
opening balances or manual accruals are rejected. A manual opening balance
or manual accrual is also rejected after policy-backed posting starts.
Monthly rounding reconciles to the annual amount.

Local PostgreSQL verification covered review authority, partial or future
periods, mixed frequencies, actor mismatch, concurrent retries and
balance reconciliation. The focused HR, attendance, permissions and
contract suite passed 52 tests with zero skips. Frontend lint, generated
types, 50 unit tests and build passed. Chrome previewed and posted annual
accrual and the CLI read back its receipt against the isolated browser API.
The 016-to-017 rehearsal preserved the seven existing ledger rows and their
18.00-day total in a disposable database.

## Slice 6 · year-end rollover and explicit expiry

HR previews and posts the balance for one employee and paid leave type for
a completed year. The dated closing policy sets the carry cap and must
explicitly authorize expiry above it. The transfer debit, matching credit,
expiry debit and receipt commit together. Source-year closure blocks late
requests and ledger changes. An exact retry returns the existing receipt,
and stale amounts, pending leave, destination opening balances and duplicate
manual carry are rejected. The preview only uses posted entries and HR
must reconcile missing accrual before confirming.

[Revision 018](../backend/alembic/versions/202605310018_hr_leave_rollover.py)
preserved the 11 existing ledger rows, 27.68-day total and two accrual
receipts when applied to an isolated 017 database. Existing policies
defaulted to expiry disabled. No production migration was run.

## Slice 7 · monthly accrual catch-up

The leave workspace and `garrisonctl hr leave accrual post` can preview an
inclusive range of closed months for one employee, paid leave type and
calendar year. The preview includes posted receipts and only totals credits
still due. It requires eligible employment and dated approved rules for
each missing period. Apply binds the preview to its actor and range,
commits missing credits together and returns persisted receipts on retry.
No database migration is required for catch-up.

Verification on a freshly migrated disposable PostgreSQL database: 52
targeted backend tests passed, including role denial, stale range, a
rollback after both new credits were staged and concurrent replay. All
50 frontend unit tests passed. The Chrome scenario posted 12 months,
confirmed 12 distinct receipts through CLI preview, and used that balance
in the year-end rollover and subsequent leave workflow. Backend typing,
lint and generated API contract checks passed.

Automatic scheduling, approved partial-period rules and broader HR
acceptance are still open.


## Slice 8 · retained HR letters

A preview binds employee revision, template, exact text and preparing HR
Manager. A retained draft encrypts its content using the HR key. A
different HR Manager reviews that immutable snapshot and issues it to a
linked employee with an active portal account or rejects it with an
encrypted reason. The employee sees only issued letters tied to their
current employee profile. The audit event includes record references
and actor, with no letter contents. The workspace and CLI support
preview, draft, decision and readback.

[Revision 019](../backend/alembic/versions/202605310019_hr_issued_letters.py)
was rehearsed on an empty database and an isolated populated revision
018 clone. The populated upgrade preserved 39 employee records, one
template, and 18 leave-ledger records and created an empty letter
register. A downgrade rehearsal with two retained letters refused to
drop the table and left both letters intact.

All 52 targeted backend tests and 50 frontend unit tests passed. Chrome
verified independent issuance, owner retrieval after reload and CLI
list/show, and reran the employee leave and rollover scenario. The API
tests verified duplicate decisions, stale employee revisions, encrypted
storage, rejection, and metadata-only audit records. The CLI write
commands were checked by lint and typing and use those same endpoints.

Production was untouched. Approved salary source, company
letter acceptance, retention, and former-employee delivery remain open.


## Slice 9 · service request handoff

Eligible processors select an active HR assignee and record an operational
reason. The assignment changes under a row lock with an expected timestamp.
Handoffs preserve status, original submission timestamp and shared response.
The audit records both assignees and the reason. The next overdue sweep routes
generic in-app reminders to the current eligible owner, or to all eligible
processors for an unassigned or unavailable owner. Reminders stay opt-in and
deduplicate per recipient and business date.

All 52 targeted PostgreSQL-backed backend tests and 50 frontend unit tests
passed. The API tests verified concurrent assignment, permission and audit
behavior, and the SLA tests verified transfer, deduplication and fallback
routing. Chrome verified a UI handoff, completion by the new assignee, owner
reopening, then CLI preview, apply and API readback for assignment of the
reopened request. No database migration is needed for this slice.


## Slice 10 · issued letter delivery from a service request

Completion can reference a previously issued letter for the same employee.
The reference and completion are committed together with an audit event
containing the prior and new IDs. Assignments and employee reopening preserve
the reference. My HR opens the exact retained snapshot through the existing
owner-only letter API. Drafts and letters from another employee are rejected,
and the selected attachment requires the current request timestamp.

[Revision 020](../backend/alembic/versions/202605310020_hr_service_request_letter.py)
adds the nullable reference. [Revision 021](../backend/alembic/versions/202605310021_validate_hr_request_letter_fk.py)
validates the foreign key. An isolated populated revision 019 clone preserved
all three existing requests and two retained letters. The migration left
all existing response references unset. On a separate test database a
downgrade refused to drop the reference after an attachment was made.

Chrome verified the assigned HR user's letter preview and attachment,
employee retrieval after reload, and reopening without losing the
response. It also verified CLI dry run, apply and readback when
completing the reopened request with the same issued letter. The
separate employee leave and service-request handoff regression passed.
The focused PostgreSQL suite and frontend unit suite passed.


## Slice 11 · effective-dated employment changes

HR proposes a transfer, promotion or category amendment from the employee
detail. A second HR Manager reviews the immutable proposal. Applying a due
approved change rechecks the employee revision, target and position headcount,
updates the employee and records the dated history and audit together. An
exact application retry returns the retained outcome. A reporting-line move
clears the advisory reviewer grant and preserves portal and project access.
The directory still supports immediate authorized contact updates. See Slice 27
for the subsequent reviewed name-correction workflow.

[Revision 022](../backend/alembic/versions/202605310022_hr_employment_changes.py)
preserved 40 employees, 44 history rows and one service response-letter link
when applied to an isolated populated revision 021 clone. The downgrade guard
preserved five proposal rows in a separate populated 022 trial. No change
was deployed.

All 53 focused backend tests and 50 frontend tests passed. The backend
suite covered denial, future-date enforcement, stale rejection, promotion
capacity, concurrent replay, and the reporting-line grant change. Chrome
verified the transfer through separate proposer and reviewer sessions and
confirmed CLI proposal, approval, application and readback for a category
amendment. The independent letter/response workflow also passed its Chrome
regression.


## Slice 12 · reviewed contract renewals

Contract renewals reuse the dated employment proposal and approval flow.
The selected contract documents must belong to the employee and each
must carry the specified reviewed version and expiry. The renewal starts
one day after the current term ends. Approval and application recheck
the exact versions under document locks. Application retains the term
dates and evidence references in the proposal and employment history.
Later renewals must start from the last applied term. No new migration
or role permission is required. Renewal expiry records a date and does
not drive separation or payroll calculations.

The 54-test PostgreSQL-backed suite covered pending and foreign evidence,
date mismatch, version supersession, latest-term enforcement, and exact
apply replay. Production was untouched.

Chrome verified contract evidence selection, approval by a second HR
Manager, due-date application, and exact version and expiry readback
from employment history. Two Chrome scenarios and 50 frontend unit
tests passed. Backend typing, lint, API contracts and the frontend
production build passed.


## Slice 13 · frozen payroll review

The protected API and CLI support an explicit roster for a closed monthly
period. The calculation selects the approved whole-period term effective
for each worker, uses policy-declared currency and rounding, and freezes
the policy inputs and encrypted lines. A retry uses the stored snapshot.
An independent reviewer can read the protected amounts and approve the
exact digest. Approval rechecks line integrity, blocks overlapping
approvals, and locks the period. No portal roles gained payroll permission.

[Revision 023](../backend/alembic/versions/202605310023_hr_payroll_snapshot.py)
preserved the 46 employee records and eight employment-change records on a
populated disposable clone. Legacy runs receive no inferred snapshot.
Synthetic permission tests verified calculation, independent approval,
rounding, protected read, altered-line rejection and competing runs.
CLI plan and readback were tested against a mocked API transport.

All 56 targeted backend tests and 50 frontend tests passed, along with
lint, typing, API contract checks and the frontend production build.
An isolated downgrade refused to discard two frozen snapshots.


## Slice 14 · employee payslip publication

The actor who approved a locked run can publish its exact snapshot. The
publication receipt preserves the digest, actor and timestamp. An
identical retry returns the same receipt. Linked employees see only
their own published statement through My HR or the CLI. The detail uses
the frozen period dates and decrypts only the caller's line. Publication
does not execute payment, change role grants, or send notifications.

[Revision 024](../backend/alembic/versions/202605310024_hr_payslip_publication.py)
adds the receipt.
[Revision 025](../backend/alembic/versions/202605310025_index_hr_payroll_run_lines.py)
adds the lookup index. The populated upgrade preserved both existing
snapshots and both lines, with no payslips automatically published.

All 56 targeted backend tests and 50 frontend tests passed. Chrome
verified owner retrieval and CLI readback against a real published
fixture, plus denial for a second linked employee. The letter issue
and retrieval regression also passed in Chrome. A populated downgrade
rehearsal refused to remove the receipt or its lookup index.


## Slice 15 · protected Finance handoff export

A locked and approved run previews a currency total, payment rows, zero-net
line count, snapshot digest and CSV SHA-256. The approving actor registers
the exact preview. The protected download reproduces those bytes and
contains opaque line references, currency and positive net amounts.
The payroll snapshot exposes the corresponding employee IDs only to
authorized payroll readers. The CLI verifies the digest before creating
a private file and refuses to overwrite it.

[Revision 026](../backend/alembic/versions/202605310026_hr_payroll_exports.py)
adds an export receipt. The isolated upgrade preserved two payroll snapshots
and one payslip publication and created no export automatically.

All 75 targeted backend tests and 50 frontend tests passed. The API
checks verified accounting totals, zero-net exclusion, repeatable bytes,
access denial and receipt tampering. CLI tests verified digest checking,
mode 0600, and refusal to overwrite an existing file. An isolated
downgrade refused to delete the registered receipt. The frontend build
and backend lint, typing and API contract checks passed.


## Slice 16 · external settlement reconciliation

The protected API and CLI acknowledge external paid, failed and reversed
events using an exact registered CSV digest, payment reference, event UUID
and unique opaque evidence reference. Appended records preserve the approved
payroll and export. A paid event cannot exceed the outstanding balance and a
reversal cannot exceed the remaining amount on its original payment. The
summary reports current outstanding amounts, including after a reversal.
Raw evidence and event amounts are encrypted and excluded from audit values.

[Revision 027](../backend/alembic/versions/202605310027_hr_payroll_settlements.py)
preserved the existing export and payslip publication on a populated
disposable database and created no settlement events automatically.

All 76 targeted backend tests and 50 frontend tests passed. PostgreSQL
verification covered failed attempts, exact replay, conflicting replay,
duplicate evidence, competing completion, partial payment, reversal,
authorization and unchanged export bytes. Mocked CLI transport tests
verified private file mode, stale balance and evidence plan detection,
and metadata-only confirmation. A disposable downgrade preserved all
five recorded events. The frontend build, lint, typing and OpenAPI
contract checks passed.


## Slice 17 · offboarding inventory custody

[Revision 028](../backend/alembic/versions/202605310028_hr_offboarding_custody.py)
adds stock return, flag, waiver and clearance receipts. The inventory owner
writes the receipts with existing inventory authority. HR reads the case history
and closure checks the latest inventory-owner sign-off under the case lock.
Exact replay is actor-bound, each posted movement can appear only once,
and recording evidence leaves stock balances unchanged. A linked account still
requires the separate director deactivation. Open cases with legacy free-text
clearance require inventory sign-off. Closed cases remain historical.

A populated disposable upgrade preserved one existing case, its five clearance
steps and five settlement receipts. It created zero custody receipts.
The downgrade guard preserved all three custody receipts on a disposable
database after verification.

All 77 targeted backend tests and 50 frontend unit tests passed. The
PostgreSQL-backed API regression exercised actual stock returns, rejected a
cross-case link, verified exact and conflicting replays, and checked the unchanged
stock balance. It also verified HR and director permission boundaries, legacy
clearance, flagged custody and terminal closure. The mocked CLI scenario
verified preview without writes, stale plan rejection and exact receipt
readback. Chrome exercised viewing the pending case, receiving an inventory
owner's sign-off, refreshing the HR workspace, closing the case, and confirming
closure after reloading. Build, lint, typing and generated contract checks
passed. IT equipment custody, separation settlement, rehire and production
activation remain open.


## Slice 18 · independently reviewed rehire

[Revision 029](../backend/alembic/versions/202605310029_hr_employment_periods.py)
stores a closed period at separation and an open period on rehire. The workflow
reuses the reviewed employment-change API and binds the proposal to the latest
completed eligible separation and the employee revision. A different HR Manager
must approve it. Due application preserves the employee code, retains the
prior dates, and creates fresh onboarding. If a legacy separated employee has
no prior period record, retain the previously recorded start or leave it unknown.
Any overlap with the verified prior last day is rejected.

The separation, request and employment history remain intact. The rehire
updates current workforce assignments for the new onboarding and leaves
portal users and project memberships untouched. An older reactivation request
cannot reopen access after rehire, and fresh account reactivation still requires
director fulfillment. Payroll cannot source a compensation term from an earlier
period for a rehired employee. An approval or date rule for carrying over prior
leave, benefits or outstanding obligations remains a business decision.

The disposable revision 028 → 029 upgrade preserved 60 employment history
records, one completed offboarding case and three custody records. It created
zero employment periods. On a separate database the downgrade guard preserved
all six recorded employment periods. Tests covered competing apply requests,
revision conflicts, exact replay, activation gating, the probation checklist
and date guard, stale and newly approved reactivation, and selection of a new
payroll term. All 77 targeted backend tests and 50 frontend unit tests passed.
Chrome covered rehire proposal, independent approval, apply, reload and real API
readback through garrisonctl. The existing probation extension and confirmation
Chrome scenario also passed. Production rollout and business verification
remain open.


## Slice 19 · IT equipment handover

[Revision 030](../backend/alembic/versions/202605310030_hr_it_custody.py)
adds a custody area and device references.
[Revision 031](../backend/alembic/versions/202605310031_validate_hr_it_custody.py)
validates the area-specific constraint. The populated revision 029 rehearsal
preserved three store custody receipts and two employment periods. It created
zero IT receipts. A downgrade on the disposable verification database stopped
and preserved all eight IT receipts.

A director can record outstanding or returned devices and resolve each open
exception separately. The portal normalizes device references so differences in
letter case cannot create a second open device. Final sign-off requires zero
outstanding devices and confirmed deactivation for any linked account.
Final HR closure rechecks both requirements. Generic clearance updates can no
longer replace an IT or inventory attestation. Evidence history is visible to HR
in the portal and through the CLI. Closed legacy cases keep their records.
No IT receipts are fabricated for them. The portal records the director's
attestation of physical custody and external credential handling.

The first disposable fresh-upgrade attempt exposed a wrong constraint name
and a retry issue in the unpublished payroll-index revision 025. The corrected
chain upgraded a fresh database and a populated revision 029 snapshot. It also
recovered the original database whose correct index was committed at revision
024. A separate disposable test kept revision 024 and preserved a conflicting
index definition. The populated snapshot without IT receipts successfully
downgraded and re-upgraded while retaining all three store records.

All 78 targeted backend tests and 50 frontend unit tests passed. Chrome
verified a director flagging a device, clearing it with a return, signing off
and HR viewing the evidence before closure. The scenario also verified the
existing rehire path after closure. CLI preview, stale-plan rejection and
readback passed for store and IT custody. Production activation and business
acceptance remain open.


## Slice 20 · separation settlement review

[Revision 032](../backend/alembic/versions/202605310032_hr_separation_settlements.py)
adds retained separation settlement outcomes and their reviews. A director with
Finance access can record external evidence against an open case. A separate
director reviews the exact proposal. The database enforces one open proposal
and a distinct reviewer. A newer outcome clears prior Finance approval and
requires review. A pending, rejected or outstanding outcome blocks HR closure.
The approved settled or nothing-due outcome is tied to the Finance clearance
actor and timestamp. Exact retries preserve the receipt and cannot restore a
superseded clearance. Monetary calculations and execution stay in the Finance
system, and audit events record outcome and ID without the evidence references.

The revision 031 test copy retained one offboarding case, eleven custody receipts
and two employment periods on upgrade. The migration created zero settlement
receipts and preserved closed cases. The downgrade guard retained all six
receipts on a separate disposable database.

All 79 targeted backend tests and 50 frontend unit tests passed. The
PostgreSQL-backed scenario exercised competing proposals, stale and exact
replay, forbidden self-review, rejected and outstanding results, reopening
Finance clearance, a fresh review, offboarding closure and prior rehire
behavior. Chrome exercised the director and independent reviewer panels,
the HR read-only view and completion after review. CLI preview, conflict and
receipt readback used synthetic HTTP responses. Production activation and
business acceptance remain open.


## Slice 21 · verified training and employee visibility

[Revision 033](../backend/alembic/versions/202605310033_hr_training_completions.py)
adds one completion receipt per enrollment. Verification requires the
employee's current approved ordinary training certificate version and valid
completion and issue dates. The receipt retains its version, certificate
record and verifier. Exact replay returns the original completion and a
conflicting replay fails. A renewal uses a new enrollment and independently
approved evidence. Credential reporting counts the modeled certificate once
when its underlying document is also retained.

The existing training grant is now assigned to HR Manager. Linked employees
can see their own course status, verification and certificate expiry in My HR.
Employee readback excludes administrative scores, evidence references and
other employees' records. Prior legacy completion rows remain historical.

The revision 032 test copy preserved 49 employees, one legacy certificate
and five separation settlement receipts. The upgrade created zero completion
receipts. The rollback guard preserved both verified receipts on a separate
disposable database. All 80 targeted backend tests and 50 frontend unit tests
passed. Chrome covered course creation, enrollment, certificate upload,
verification, reload, CLI readback and employee visibility. A separate HR
session approved the certificate through the API. Role/site-specific training
rules, performance reviews and production evidence remain open.


## Slice 22 · mandatory training by position and site

[Revision 034](../backend/alembic/versions/202605310034_hr_training_requirements.py)
adds explicit course requirements by HR position, primary project site, or
both. A combined rule requires both assignments. Overlapping rules render one
requirement per course. Existing verified evidence determines whether the
requirement is met, enrolled, expired or required. Deactivating a rule preserves
enrollment and receipt history. Portal permissions, membership and the legacy
course flag have independent meanings.

All 80 targeted backend tests and 50 frontend tests passed. The API scenario
verified combined-scope mismatch, overlapping rules, concurrent duplicate
requests, expiry, renewal and safe rule deactivation/reactivation. Chrome
verified HR configuring a position rule and the linked employee seeing their
own expired requirement. The revision 033 copy retained one course, two
enrollments and two verified receipts on upgrade. The downgrade guard
retained all three configured rules on the disposable verification database.


## Slice 23 · participant-scoped performance review

[Revision 035](../backend/alembic/versions/202605310035_hr_performance_events.py)
adds retained participant decisions. Review setup resolves goals by cycle code
and locks them when HR opens the draft. Access follows the linked employee,
their explicitly authorized current direct manager, and HR Manager authority.
The manager’s written assessment stays private from the employee until HR
calibration. Once the employee acknowledges the final narrative, HR can append
corrections while the prior assessment and decision events are preserved.

All 81 targeted backend tests and 50 frontend tests passed. The API scenario
covered denied unrelated access, revoked reviewer access, stale actions and
duplicate acknowledgment, progress notes, publication and append-only
correction. Chrome covered HR setup, both acknowledgments, the assessment
handoff, calibration and correction. The upgrade from revision 034 retained
51 employees, three training rules and two training receipts and created zero
review events. The downgrade guard retained all eight events in the
disposable verification database.


## Slice 24 · performance ratings and reviewer handoff

[Revision 036](../backend/alembic/versions/202605310036_hr_performance_scale_handoff.py)
adds optional cycle-specific rating labels and retains both reviewer identities
on each handoff. Narrative-only cycles retain their prior behavior. Rated
cycles validate employee, manager and HR choices against the configured scale.
The final rating comes from HR calibration. The code introduces no default
labels or weighting formula.

Before calibration, HR can hand off to an explicitly authorized current manager.
The former manager loses participant access when their assignment changes.
The replacement acknowledges goals before submitting a new assessment. The
employee’s submission stays in the review and the superseded assessment
stays in HR history. A published or closed review retains its assignment.

All 82 targeted backend tests and 50 frontend tests passed. The API covered
rating validation, authorization and publication after handoff. Chrome exercised
cycle setup, rated assessments, the HR handoff, replacement acknowledgment,
calibration and the employee’s final acknowledgment. The populated migration
retained one narrative cycle, one review and eight events. A downgrade attempt
preserved four rating events and one handoff on a disposable database.

## Slice 25 · workforce roster allocations

[Revision 037](../backend/alembic/versions/202605310037_hr_roster_allocations.py)
adds the roster ledger. HR can schedule a whole published workday or shift
against a project and cancel it with a retained reason. UTC interval checks
detect overnight overlaps under the same employee lock used for shift
assignment. Exact create and cancellation replays preserve one audit event
per action. Project membership, attendance, stock, and payroll keep their
existing writers.

The targeted backend suite passed 83 tests and the frontend suite passed 50.
The Chrome workflow allocated a published workday, rejected a duplicate,
cancelled with a reason, and retrieved the cancellation after reload.
PostgreSQL tests exercised concurrent requests, cross-date overlaps, configured
daily hours, permission denials, and isolation from access, attendance, and
stock. The upgrade from revision 036 retained 56 employees, two review cycles,
and 19 performance events. A downgrade attempt on the test database preserved
its two roster records, including one cancellation. Production activation and
HR business verification remain open.

## Slice 26 · payroll time input handoff

The prepare-only API and `garrisonctl hr payroll time-inputs` preview a named
payroll period and explicit employee roster. A ready preview can be downloaded
by digest. The extract uses locked timesheets as the single source of counted
hours, checks approved overtime against each sheet, and flags outstanding
attendance and corrections, missing attendance schedule links, overlapping
sheets and out-of-period sheets. HR must decide pending overtime before
locking a timesheet. The CSV carries time quantities and opaque source
references. It leaves wage calculation and resulting payouts in the existing
separate workflows.

The PostgreSQL/API test exercised the pending-overtime lock, independent
approval, one-row reconciliation, permission denial, and stale-download
rejection after inconsistent legacy inputs. The CLI contract test verified
the downloaded bytes, file permissions, digest failure and refusal to
overwrite. Chrome exercised employee submission, manager recommendation, HR
approval and the lock error while overtime remained pending. All 85 targeted
backend and 50 frontend tests passed, along with lint, types, the frontend build
and regenerated contracts. This slice requires no new database migration.
Production payroll authorization, approved rate examples and live
reconciliation remain open.

## Slice 27 · reviewed profile name corrections and revision checks

Current employees' first, last, and full names now use the existing
effective-dated employment change workflow. The proposal retains the exact
name fields and reason. A different HR Manager approves the proposal before
it can be applied. Applying a due proposal keeps one history entry with the
previous and corrected names. The API rejects stale proposals and direct name
changes to current employees. Pre-activation editing continues through the
directory.

The employee's current revision also governs private-vault and My HR updates.
Both writers serialize on the employee row, so concurrent first writes to an
empty vault produce one save and one conflict. Unexpected fields are rejected,
sensitive responses use `Cache-Control: no-store`, and audit events retain
field names and the revision without contact or identity values. These write
requests now require `expected_revision`. Older clients must refresh before
editing after rollout.

All 86 targeted backend tests and 50 frontend tests passed with lint, types,
API contract checks and the production build. PostgreSQL tests verified
conflicting writes, role denials, stale proposal handling and one retained
history entry. The issued-letter regression confirmed that a later name
correction preserves an already issued letter and prevents issuing a stale
draft. Chrome verified reviewed employment changes, name correction, stale
contact and private-vault edits, and successful saves after reloading. This
slice requires no new database migration. Production verification remains
open.

## Slice 28 · application withdrawal and retention decision

A withdrawal records the reviewed application stage, reason, and one of two
retention dispositions. HR can retain under a referenced policy until a
recorded review date, or mark the application for policy review when those
values are pending. The date is for review. The workflow retains candidate
records, CVs, and other applications under their existing authorization.
It cancels scheduled interviews and withdraws open offers for the affected
application. Acceptance and withdrawal serialize on the application row.
Historical offers and completed interviews remain available.

The UI and CLI use the protected recruitment API. The CLI binds apply to
the preview, reads back the recorded decision and omits the private reason
from its output. An identical API retry preserves the recorded decision and
emits no duplicate audit event.

All 88 targeted backend and 50 frontend tests passed with lint, typing,
API contract checks and the frontend build. Chrome verified retention form
validation, withdrawal, interview cancellation, persistence after reload,
and the existing offer reissue and conversion workflow. PostgreSQL tests
covered competing acceptance and withdrawal, a separate application for
the same candidate, and authorized and unauthorized CV retrieval.
[Revision 038](../backend/alembic/versions/202605310038_hr_application_withdrawal.py)
upgraded a populated revision 037 test database while retaining four
applications, five candidates and five offers. A downgrade attempt preserved
two recorded withdrawals. Business retention policy and production
verification remain open.

## Slice 29 · independently reviewed candidate rejection correspondence

HR prepares candidate rejection templates with only candidate name and
position title as record-derived placeholders. A rejected application can
have one pending or approved draft. The retained subject and body are
encrypted and tied to the reviewed digest. A second HR Manager can approve
that text or reject it with an encrypted reason. Approval fails if the
rendered source changed. Approved text is available for manual handoff.
The workflow records no delivery and sends no messages.

Application rejection now closes scheduled interviews and outstanding
offers under the same application lock as the withdrawal workflow. A
previously accepted offer requires separate resolution. Employee letters
and candidate correspondence keep separate template choices and records.

All 89 targeted backend and 50 frontend tests passed with lint, typing,
API contract checks, and the frontend build. Chrome exercised template
creation, internal application rejection, draft review by a second HR
Manager, and approved text after reload. The withdrawal regression also
passed. PostgreSQL tests verified encrypted text and review reasons,
recruitment authorization, changed-source and digest conflicts, and
idempotent approval. [Revision 039](../backend/alembic/versions/202605310039_hr_candidate_correspondence.py)
retained seven applications, two withdrawal decisions, two letter
templates and two issued employee letters in a populated upgrade.
The downgrade guard preserved one approved and one rejected candidate
draft. Business wording and production verification remain open.

## Slice 30 · manual shortlist and application stage history

Recruitment now records an explicit shortlist between screening and
interview. The interview API checks eligibility under the application row
lock. Existing applications in interview or evaluation retain their stage.
Evaluation still requires a completed interview. Search and stage filters
page through applications by candidate name or code. The activity view
reads stage, actor and time from the audit trail. The CLI offers a
checksum-bound shortlist command and stage history readback.

All 91 targeted backend and 50 frontend tests passed with lint, types,
API contract checks and the frontend build. PostgreSQL tests covered
unauthorized access, early interview rejection, concurrent shortlist
requests, literal search and stable pagination. Chrome exercised candidate
search, manual shortlisting, stage history and interview scheduling through
withdrawal. Offer reissue/conversion and reviewed correspondence passed
in the same run. [Revision 040](../backend/alembic/versions/202605310040_index_hr_application_activity.py)
preserved the populated application stages and audit data. Rehearsing a
retry after index creation reused the same valid index. PostgreSQL
confirmed the history lookup can use it. Production activation and
remaining business verification remain open.

## Slice 31 · policy editions and exact acknowledgement

The publication stores the exact approved version of a company policy file
and can name the preceding edition. A scheduled replacement takes effect on
its effective date. Prior recipients can reopen editions they acknowledged.
Each required edition has a separate receipt and repeated submissions return
the same receipt. Text-only policies use the same edition check. Old file
links without a verified version remain visible for HR reconciliation and
cannot collect new acknowledgements until reviewed and republished.

All 92 targeted backend and 50 frontend tests passed with lint, types,
API contract checks and the frontend build. The API tests covered future
effective dates, wrong-version attempts, repeat submissions and access by
linked and unlinked users. Chrome published two editions, downloaded both
PDFs from the vault and compared their bytes with the original uploads.
Both acknowledgements persisted after reload. The candidate correspondence
regression also passed.

[Revisions 041](../backend/alembic/versions/202605310041_hr_policy_edition_binding.py)
and [042](../backend/alembic/versions/202605310042_validate_hr_policy_edition.py)
preserved the existing policy and receipt on a populated upgrade. The
downgrade guard preserved two pinned documents and one replacement link.
Acknowledgement API clients now send the displayed policy edition and the
pinned document version when present. Production verification remains open.

## Slice 32 · isolated HR recovery readback

The authenticated format 2 rehearsal restored a populated synthetic database
at Alembic head `202605310042`. The source object service was stopped and the
source database closed to new connections before the backup was fetched from
a separate loopback object service. PostgreSQL and the recovered object store
were isolated on the same machine.

The running restored API verified three distinct accounts, the decrypted
synthetic identifier, both versions of a confidential personnel file, both
policy receipts and their exact PDF bytes, and the digest of decrypted approved
candidate correspondence. The outsider was denied access to the confidential
records and the superseded policy edition. A wrong HR key returned HTTP 503
for the identity readback, and a tampered encrypted artifact failed backup
verification. The restore receipt recorded four restored objects and
approximately 0.41 seconds from restore start to object verification for the
synthetic dataset. Production key custody, off-host recovery and production
recovery targets remain unverified.

All 49 focused recovery and backup tests passed against disposable PostgreSQL,
including seven cases for the readback checker. Ruff and mypy passed on the
checker and its tests.

## Slice 33 · candidate correspondence CLI

`garrisonctl hr correspondence` lists templates and draft status, prepares a
draft under a stable UUID and reads the exact content into a new private file.
Independent decisions require the opened content's digest and a plan bound to
the current actor and target. The CLI checks the persisted final status and
keeps correspondence content and review reasons out of console output.

The focused run passed seven tests, including the existing PostgreSQL API
regression and the CLI approval and rejection cases. The CLI regressions also
verified that template content stays out of listings, preview cannot be applied
by another actor, private output cannot be overwritten, and stale digests and
changed review reasons prevent a write. Ruff and mypy passed for the CLI changes.

## Slice 34 · interview scheduling and outcomes in the CLI

Recruitment staff can list an application's interviews, schedule a round and
record the outcome using a private JSON file and an actor-bound preview. A
client-generated interview UUID makes identical scheduling retries safe.
Interview updates check the revision timestamp after locking the application
and interview. The API fields are additive for existing portal clients.

Eleven focused recruitment and CLI tests passed against disposable PostgreSQL.
The API regression verified that concurrent retries persist one interview,
changed details cannot reuse its UUID, a stale application cannot schedule a
round, unauthorized staff cannot schedule, and competing updates from the
same snapshot yield one saved outcome. The CLI regression verified stale
plans, persistence readback and omission of private feedback and names.

## Slice 35 · versioned offers in the CLI

The terminal lists and filters offers, drafts and reissues terms, records
decisions and inspects terms in a new owner-only file. Mutation previews bind
the actor, offer or application state and private input checksum. Under the
existing database locks the API checks the expected timestamp. Reissue verifies
the old and new version links. The existing approval permission checks still
apply.

Thirteen focused PostgreSQL-backed recruitment and CLI tests passed. The API
regression verified stale decisions and reissue, acceptance versus expiry,
unchanged historical terms and pagination across versions. The CLI regression
verified private output, permission checks, changed inputs and readback of
both version links. OpenAPI, generated types, frontend build, Ruff and mypy
passed.

## Slice 36 · internal interview invitations

Recruitment staff can search active portal accounts by name when scheduling
an interview. Only the assigned account receives a generic in-app invitation
or cancellation. Notices contain no candidate details, appointment date,
feedback or record links. Scheduling retries reuse the interview UUID, and
the notification commits with the interview.

Six focused tests passed against disposable services. The API regression
verified recipient lookup permissions, invalid recipient rejection and one
notice after concurrent scheduling retries. Chrome selected an interviewer,
scheduled the interview, withdrew the application, then verified both
notifications and the absence of the candidate name in the notification feed.

## Slice 37 · exact confidential offer PDFs

Offer drafts can reference an approved confidential PDF for the same candidate.
A different HR Manager reviews the PDF in the vault before it becomes
selectable. Reissue requires a different approved PDF when the original
offer had a file. Download uses the pinned version for that offer, including
after replacement, and requires recruitment and confidential-document access.

Six targeted PostgreSQL-backed tests, one CLI regression and three Chrome
scenarios passed. Chrome uploaded an offer PDF, selected the reviewed version,
reissued with a second PDF and checked the exact downloaded bytes for both
offers. A populated upgrade from 042 through 044 preserved six existing
offers and validated the foreign key. A downgrade with two pinned references
was rejected and left them intact.

## Slice 38 · requisition lifecycle in the CLI

Recruitment staff can retrieve a requisition by ID, filter and page the
register, create a requisition from a private file, and apply a reviewed
workflow decision. The API compares the decision's expected timestamp under
the requisition lock. The terminal verifies the persisted headcount and the
decision without printing private justification, budget notes or rejection
reasons. An exact code lookup supports lost-response recovery.

The focused PostgreSQL-backed run passed six tests. It covered denied reads,
stale decisions, exact code and status filters, preserved rejection reasons
and the CLI's private preview, apply and readback. OpenAPI, generated types,
Ruff, mypy and the frontend build passed.

## Slice 39 · candidates and applications in the CLI

Recruitment staff can register and find candidates, create an application for
an open requisition and record screening, interview, evaluation, offer and
rejection decisions. The CLI supports recovery lookups by exact candidate
code or candidate and requisition IDs. Candidate contact information, scores
and private screening notes stay out of previews and receipts. Authorized
operators can inspect them in a new owner-only file.

The API checks the requisition snapshot on application creation and the
application snapshot on stage decisions, including CLI shortlist and
withdrawal. The focused run passed ten tests, including stale updates,
duplicate application prevention in the CLI, denied candidate reads and
literal filtering. OpenAPI, generated types, Ruff, mypy and the frontend
build passed.

## Slice 40 · candidate vault files in the CLI

The CLI lists candidate documents, uploads initial and replacement versions,
and supports independent approval or rejection of an exact checksum. The API
checks the expected latest version under the vault document lock. Downloads
verify the signed storage origin, exact file size and SHA-256 before writing
a new owner-only file. Requests to storage carry no portal credentials.

Six focused tests and three Chrome recruitment regressions passed. The real
API verified denied access to confidential metadata and a single replacement
after two concurrent requests. The CLI exercised a loopback object server and
rejected redirects, a different origin and changed bytes. The OpenAPI contract,
generated types, frontend build, Ruff and mypy passed.

## Slice 41 · onboarding and probation in the CLI

The terminal can list cases, start direct-hire onboarding, record checklist
evidence and extend or confirm probation. The API protects checklist updates
with the current task timestamp. Probation decisions use the employee's
existing revision check. Terminal receipts omit evidence notes and probation
reasons. Authorized operators can save case details to a new owner-only file.

Three focused tests passed. The PostgreSQL checks covered denied case access,
concurrent checklist updates and competing probation decisions. A Chrome
scenario completed the first task through the actual CLI against the local
API, then extended and confirmed probation in the portal. OpenAPI, generated
types, frontend build, Ruff and mypy passed.

## Slice 42 · opt-in scheduled leave accrual

Celery can post the latest closed month and previous calendar year's
accruals for explicitly selected policy UUIDs. The job checks policy review,
type, period coverage and employment history using the same transaction
as manual posting. Scheduled credits use the existing accrual audit event
with a scheduled source, and the worker skips periods with an existing receipt. No policy
is selected by the default configuration.

Three PostgreSQL tests passed, covering monthly and annual credits,
unapproved policies, an unselected category-specific override, a partial
period, preservation of a manual receipt and concurrent scheduled runs.
Separate Celery initialization checks verified schedule registration with a
configured policy list and omission with an empty list. Ruff and mypy passed.

## Slice 43 · reviewed partial-period accrual

Monthly and annual policies can opt into calendar-day proration through the
existing independent approval workflow. The credit uses the eligible share
of the period, with the credited date range retained in the receipt and audit
event. The default requires the full period. Scheduled runs use the same
calculation as manual and catch-up posting.

Three focused tests passed, including rounding for leap-year periods,
a scheduled partial credit, and receipt readback. Chrome independently
approved a prorating policy and posted 0.50 days for a mid-month hire while
retaining the full-year credits for the original employee. An isolated
upgrade from revision 044 preserved 14 historic receipts and five policies.
The downgrade rehearsal refused to remove a retained prorated receipt.

## Slice 44 · reconciled leave inputs for payroll

The payroll preparer can preview approved leave for an explicit roster and
download the exact reviewed CSV through the API or `garrisonctl`. A leave
approval must reconcile to its ledger debit. A cancellation after approval
must reconcile to its reversal. The CSV records paid and unpaid quantities
without names, reasons, attachments or rates. It covers roster employees with
no approved leave and blocks an export when inputs are pending or inconsistent.
Requests spanning two periods require approved daily allocations before they
can be exported. Quantities are input evidence for payroll.

Four focused tests passed against disposable services, including stale download
after cancellation, a mismatched debit, cross-period requests, digest stability
and private file handling. Ruff, mypy, the OpenAPI contract, generated types
and the frontend build passed locally. The API and terminal change has no
schema migration on its own. Production verification and policy-backed
deductions remain open.

## Slice 45 · approved leave across payroll periods

Revision `202605310047` retains scheduled work dates on leave submissions.
Approval rejects a changed schedule, including a change that preserves the
total number of days. Once approved, later calendar edits cannot change the
payroll split. Payroll verifies the full approval against the ledger, then
exports only the approved dates and units in its period. Legacy approvals
retain their original totals. A legacy approval crossing a payroll boundary
requires verified date evidence before export.

All 46 tests in the HR API and CLI suite passed with disposable PostgreSQL and
Redis at revision `202605310047`. The regression verified exact allocations
across two periods, half-day handling, moved holidays before and after
approval, and rejection of invalid or absent date evidence. Ruff, mypy,
generated TypeScript checks and the frontend build passed. The migration
and app changes remain local.

## Slice 46 · reimbursement evidence and independent decisions

The API restricts claims to the existing payroll permissions. New claims
keep their submitter and approved receipt version. Per-employee locking and
idempotency prevent duplicate submissions, including copies of the same
receipt for an open, approved or paid claim. Changed details under an
existing key return a conflict. Only independent actors can review and
record external settlement. Recording settlement preserves the approval
and appends an audit event. No live permission grant or Finance mutation
was introduced.

All 47 HR API and CLI tests passed against disposable PostgreSQL and Redis at
revision `202605310049`. The new regression covered wrong-employee and
unapproved receipts, nonprivate files, exact decimal amounts, concurrent
submissions and decisions, replay conflicts and immutable approval.
Ruff, mypy, OpenAPI, generated TypeScript and the frontend build passed.
Production rollout, policy configuration and the Finance handoff remain open.

## Slice 47 · independent compensation approval

Authorized actors can propose encrypted terms and independently approve or
reject each proposal. Payroll reads only approved terms and keeps its
calculated snapshot unchanged. HR history marks the approved term effective
on the business date. Backdated terms that would affect locked payroll are
refused. Masked history is the default, and explicit access to private terms
and review reasons is audited.

All 47 HR API and CLI tests passed against disposable PostgreSQL and Redis.
The payroll regression exercised draft exclusion, self-approval denial,
future and duplicate dates, private rejection reasons, and locked payroll.
The upgrade from revision 049 to 051 preserved a legacy term's ciphertext
and history. A downgrade rehearsal refused to discard reviewed evidence.
Ruff, mypy, OpenAPI, generated TypeScript and the frontend build passed.
Production rollout remained open.

## Slice 48 · compensation proposals and review in the portal

The employee directory shows compensation history to actors with restricted
payroll access. Salary, allowances and rejection reasons are loaded only
after revealing a specific term. The panel clears the private view when
closed or when changing employees. A second operator can approve or reject
the revealed proposal through the same API, and reviewed terms persist
through reload. The browser fixture grants the two existing permissions only
inside the disposable test server.

The PostgreSQL regression checked a scoped reveal and rejected a term
belonging to a different employee. The Chrome scenario exercised input
validation, preserved the amount after a rejected submission, blocked the
maker's review controls, and confirmed independent approval and masked
history after reload. All 47 HR API and CLI tests passed. Three Chrome
scenarios passed, including employee profile editing and HR access
revocation. Ruff, mypy, OpenAPI, API types and the frontend build passed.
No migration was needed for this portal change.

## Slice 49 · reimbursement payable and Finance reconciliation

Approved claims produce a deterministic private payable reference with an
opaque employee ID and the exact amount, currency and approval timestamp.
Settlement confirms the external reference, reviewed payable digest and
exact full amount and currency. The original approval stays intact. The
terminal verifies the digest, saves an owner-only copy for unpaid claims,
and supports a private preview, apply and readback for settlement. No
invoice, payment or bank transfer is created. An outcome short of full
settlement leaves the claim approved and outstanding.

All 48 HR API and CLI tests passed on disposable services. The tests covered
denied or premature handoff, stable reference after settlement, stale or
changed confirmation, amount and currency mismatches, restricted terminal
output, and unchanged Finance invoice and payment counts. Ruff, mypy,
OpenAPI, generated TypeScript and the frontend build passed. No schema
migration was needed. External execution mapping and live activation remain
open.

## Slice 50 · approved reimbursement ceilings

Restricted operators can propose a ceiling and currency on a benefit type.
A separate actor approves the policy before an employee can receive capped,
dated coverage. New claims bind to that assignment. Pending approvals
reserve the limit. Paid claims continue to count. Rejection and cancellation
free the reserved amount. Coverage dates are inclusive and overlapping
assignments for one employee and benefit type are refused.

All 48 HR API and CLI tests passed. The PostgreSQL regression exercised
exact boundary acceptance, concurrent claims competing for the remaining
limit, rejection releasing the reservation, and denied assignment or claim
against unapproved, out-of-window or other-employee coverage. The isolated
051 to 053 upgrade preserved legacy claims and benefit types. Downgrade
refused to discard new coverage evidence. Ruff, mypy, OpenAPI, generated
types and the frontend build passed. Policy values and production activation
remain open.

## Slice 51 · advances and external repayment evidence

The restricted API supports advance submission, independent approval,
digest-bound external disbursement, recorded repayments and protected
readback. Approved policies must explicitly allow advances. An open
advance reserves its full principal against the same dated ceiling as
reimbursements until fully repaid. Duplicate repayment evidence is safe to
retry. A repayment above the outstanding balance is refused.

The full HR suite passed all 48 tests. The final focused run covered
independent approval and disbursement, same-key replay, recovery races,
overpayment, closed balances and the resulting reimbursement capacity.
Invoice and payment counts stayed unchanged. The isolated upgrade to 054
preserved the previous policy values with advances disabled. The downgrade
refused to discard advance evidence. Ruff, mypy, OpenAPI, generated
TypeScript and the frontend build passed. Production activation and
deduction policies remain open.

## Slice 52 · advance operations in the CLI

`garrisonctl hr advance` supports discovery, private record export,
submission, decision, disbursement and repayment. Write previews bind the
actor, environment, private input and reviewed state. The terminal prints
record identifiers and status. It writes amounts and external evidence only
to an explicitly requested owner-only file. Each mutation checks API
readback for the expected state or evidence.

All 49 HR API and CLI tests passed. The CLI focused test covered private
input permissions, missing approval permission, changed state or
confirmation fields, replay-safe submission, owner-only output and
ambiguous readback after a write. The command help, Ruff and mypy passed.
The CLI requires no new database revision. Production activation remains
open.

## Slice 53 · employee advances in the portal

Permitted directory users can open an employee's advance records, select
approved benefit coverage, submit and independently review a request.
The panel can export the approved payable and lets a separate operator
record external disbursement and repayments.

All 49 HR API and CLI tests passed. Two Chrome workflows passed with the
isolated API and database. The advance scenario verified that validation
preserves the amount, the submitter cannot approve, the approver cannot
confirm disbursement, the payable download matches the approved record,
and the paid balance and repayment reference persist after reload.
The compensation review scenario passed in the same Chrome run.
Ruff, mypy, OpenAPI, TypeScript and the frontend build also passed.
No schema migration was needed for this panel.

## Slice 54 · capped benefit policy administration in the portal

Authorized directory users can propose a capped benefit policy, specify its
currency and opt in to advances. An independent reviewer can inspect and
approve the proposal. The employee's coverage form lists approved policies
and records dated assignments. The advance picker uses the same approved
policy and coverage records.

All 49 HR API and CLI tests passed. In Chrome, the maker proposed a policy,
the checker approved it, and the maker assigned coverage through the portal.
An overlapping assignment was refused and the entered dates survived.
The scenario used that coverage for an advance, verified its ceiling, and
read back full repayment after reload. The compensation workflow passed
in the same run. Ruff, mypy, OpenAPI, TypeScript and the frontend build
passed. No schema migration was needed for the panel.

## Slice 55 · reimbursement operations in the portal

The directory supports private receipt upload, independent receipt review,
claim submission under approved coverage, exact pinned evidence retrieval,
independent claim decisions, payable export and external settlement.
The uploader cannot download the pending receipt through the new review
path. A separate reviewer with both the document and payroll permissions
can access that exact pending version.

All 49 HR API and CLI tests and two Chrome workflows passed. The new
scenario checked the pending and pinned receipt bytes, the maker/checker
controls, the payable digest, the rejected wrong-amount settlement and
the persisted external reference after reload. The advance workflow passed
in the same Chrome run. OpenAPI, generated types and the frontend build
passed. No new schema migration was needed for the panel.

## Slice 56 · payroll review and payslip publication in the portal

Authorized operators can open a period, create a run under an approved
base-salary policy and calculate it using an explicit roster. A separate
reviewer opens the private snapshot by run ID, confirms its digest to lock
the period, and publishes employee-scoped payslips. Production permissions
remain role gated.

All 49 HR API and CLI tests passed, and the targeted PostgreSQL payroll
regression passed on rerun. Two Chrome workflows passed. The new scenario
checked duplicate roster entry rejection, masked totals before explicit
review, maker/checker separation, digest-bound approval and the employee's
published net amount. The existing payslip and access-boundary scenario
passed after updating its fixture to independently approve compensation.
Ruff, mypy, OpenAPI, TypeScript and the frontend build passed. The portal
change required no migration.

## Slice 57 · payroll Finance handoff and reconciliation in the portal

An authorized payroll reviewer can open the Finance handoff from a reviewed
approved snapshot. The original approver registers the snapshot and CSV
digests. The browser hashes the downloaded bytes before saving the
registered CSV. Authorized reviewers can inspect exported payment balances
and paged event history, then record an external confirmation, failure or
reversal. Retrying the same form submission reuses its event ID while the
form is open. This uses the existing API and requires no schema migration
or new production permission grants.

The isolated HR suite passed 49 tests. Three targeted payroll tests passed
on rerun. Two Chrome scenarios passed on the final portal changes. The
payroll scenario verified the downloaded CSV schema, exact amount and
checksum, recorded a partial payment, rejected an overpayment without
clearing the form, reversed the original payment and read the reconciliation
back after reload. The employee payslip access scenario also passed.
Frontend lint, the generated API type check and the build passed. The
failure-outcome option uses the existing settlement contract and was not
exercised in Chrome.

## Slice 58 · payroll policy proposal and review in the portal

A payroll preparer proposes a monthly base-salary policy with an explicit
currency, rounding method and deduction fraction. A separate approver opens
the saved policy by ID, inspects its exact calculation rules and approves
it. The preparer can then select it for a payroll run. The policy-detail
route requires approval permission and returns `Cache-Control: no-store`.
This uses existing policy records and approval rules. No migration,
production permission grant or statutory rate is included.

All 49 isolated HR tests passed. The focused PostgreSQL rerun additionally
verified exact rule readback, no-store, forbidden access for a preparer
without approval permission, and not-found behavior. Two Chrome scenarios
passed. The payroll scenario proposed the policy, confirmed the proposer
could not approve via UI or direct API, independently approved as the
reviewer, reloaded and calculated from the approved policy. It also
exercised the previous payslip and Finance handoff. Ruff, targeted mypy,
OpenAPI, generated API types, frontend lint and build passed.

## Slice 59 · independently reviewed payroll earnings and deductions

Revision 055 creates an additive adjustment table for policies that
explicitly enable reviewed inputs. A preparer submits an earning or
deduction with an opaque evidence reference and an idempotent UUID.
A different authorized reviewer approves or rejects the exact entry.
The period and run locks serialize proposals and decisions with
calculation. Only approved entries go into the encrypted snapshot.
Pending entries and an omitted employee with an approved entry block
calculation. The policy rate applies to base salary. Approved fixed
earnings increase gross and approved fixed deductions increase total
deductions. There are no new statutory rates or automatic imports.

All 49 HR tests passed. The focused PostgreSQL regression also passed on
rerun and checked exact totals, request replay, changed payload and duplicate
evidence conflicts, unauthorized access, stale review, excluded rejected
inputs and frozen evidence. Two Chrome scenarios passed after disambiguating
the test selectors. Chrome exercised proposing and independently approving
an earning and a deduction, reviewing their frozen breakdown and publishing
the employee payslip. Ruff, targeted mypy, OpenAPI, TypeScript and the
frontend build passed. An isolated PostgreSQL database upgraded through
revision 055. Production migration and activation remain pending.

## Slice 60 · close reconciled payroll

The portal and CLI close an approved run after its exact payslips are
published and every positive payment is reconciled. Zero-net payroll
uses the deterministic checksum of its empty payment file and does not
need export registration. Under the existing run and period locks, the
closure binds the reviewed snapshot, CSV and immutable event set to one
receipt. An identical retry returns the receipt. Existing settlement,
export and payslip reads stay available. New settlement events against a
closed run are rejected until a correction workflow is available.

All 49 isolated HR tests passed, followed by the new targeted CLI test.
PostgreSQL coverage verified pending-balance refusal, independent authority,
a stale digest, concurrent close replay, zero-net closure, late reversal
refusal and continued file access. Chrome passed two scenarios including
final payment, closure, reload and employee payslip readback. The CLI test
confirmed stale-plan rejection and receipt readback without payroll line
details. Ruff, mypy, OpenAPI, generated types, frontend lint and build
passed. Revision 056 ran on the isolated database. Production remains
unverified for this slice.

## Slice 61 · review payroll time and leave inputs in the portal

The preparer can open the time and leave previews for the selected draft
run's period and exact roster. Pending or inconsistent records are shown
with their employee and source IDs. Clean sources show reconciled hours
or days and support an exact CSV download checked against the preview
digest. Changing roster membership discards the prior review. The UI uses
the existing source APIs and requires no migration. The preview does not
apply overtime or unpaid leave rates to wages.

Ten targeted payroll tests and two Chrome scenarios passed. Chrome
observed a missing locked timesheet, cleared the preview by editing the
roster, then refreshed against a locked timesheet with independently
approved overtime. Both source CSVs matched the displayed checksums and
omitted private notes. The same scenario continued through calculation,
payslip publication, settlement and closure. Frontend lint, generated type
check and build passed. HR is the confirmed business owner; its approved
policy reference remains unconfirmed. Production has not been changed.

## Slice 62 · freeze reviewed payroll source evidence

The preparer can include time and leave review in the calculation command
from the portal or CLI. Both inputs must reconcile against the reviewed
digests for the exact roster. Source reads use the existing locks without
committing; stale evidence rejects calculation before the snapshot is
saved. An identical retry reuses the snapshot and a changed source
selection conflicts. The existing encrypted snapshot stores the two
reviewed CSVs and summary totals. A sensitive payroll reviewer can
download the frozen bytes through an audited, no-store endpoint. This
requires no migration and does not introduce new wage formulas.

Ten targeted payroll tests and two Chrome workflows passed. Chrome
checked stale and changed calculation commands, exact retry, protected
source downloads, and byte-for-byte retention after a new live overtime
request. A focused CLI rerun checked both digests are sent together.
Ruff, mypy, OpenAPI, generated API types, frontend lint and build passed.

## Slice 63 · review corrections to closed payroll

Preparers can propose corrected gross and deduction amounts for a line
in a closed run. The encrypted proposal references the exact original
snapshot and the current approved correction when one exists. A separate
reviewer approves or rejects the exact proposal. Approved successors
preserve the prior approved correction as their baseline. The portal
shows both amounts and the net delta. The original payroll snapshot,
employee payslip, Finance CSV and settlement history remain intact.
Payment execution, overpayment recovery and corrected statement issuance
remain open. Slice 64 adds correction CLI operations.

Ten targeted payroll tests passed. The PostgreSQL run exercised revision
057, stale baseline and digest rejection, proposal and decision replay,
self-review denial, a second approved correction and unchanged historical
payslip, export and snapshot. Two Chrome workflows passed, including
proposal, separate approval, persistence after reload and original
employee payslip access. Ruff, mypy, OpenAPI, generated API types,
frontend lint and build passed. Production has not been changed.

## Slice 64 · payroll correction CLI and recovery rehearsal

The CLI lists, reads, proposes and decides closed payroll corrections.
Proposal amounts and the evidence reference are read from an owner-only
file. The write previews bind the actor, original snapshot, reviewed
baseline and proposal or decision digest. Write responses include a
verified receipt and omit the private amounts and evidence reference.
The new exact-record route enforces sensitive permission and confirms
the correction belongs to the requested closed run and line.

The 51-test HR suite passed, including CLI owner-only input, stale
baseline refusal, self-review refusal and receipt readback. The API test
verified authorized exact read, no-store, forbidden access and an unknown
correction. Two Chrome scenarios passed. Whole-backend Ruff and mypy,
OpenAPI, generated API types, frontend lint, 50 frontend tests and build
passed.

The populated synthetic PostgreSQL 18 database was dumped and restored
at revision 057 into a distinct disposable database after the source
stopped accepting connections. Application readback reproduced the
correction, closure, payslip publication, snapshot, frozen time/leave and
Finance CSV digests. The wrong HR key raised the expected 503
decryption error. This rehearsal verified database records and key
behavior on one machine. Off-host recovery, production key custody and
the release-candidate production restore remain open.

## Slice 65 · attendance, timesheet and overtime CLI

HR time administrators can list, read, create and decide attendance
entries, attendance corrections, timesheets and overtime requests from
the CLI. Create and review read an owner-only JSON file, bind previews to
the signed-in actor and request, and read back the saved status. Review
also binds the current record and sends its revision where supported by
the existing decision contract. New record-detail endpoints retain the
existing attendance read permission and return no-store responses.
Write receipts omit private notes. No migration was needed.

The 55-test HR suite passed. PostgreSQL covered exact detail reads,
missing records and denied reads for all four record types. CLI tests
covered private-file requirements, stale-plan rejection and receipt
readback for each command group. Two Chrome scenarios passed. The
payroll scenario created overtime and a timesheet through the real CLI,
approved both as a different actor, locked the timesheet and reconciled
the resulting period in the portal. Backend lint and mypy, generated
OpenAPI and TypeScript, frontend lint, 50 Vitest cases and build passed.

## Slice 66 · reconcile legacy work dates for cross-month leave

HR can propose exact historical work dates for a previously approved
cross-month request with missing dates. A different reviewer approves
or rejects that exact proposal. The service verifies the original debit,
approved units and request revision, and refuses to change source dates
when an approved payroll run already covers that employee and date
range. Approval retains the dates without posting another debit or
recalculating the historic calendar. Revision 058 creates an empty
evidence table and performs no backfill.

All 55 HR tests passed. The focused PostgreSQL rerun checked a payroll
lock that appeared after the proposal, revision and digest checks,
independent authority, exact replay and the restored month split with
one unchanged debit. Two Chrome workflows passed, with the historical
date workflow passing again after the focused rerun. Chrome exercised
invalid units, separate approval and readback after reload. Ruff, mypy,
OpenAPI, generated types, frontend lint and build passed. Production data
and policy have not been changed.

## Slice 67 · integrated HR regression and populated migration rehearsal

A disposable PostgreSQL 18 database at revision 013 was seeded with a
synthetic employee, approved cross-month leave and its debit, encrypted
compensation, an existing benefit and a reimbursement. The complete
upgrade to revision 058 preserved the projected original IDs, status,
amounts, approval fields and encrypted compensation bytes. The upgraded
application decrypted the compensation term, kept missing legacy work
dates explicit, and created no advance, adjustment, closure, correction
or leave evidence records by inference.

The complete local backend suite passed in two isolated CI-equivalent
shards. The JUnit reports covered 306 and 621 unique tests, with no
failures, skips or overlap. An earlier unsharded run exposed an SMTP
test that inherited the local useSend transport setting. The fixture
now selects SMTP explicitly. All 67 Chrome scenarios passed. The final
browser manifest covers 31 and 36 cases without overlap or omissions.
Local timings project a more balanced Chrome split. The next self-hosted
run still needs to measure CI wall time. Compose configuration and
deployment script syntax checks passed.

The database fixture was synthetic. No production database, keys, roles
or deployment were modified. HR's approved policy, authorized operator
assignments, Finance's operational correction process, and the actual
production maintenance and recovery verification remain open.

## Slice 68 · company policy editions and employee acknowledgments in the CLI

Company policy publication now has an actor-bound CLI preview that pins the
edition, predecessor, and checksum of the exact approved attachment. Linked
employees can list and read their visible editions, download the pinned
file into a new owner-only path, and acknowledge the named version. The
employee-owned download response includes the registered size and hash so
the CLI can verify the bytes. Historical acknowledged editions keep their
own attachments and receipts. This change requires no migration.

The 56-test HR suite and two Chrome workflows passed. The policy workflow
published the replacement through the CLI, downloaded the exact original
file using the employee account, and retained separate receipts across
reload. Focused tests refused a changed attachment plan, a mismatched
edition, and altered bytes. Backend lint and mypy, OpenAPI, generated
TypeScript, frontend lint and build passed. Production was unchanged.

## Slice 69 · discover and reconcile missing historical leave dates

HR can find approved, full-day cross-month leave with missing work dates in
the portal and CLI. Requests covered by approved payroll explicitly require
the payroll correction workflow. The CLI supports proposal and independent
review using previews that bind the actor, affected request and expected
state. The original leave debit is preserved. No new migration is required.

All 56 HR tests passed on disposable PostgreSQL. One Chrome workflow passed
through candidate discovery, CLI proposal and independent approval, and
readback after reload. Reconciliation of live records remains open pending
the historical evidence for each affected request.

## Slice 70 · work calendar administration in the CLI

HR can read calendars, create and revise drafts, submit, review, and publish
through the existing work calendar API. Writes bind the signed-in actor,
request and current revision to the preview. The CLI reads back the
resulting revision and status. Approval still requires a different HR
Manager from the creator and submitter. No migration is required.

Two calendar tests passed on disposable PostgreSQL. The Chrome scenario
passed through a portal draft, CLI create and revision, stale-plan and
self-approval rejection, independent CLI approval, and portal publication.
CLI readback and an attendance import confirmed the published calendar was
available to the existing time workflow.

## Slice 71 · roster allocation and cancellation in the CLI

HR can list and inspect allocations, assign a published shift, and cancel
an allocation using an actor-bound preview and saved-record verification.
The create preview binds the request identifiers and date. The server
resolves the shift when it applies the allocation. The exact read uses
the existing attendance permission and disables caching. Write receipts
omit names and cancellation reasons. No migration is required.

The PostgreSQL regression passed exact and denied reads, preserved overnight
overlap enforcement and retained cancellation history. The Chrome workflow
passed portal and CLI allocation and cancellation, idempotent allocation
replay and reload. Backend lint and typing, OpenAPI and generated types,
and frontend lint and build passed.

## Slice 72 · salary confirmation from approved compensation

Salary confirmation drafts use the current independently approved
compensation term for base salary, currency and pay frequency. The draft
retains the term reference and verifies it again at issuance. Only HR
Managers with payroll-sensitive access can prepare or review a salary
confirmation. The linked employee can read their own issued letter. Text
remains encrypted, and the audit records the source reference without
logging the salary or letter text.

All 57 HR tests passed on disposable PostgreSQL. Coverage included blocked
caller-supplied salary values, a future term, a source change with identical
pay, independent review, permission revocation and recipient isolation.
Two Chrome workflows passed for salary and ordinary letters. The populated
058 to 060 upgrade preserved an existing letter and validated the new
source reference. Production templates, data, operators and migration
execution remain open.

## Slice 73 · reverse approved leave against the original debit

HR can reverse approved leave from the portal with a reason. The service
verifies the exact debit before adding a single reversing credit. The
audit identifies the original debit and the approval or reversal checks
for approved payroll under the payroll lock. The employee can see the
result and reason in My HR. No migration is required.

All 60 HR and accrual tests passed on disposable PostgreSQL. The regressions
covered missing reasons, a mismatched debit, denied employee reversal,
concurrent reversals, and blocked changes for approved payroll.
Two Chrome workflows passed after correcting My HR to show the cancellation
reason after reload. The legacy dates review remained available. Lint,
typing, frontend build and the OpenAPI check passed.

## Slice 74 · verify attached payroll evidence at approval

The API reproduced an approval after the run's attached leave evidence
changed through a reversal. Approval now locks the snapshot roster and
reconciles both attached sources against their frozen digests. A conflict
leaves the run calculated and the period open. The earlier snapshot and
its files stay available for authorized review. The recheck runs inside the
approval transaction and uses the existing approval and sensitive grants.
Source previews retain their separate preparation permission.

All 60 HR and accrual tests passed on disposable PostgreSQL. The regression
proved that a leave reversal blocks approval by a reviewer without the
preparation grant and that the original file is unchanged. In Chrome, a
pending overtime request blocked approval. After the request was rejected,
the matching snapshot was approved and the original payroll workflow
completed through payslip publication, Finance reconciliation and closure.
The legacy leave evidence workflow also passed in Chrome.

## Slice 75 · verify compensation at payroll approval

Approval checks roster eligibility and the exact approved compensation term
used for each employee. A superseded term leaves the original snapshot
readable and the period open for a new run. The recheck uses the same
employee locks as calculation and source reconciliation.

The API reproduced approval of a superseded term before the change. The
regression now rejects it even when the replacement has the same amount.
Two replacement snapshots use the updated term, and only one can lock the
period. All 60 HR and accrual tests passed on disposable PostgreSQL. The
salary confirmation and payroll-to-settlement Chrome workflows passed.
Backend lint, typing and the OpenAPI check passed.

## Slice 76 · retain the controlled payroll policy record

The policy form records the restricted system's opaque document identifier,
version, effective date and approved decision reference. The reviewer sees
these before independent approval. Calculation rejects use before the
effective date and keeps the record in the encrypted snapshot. Existing
policies and legacy API clients retain compatibility.

All 60 HR and accrual tests passed on disposable PostgreSQL. The API test
rejects a URL in place of the identifier and an approved policy effective
after the period start. A populated upgrade from 060 to 061 preserved the
preexisting policy and rules. Backend and frontend static, contract and
build checks passed. The Chrome payroll workflow verified entry, independent
review, snapshot readback and completion through Finance reconciliation.

## Slice 77 · validate worked examples before payroll policy approval

The controlled record accepts one to twelve synthetic examples. The same
Decimal calculation computes examples and payroll lines. The service
checks gross, deductions and net and leaves a mismatched policy pending.
The independent reviewer sees the retained examples, and the snapshot
stores them with the controlled source. The existing JSONB field holds
the examples.

All 60 HR and accrual tests passed on disposable PostgreSQL. The API
rejected an incorrect expected net at approval and retained the draft.
The Chrome payroll workflow entered and reviewed an adjustment example and
completed through settlement. Lint, typing, OpenAPI and build checks passed.

## Slice 78 · correct a pending payroll policy draft

The original preparer can revise a pending controlled policy under the
same ID. Revisions and approvals serialize on the policy row. A reviewer
submits the version they opened so an intervening correction returns a
conflict. Existing approved policies retain their content and reference.
The new draft workflow uses the existing timestamp and requires no
schema migration.

All 60 HR and accrual tests passed on disposable PostgreSQL, including
non-owner edits, stale edits and approvals, and edits after approval.
Chrome verified a failed worked example, correction by the preparer,
rejection of the previous review version, and approval after reopening.
The scenario continued through Finance reconciliation. Lint, typing,
OpenAPI, generated types and build checks passed.

## Slice 79 · integrated payroll candidate verification

The local worktree based on `c4a61cd` passed all 929 backend tests
across the two CI-equivalent PostgreSQL shards, all 50 frontend tests,
and all 68 Google Chrome scenarios. JUnit reports showed no failures or
skips. The populated 013-to-061 upgrade preserved the seeded employee,
leave debit, benefit and claim history and decrypted the original
compensation record. Frontend lint, generated contract, build, Compose
configuration and deployment shell syntax checks passed.

Retiming the Chrome cases moved one existing scenario from the slower
selector to the faster one. The 33/35 selectors contain all 68 cases
without overlap. The estimated test-time sums are 171.40 and 170.84
seconds. Measure actual runner wall time when this worktree is published.

The last published `main` had green self-hosted CI on `c4a61cd`.
Its production workflow stopped before deployment because schema
revisions require maintenance. These local results do not establish
production payroll acceptance or authorize a database change.

## Slice 80 · find reviewed employment changes due for application

The HR portal and CLI list approved changes that have reached their
effective date, based on the configured business date. The list is
paginated, omits proposal reasons and values, and identifies employee
revisions that have changed since review. The existing employee detail
and apply workflow still checks that an exact change remains current.
The queue requires existing sensitive employee access and no migration.

All 60 HR and accrual tests passed on disposable PostgreSQL. The API
coverage checked future and applied exclusion, pagination, restricted
access and stale revision status. Chrome found an approved change from
the queue, inspected its employee, applied it and confirmed it left the
queue. The same browser scenario verified the real CLI listing and
existing apply command. Lint, typing, contracts and build passed.

## Slice 81 · rehearse account provisioning and credential delivery

A disposable PostgreSQL and Redis environment exercised the real user
creation, role readback and authentication APIs. The managing director
issued separate CLI previews and applied them for two synthetic accounts
with different roles. A second create for the same email was refused.
The configured application mail service sent an individual synthetic
temporary password to each recipient through a loopback SMTP sink.
Each account authenticated with its own password and the OTP received by
the sink. The API did not expose a development OTP. The HR account had
directory access and the site supervisor received a denial. A rejected
SMTP recipient surfaced as a delivery error.

This rehearsal used synthetic recipients and an SMTP sink. Production
sender delivery and live account creation remain unexecuted. The supplied
roster includes display names, emails and role columns. Creating any
account missing from the production directory also requires its approved
employee code and phone value. Existing accounts can be reconciled with
their existing identifiers. The restricted roster and all generated
credentials stayed outside Git.

## Slice 82 · payroll policy CLI review

Payroll preparers can propose and correct a controlled policy from a
private JSON file. An independent reviewer can save the exact policy to
a new owner-only file. Approval validates the review digest and the
current record revision. Receipts omit rules, restricted references and
worked-example amounts.

All 76 targeted HR, accrual and CLI tests passed on disposable
PostgreSQL. The Chrome payroll workflow passed with actual CLI proposal,
private review download, correction, stale review rejection, independent
approval and readback, followed by the portal settlement workflow. Ruff,
mypy, frontend lint and browser TypeScript checks passed.

The production policy reference, approved examples and operational
assignments remain unconfirmed. This slice used synthetic policy data.

## Slice 83 · recheck the local release candidate and onboarding roster

The local `7df303d` application candidate passed 929 PostgreSQL tests
and 50 frontend tests. Both backend shards had zero failures or skips.
The populated upgrade from revision 013 to 061 preserved existing HR
rows and decrypted the original synthetic compensation. The OpenAPI and
generated TypeScript contracts matched.

The first full Chrome run passed 67 cases. The interview withdrawal case
timed out because more than 20 generated HR accounts shared one display
name and the intended account was outside the first lookup page. Browser
fixtures now give synthetic users unique names. The full rerun passed all
68 cases in 2.9 minutes. The 33/35 Chrome selectors cover each case once
and sum to 172.20 and 161.33 seconds of local case time. The backend
shards ran in 98.45 and 116.11 seconds locally. The next published
self-hosted run is needed to measure CI wall time for this candidate.

The account roster has 12 distinct email entries. Two lack a role and one
uses the retired HR Executive title. The CLI guide now records role
readback and credential delivery separately. No new production migration,
account assignment, or credential delivery was performed in this slice.

## Slice 84 · disambiguate interview invitations

The recruitment picker lists employee codes beside active portal
interviewers' names and accepts the exact employee code. An exact code
match comes first even if a different user's name matches the search.
The response contains the user ID, name and employee code. Recruitment
authorization and active-account checks still apply. No migration is
needed.

Five focused recruitment API tests passed on disposable PostgreSQL,
including two active accounts with identical names, an inactive account,
a misleading name match and a denied non-HR request. The Chrome workflow
selected an interviewer by employee code, then withdrew the application
and confirmed cancellation of the assigned interview. Backend lint and
typing, frontend lint and build, and generated API type checks passed.

## Slice 85 · verify training, performance and employment changes together

The portal records progress, no-show and cancellation on open training
enrollments and rejects an update if its starting status changed. The CLI
lists and creates courses and enrollments, confirms enrollment status changes,
and reads the saved state back. Training completion still requires an approved
certificate version. Participants can submit performance actions through an
actor-bound CLI plan. The receipt confirms the event without displaying notes
or ratings. The portal and CLI use the server's business date for effective-dated
employment changes and identify proposals whose employee revision changed.

The combined local worktree on main `06c0f9d` passed 184 selected backend
tests and all 50 frontend unit tests. The backend selection covered HR,
garrisonctl, OpenAPI, authentication, Super Admin sign-in and role transitions
against disposable PostgreSQL, Redis and object storage. The 31 selected
Chrome cases passed, including training verification after a status change,
employment scheduling and application, and HR access revocation. Repository-wide
backend Ruff and mypy and the OpenAPI and generated TypeScript checks passed.

These results cover the local application and test data. Live HR acceptance,
account onboarding and payroll operating approval remain open.

## Slice 86 · verify the HR-only release candidate on self-hosted CI

The verification branch tested `c06d18196f89d2ab2f4193de8def951532793b4c`
through a manual self-hosted [CI run](https://github.com/nirzaf/garrison-investments/actions/runs/44016668981).
All seven jobs passed, including 942 backend cases across both shards and
68 Chrome cases. This candidate bundles the isolated training, leave,
employment and CLI changes with the service-request categories and queue.
It carries no Alembic, production Compose or deployment workflow changes
relative to the deployed `06c0f9d` release. The manual verification run did
not deploy the candidate.

CI elapsed time was 800 seconds and summed job time was 1,528 seconds.
The Chrome test steps took 428 and 413 seconds. Dependency and storage setup
took 10 and 12 seconds for those jobs. The prior successful main run took
815 seconds. Both runs used the same workflow settings, so this sample does
not establish a pipeline speedup.

## Slice 87 · production rollout of the HR candidate

Main CI for `c06d181` stopped deployment because a Chrome assertion matched
both a search result and the selected historical leave request. Commit
`fa73693` scopes the assertion to the selected request. It passed three
consecutive isolated Chrome repetitions and all seven jobs in the exact
main CI, which took 804 seconds.
[`c06d181` main CI](https://github.com/nirzaf/garrison-investments/actions/runs/44018706490) ·
[`fa73693` main CI](https://github.com/nirzaf/garrison-investments/actions/runs/44020386126)

Production deployment `44021927486` activated `fa73693` at schema
`202605310061`. No migration ran. The standard pre-activation backup completed
and was not omitted. The host receipt and database readback agreed, the public
readiness endpoint reported `ready`, the unauthenticated HR queue returned
401, and no running business role had a payroll grant. HR onboarding and
authenticated HR acceptance remain pending.
[Production deployment](https://github.com/nirzaf/garrison-investments/actions/runs/44021927486)

## Slice 88 · HR service request queue in garrisonctl

The CLI now pages and inspects the existing HR request queue and discovers
eligible assignees. Assignment and resolution use an actor-bound dry run,
the current request timestamp and API readback. Free-text fields stay out
of terminal output. Full request detail can be saved to a new owner-only file.
See the [CLI guide](CLI_ADMINISTRATION.md#workforce-administration).

All 48 CLI tests passed, including a synthetic request paging, private-file,
assignment, permission and resolution scenario against an HTTP mock. Ruff and
mypy passed for the changed Python files.

An isolated HTTP smoke test used the deployed source baseline at revision
202605310061 plus the CLI changes and a fresh PostgreSQL 18 database. It
verified denied access for a Quantity Surveyor, owner-only export, refusal of
plans from a different actor or stale request, assignment between two
synthetic HR Managers, and completion with persisted notes. The CLI changes
have not been activated in production.

## Slice 89 · workbook onboarding field checks

The restricted workbook preview flags missing Employee ID and Mobile Number
for rows requesting a new portal account. It shows the affected entries in
the HR workspace and reuses the existing per-row issues in the CLI report.
The supplied values are omitted from the preview and are not imported.
Changing the workbook or role mappings clears the previous preview.

The PostgreSQL regression passed for the legacy and expanded CSV layouts,
including the original idempotent draft apply. The focused Chrome regression
verified visible per-person issues, omitted source values, and invalidation
after a role-mapping edit. The frontend build and lint, backend Ruff and mypy,
and the OpenAPI comparison passed. Only synthetic workbook data was used.

## Slice 90 · combined HR candidate regression

The isolated archive of `4846fe9d1432e2a2d020e868da328e9c2506c44f` contains
the workbook and service request CLI changes. Both disposable databases were
migrated from empty to revision 202605310061. The backend/CLI run returned 106
passes and the Chrome selection `(HR |payroll)` returned 28 passes in 3.4
minutes. The backend used PostgreSQL 18, Redis, and a local Moto S3 endpoint.
A synthetic XLSX parse also preserved leading zeros and the country prefix
in the new columns. The candidate has no delta in migrations or deployment
configuration from production `fa73693`.

The last exact-main CI, run 44020386126, spent 426 and 408 seconds in its two
Chrome test steps. Their JUnit reports logged 411.1 and 392.3 seconds of
case time. Dependency and storage preparation took 11 and 12 seconds.
The second browser job started 68 seconds after the first and finished
last. The local candidate regression does not establish a self-hosted
speedup. The next comparison is runner scheduling and Chrome case time
on the candidate's self-hosted run.
[Latest production CI](https://github.com/nirzaf/garrison-investments/actions/runs/44020386126)

## Slice 91 · separate HR Executive read role

HR Executive uses `hr_executive_reader` and has exactly `users:read`,
`dashboard:scoped`, `reports:view`, and `documents:view`. The historical
role key stays retired. The [task matrix](HR_WORKFORCE.md#hr-executive-scope-and-proposed-hr-tasks)
records the worksheet's pending review, the four approved grants and the
decisions that gate any future preparation duties. Existing onboarding and
HR vault entry points now check their current permissions in the service
before a record lookup, in addition to the HTTP route.

The local PostgreSQL/S3 suites passed 166 HR, authorization and CLI tests
and 172 auth, import and release-contract tests. Four Chrome scenarios
passed, covering role navigation, catalogue parity and retained HR Manager
offboarding and training. Ruff, mypy, ESLint and the OpenAPI and generated
TypeScript checks passed. No migration, account assignment or production
activation was performed.

## Slice 92 · exact HR candidate on self-hosted CI

Verification of `b8a34ba` found an integration assertion that still expected
the previous user-directory role catalogue. Commit `21750a2` adds the new
role to that independent expectation and verifies its exact grants and
non-assignability to the scoped reader of the catalogue. Thirty focused
tests passed locally. The superseded verification run had one failing
backend shard and its browser jobs were cancelled after the replacement
was queued.
[First verification run](https://github.com/nirzaf/garrison-investments/actions/runs/44026035722)

All seven self-hosted jobs passed on exact commit
`21750a2a425f91b4d5811e8ac77f0e3ddec9deb8`. The two backend shards passed
314 and 637 tests and the two Chrome shards passed 34 and 36 scenarios.
The workflow took 17m 15s including 3m 25s before the first job started.
The later Chrome shard started 2m 09s after the first and finished last.
The workflow ran on the verification branch. Remote main and production
remained on `fa73693`.
[Exact candidate CI](https://github.com/nirzaf/garrison-investments/actions/runs/44026987785)

## Slice 93 · production release of the scoped HR candidate

The exact `21750a2` push to main passed all seven self-hosted CI jobs on
attempt 1, including 951 backend, 50 Vitest and 70 Chrome cases with no
failures or skips. CI took 13m 02s. The Chrome jobs began five seconds apart,
compared with 2m 09s apart for the same candidate's verification run.
Combined Chrome case time was 803.8 seconds. Runner scheduling changed
between the runs. The release did not change CI configuration.
[Main CI](https://github.com/nirzaf/garrison-investments/actions/runs/44029735679)

Hostinger activated the same SHA on deployment attempt 1. The standard
pre-activation backup completed in three seconds. Before and after
activation, the host receipt and PostgreSQL query agreed on
`202605310061`. No migration ran. Public readiness returned `ready` and
`connected`, and the anonymous HR request queue returned HTTP 401.
The running backend exposed the HR request CLI and the four approved HR
Executive grants. PostgreSQL showed zero HR Executive assignments and
zero active HR Managers. The application granted payroll to zero roles.
The receipt records formal acceptance pending.
[Production deployment](https://github.com/nirzaf/garrison-investments/actions/runs/44031348063)

## Slice 94 · isolate restricted employee-relations records

The case API bounds and scopes lists to the opener, withholds narratives
and resolution notes from list responses, and audits detail disclosure.
A linked employee cannot open or act on their own case. Closed records
reject subsequent mutations. New resolution notes use the existing HR
encryption key and storage column. Scoped detail can read legacy notes,
and an omitted note preserves the prior note. General vault routes keep
disciplinary material unavailable pending explicit case-linked authorization.
See [restricted employee-relations cases](HR_WORKFORCE.md#restricted-employee-relations-cases).

An HR-only overlay on `21750a2` passed 82 focused backend and CLI tests
on disposable PostgreSQL at revision `202605310061`. The case scenario
covered cross-account and subject denial, encrypted persistence, legacy
readback, document denial, and concurrent closure with one recorded
decision. Ruff, mypy and generated contract checks passed.

## Slice 95 · compensation review in garrisonctl

The CLI lists compensation metadata, saves an exact private review copy,
and uses actor-bound plans for proposal and independent decision against
the existing HR API. Salary, allowances and decision reasons stay out of
terminal output. Apply rechecks the reviewed term and verifies the saved
outcome. Existing payroll permissions and locked-period rules remain in
force. See [CLI workforce administration](CLI_ADMINISTRATION.md#workforce-administration).

An HR-only overlay on `21750a2` passed 116 backend and CLI tests
on disposable PostgreSQL at revision `202605310061`. The compensation
test used the real HR API and two synthetic operators. The HTTP mock
covered private output, distinct approval, stale and actor-mismatched
plans, replay denial, and masked terminal output. Ruff and mypy passed.

## Slice 96 · benefit policy and coverage in garrisonctl

The CLI now proposes benefit types, exports an owner-only policy review
copy, records independent approval and assigns dated employee coverage
through the existing HR API. It excludes ceilings and private coverage
notes from terminal output. An HR-only candidate passed 117 backend and
CLI tests on disposable PostgreSQL. The real-API scenario verified
self-approval and tampered-copy denial, an actor-bound plan, and refusal
of pending and overlapping coverage. The change was neither pushed nor
deployed.

## Slice 97 · reimbursement submission and independent review in garrisonctl

The CLI lists masked claim metadata and writes a private review copy.
Submission pins an approved receipt and an actor-bound plan. A retry
with the same key returns the same claim. An independent reviewer applies
a plan bound to the exact claim and decision. The CLI verifies persisted
readback after submission and decision. The new claim detail route requires
the existing payroll-sensitive permission, audits each successful read
and disables caching. See [CLI workforce administration](CLI_ADMINISTRATION.md#workforce-administration).

An HR-only overlay on `21750a2` passed 118 tests on disposable PostgreSQL
and S3-compatible storage. The CLI integration exercised real API
submission, same-key replay and changed-body conflict, independent
review, external settlement recording, unauthorized detail denial and
private output. Ruff, mypy, OpenAPI export and generated TypeScript
checks passed. No schema migration, permission grant, push or production
deployment was required for this verification.

## Slice 98 · restricted employee-relations case CLI

The CLI opens, lists, inspects and updates cases under the existing
restricted permission and opener-only scope. Terminal receipts omit the
title, case code, employee ID, narrative and resolution. A reviewed
update compares the exact reviewed state under the case lock and
returns a conflict if another writer changed it before the decision.
Omitting resolution notes preserves the previous text.

The HR-only overlay on `21750a2` passed 119 tests on disposable
PostgreSQL and S3-compatible storage. The real-API CLI test verified
private output, opener isolation, duplicate prevention, a stale
update injected between preview and write, and persisted closure
with the newer note intact. Ruff, mypy, OpenAPI and TypeScript contract
checks passed. The case permission remains unassigned in production.

## Slice 99 · restricted employee-relations browser workspace

The Employee relations navigation and route require the existing
restricted case permission. The page opens cases, lists the opener's
records, and loads the full review only when selected. Review responses
carry a digest. Browser updates send that digest and preserve draft notes
when the API rejects a stale review.

The isolated HR overlay on `21750a2` passed four backend checks and
four Chrome scenarios. Chrome verified case creation, newer-note
conflict and deliberate retry, persisted closure after reload, and access
denial to another HR operator and to a director without the case grant.
The other scenarios covered offboarding and rehire, training, and HR
Executive navigation. The isolated production build, Ruff, mypy, and
OpenAPI and TypeScript contract checks passed. The full dirty worktree
still has two type errors in the in-progress Super Admin panels.
No production permission was granted and no deployment was performed.

## Slice 100 · overnight attendance and incomplete punch validation

The attendance CSV preview shows the validated check-in and check-out
timestamps with their original offsets. The import rejects a single
punch and applies the batch only when all rows pass. The preview and
apply responses disable caching.

An HR-only overlay on `21750a2` passed six backend checks and two
Chrome scenarios. PostgreSQL readback retained the check-in work date
and both instants across midnight. The API rejected a UTC date that
did not match the employee calendar date. Chrome verified that a
missing punch disabled Apply and that the corrected overnight row
was submitted and independently approved. Ruff, mypy, ESLint, the
isolated production build and both API contract checks passed.
No attendance or payroll policy changed. No production deployment ran.

## Slice 101 · attendance CSV import in garrisonctl

The CLI uses the same preview and apply endpoints as the browser. It
binds apply to the signed-in actor, exact CSV bytes and API preview.
Successful receipts identify the committed attendance entries. Clock
times and employee codes are available in an optional owner-only review
file and are omitted from terminal receipts.

The HR-only overlay on `21750a2` passed seven backend checks and two
Chrome scenarios. The real-API CLI test refused an invalid file, wrong
actor, changed file and duplicate attempt. It verified the committed
entry's identity, submitted state and overnight timestamp through a
separate API read. The local production build passed. The work remains
in the main worktree and has not been pushed or deployed.

## Slice 102 · leave entitlement profiles, final supervisor decisions and celebrations

The existing leave ledger, policy review, calendar, accrual, rollover and HR
workspace remain the source of truth. Additive revisions 113–114 add managed
annual/casual rule metadata, route and fallback evidence, reconciliation
baselines, notification event revisions and guarded idempotency indexes.
Approved managed annual policy profiles support zero annual credit in the
first calendar service year, an explicitly reviewed 4–14 day bracket in the
second, 14 days from the third year, no carry-forward, and a reviewed basis for
the seven-day block. Casual profiles support 0.50 days per completed first-year
service month and 7 days from the second year. Credit planning, preview/apply,
catch-up, baseline reconciliation, rollover and the employee balance projection
use the existing Decimal ledger and transaction safeguards. New policy/type
configuration remains inactive until independently approved and supplied with
the required HR inputs.

Leave submissions freeze the current direct supervisor route when eligible.
That supervisor makes the final decision through a relationship-scoped queue;
HR retains visibility and uses the existing approval permission only for an
explicit, reasoned fallback. The final decision, debit or rejection, audit
event and revision-scoped portal/email notifications share the request
transaction. Existing advisory attendance/time reviews, permission grants,
leave status values and generic policy behavior remain unchanged. The dashboard
loads birthdays and anniversaries through separate minimal private responses:
birthdays expose only name and day/month for seven days; anniversaries expose
name, day/month and completed years for thirty days. These cards do not expand
the HR directory or dashboard summary.

### Slice 102 verification (historical record)

At the time of that verification, the source baseline was
`60836daac4b77fe8cf6ba7fff206bfcc6bb343a0` on local `main`; the implementation
overlay was uncommitted. All test data used disposable loopback PostgreSQL
databases. No production database, accounts, mail delivery or deployment was
accessed. The later main revision `7203f00f0bf504d563d63b6090c848b8da51a5e0`
contains the managed leave and employee milestone baseline. The historical
counts below remain tied to the Slice 102 test run and are not tests executed
on that later SHA.

- Fresh schema upgrade to Alembic head `202605310114` passed. A populated
  forward-upgrade rehearsal from `202605310112` to `202605310114` retained the
  synthetic approved request, its one `taken` ledger entry and its pre-existing
  notification unchanged.
- `cd backend && .venv/bin/ruff check . && .venv/bin/mypy .` passed; mypy found
  no issues in 464 source files. `scripts/export_openapi.py --check` passed and
  reported `docs/openapi.json` current. Alembic reported one head,
  `202605310114`.
- `cd backend && .venv/bin/pytest -q -rs` passed **1,458 tests**, with **6
  skipped**: five Docker opt-in forward-stack tests and one explicit Docker
  ingress check. The run emitted 18 deprecation warnings.
- `cd frontend && npm run lint && npm run api:types:check && npm test && npm run build`
  passed. Vitest reported **14 files and 66 tests passed**. Browser TypeScript
  compilation passed. The production build completed with the existing
  large-chunk warning.
- The full Chrome suite ran **90 tests: 89 passed, 1 skipped**. The skip is the
  dedicated single-owner support-custody case, which requires a matching test
  deployment mode. A focused leave workflow also verified employee submission,
  final direct-supervisor decision, HR visibility, and birthday/anniversary
  card privacy. The updated linked-employee leave lifecycle browser regression
  passed.
- Production Compose validation, release shell syntax, `git diff --check` and
  `graphify update .` passed.

### Slice 102 remaining policy and release dependencies

Implementation and local tests do not activate an HR policy. HR still needs to
approve the calendar-year/service-start and rehire conventions; supply all 366
second-year annual bracket values; select the seven-day-block basis; approve
effective dates, policy source references and sick/maternity/unpaid eligibility,
pay, evidence and expiry rules; reconcile actual opening balances and direct
supervisor assignments; and publish the relevant work-calendar coverage. No
employee entitlements or manager assignments were fabricated. The earlier
worktree had no commit SHA or hosted evidence. For revision
`7203f00f0bf504d563d63b6090c848b8da51a5e0`, the supplied hosted evidence is
[push CI run 45749108343](https://github.com/nirzaf/garrison-investments/actions/runs/45749108343)
and [deployment workflow 45749874396](https://github.com/nirzaf/garrison-investments/actions/runs/45749874396).
Both workflows were read back as successful for that SHA during this task;
the CI browser steps were skipped, and workflow success is not independent
live image/schema/readiness verification. No production readback or business
acceptance is claimed. No push or release was requested for the new local
candidate.

## 60-finding implementation closure register · local candidate

This register records the implementation contract against the actual local
worktree based on `7203f00f0bf504d563d63b6090c848b8da51a5e0` (`main`), with
`origin/main` matching that baseline when fetched. The candidate is uncommitted;
its Alembic head is `202605310115`. The current working tree also contains
pre-existing user changes in `docker-compose.yml` and two Celery beat sidecar
files. They are excluded from the implementation fingerprint and were not
edited. `COMPLETED` means the scoped code and focused evidence passed locally;
it does not imply business activation, hosted checks, production readback or
UAT. `BLOCKED_POLICY` and `BLOCKED_AUTHORIZATION` identify external gates, not
reasons to weaken the existing role or policy controls.

| Finding | Status | Local implementation / verification evidence | Remaining dependency |
| --- | --- | --- | --- |
| LM-01 | PARTIAL | `hr_workforce_service.py` current-route resolver and reasoned temporary-fallback restoration; four focused route/fallback tests passed on a fresh disposable PostgreSQL database; Ruff, Mypy (465 files), OpenAPI, and generated TypeScript checks pass. | Sole-eligible-reviewer edge matrix and production roster readback remain unverified. |
| LM-02 | COMPLETED | Revision-required final mutations in `schemas/hr.py` and `hr_workforce_service.py`; focused HR tests and full backend suite | None for local contract; production remains unverified. |
| LM-03 | PARTIAL | Request-specific independent HR eligibility and batched list projection in `hr_workforce_service.py` / `api/v1/hr.py`; focused tests cover subject/maker exclusion, no eligible HR account, multiple eligible reviewers, mutation denial, notification eligibility, and bounded page queries. | Verify current production operator assignments and full role acceptance. |
| LM-04 | PARTIAL | Managed baseline/accrual reconciliation guards in `hr_leave_accrual.py` and `hr_workforce_service.py`; accrual/HR tests | Approved roster balances and policy inputs are unavailable; complete all concurrent and stale-receipt cases. |
| LM-05 | PARTIAL | Managed carry/credit guard in `hr_leave_rollover.py` and `hr_workforce_service.py`; leave tests | Complete category-window and concurrent credit/debit matrix; approved live inputs remain absent. |
| LM-06 | PARTIAL | Direct/reviewed manager updates reroute pending leave in `hr_service.py`; HR tests | Full writer/concurrency matrix and authorized manager/account roster readback. |
| LM-07 | COMPLETED | Open-ended shift and ambiguous schedule handling; `test_site_attendance.py` / `test_hr.py`; backend suite | No local dependency; real calendar coverage still requires approved data. |
| LM-08 | PARTIAL | Existing `HrLeaveDateEvidence` review is retained. Focused disposable-PostgreSQL regressions verify the existing date-evidence flow and unmet-block denial; `test_annual_block_reassesses_after_reviewed_legacy_date_evidence` confirms an approved historical date repair changes `unverified` to `taken` while preserving the approved request and original debit, after which the existing zero-carry rollover preview is allowed. | No closure exception was added. Zero-carry expiry despite a genuinely unmet block remains disabled until an owner-approved source policy expressly permits it and names an independent decision authority; CFG-04 records that both are absent. |
| LM-09 | BLOCKED_POLICY | Existing inactive, policy-required leave type behavior retained; HR tests pass | Approved sick, maternity and unpaid rules, source references and effective policies are missing. |
| LM-10 | PARTIAL | Self-service requestable leave type filtering and empty/stale selection handling; HR UI/API changes and suite | Add direct inactive-ID and historical-label acceptance coverage. |
| LM-11 | PARTIAL | Explicit accrual outcome labels in `HRLeaveAccrual.tsx`; frontend tests/build pass | Add all mixed catch-up/stale digest visual cases. |
| LM-12 | PARTIAL | Server-derived leave action/route projections and scoped UI; API contracts regenerated; HR suite passes | Complete actor-name/time projection and former-reviewer/stale-route acceptance matrix. |
| NT-01 | ALREADY_SATISFIED | Existing submit/resubmit event path and revision-key uniqueness retained; `test_hr.py`, `test_notifications.py`, full backend suite | Production email delivery is not established. |
| NT-02 | PARTIAL | `tasks/email.py` revalidates leave route/revision/recipient; notifications and HR tests pass | Real transport, retry race and every terminal-recipient case remain unverified. |
| NT-03 | COMPLETED | Additive notification supersession migration 115, unread projection and neutral UI state; notification tests, full backend and browser shards pass | None for local implementation; old signed-in users still need deployed rollout. |
| NT-04 | PARTIAL | Request-specific missing-reviewer setup projection and route refresh retained; API/notification tests pass | Verify configured/unconfigured transition and actual mail queue/worker status with approved test accounts. |
| CE-01 | PARTIAL | Minimal birthday/anniversary eligibility and stable service-date logic in `dashboard_service.py`; dashboard tests pass | Complete termination/rehire boundary matrix and authorized directory data-quality follow-up. |
| CE-02 | PARTIAL | Synthetic date/window/pagination service tests; full frontend and both Chrome shards pass | Mobile/identity-switch cache and full leap-year browser scenarios remain. |
| CE-03 | PARTIAL | Paginated HR-only data-quality projection and authorization tests; no guessed corrections | No live data-quality counts or HR-owned source corrections authorized; a dedicated HR issue UI remains. |
| CFG-01 | BLOCKED_POLICY | Existing exact bracket contract preserved; synthetic rules remain test-only | HR-approved complete 366-day 4–14 bracket table and source/version are absent. |
| CFG-02 | BLOCKED_POLICY | Calendar-join-year convention preserved and synthetic tests retained | HR confirmation of calendar-year versus anniversary-year basis is absent. |
| CFG-03 | BLOCKED_POLICY | Existing employment-period/service-month conventions preserved | HR approval and verified continuous-service/rehire source records are absent. |
| CFG-04 | BLOCKED_POLICY | Existing seven-day assessment retained | HR-approved calendar-day/workday basis and any explicit closure exception are absent. |
| CFG-05 | BLOCKED_POLICY | Additional types remain inactive unless explicitly configured | Approved sick/maternity/unpaid eligibility, pay, evidence and expiry rules are absent. |
| CFG-06 | BLOCKED_AUTHORIZATION | Actor-bound preview/apply and ledger reconciliation mechanisms retained | Authoritative private balance roster and permission to reconcile actual employees are unavailable. |
| CFG-07 | BLOCKED_AUTHORIZATION | Current manager/account eligibility and cycle checks retained | HR-approved manager-to-account roster and application authority are unavailable. |
| CFG-08 | BLOCKED_POLICY | Published calendar/holiday lookup and fail-closed missing schedule retained | Approved calendar, holiday and assignment coverage is unavailable. |
| CFG-09 | BLOCKED_POLICY | Scheduler allowlist remains disabled unless explicitly selected | Approved policy IDs, completed CFG-01–08, and activation authorization are absent. |
| CFG-10 | BLOCKED_POLICY | Existing reviewed payroll policy and Decimal calculation gates retained | Approved jurisdiction, rules, worked examples and named independent operators are absent. |
| CFG-11 | BLOCKED_POLICY | Unknown valuation and frozen material stages retained; no thresholds enabled | Approved thresholds and historical request dispositions are absent. |
| CFG-12 | BLOCKED_POLICY | Entity-backed approval restrictions retained; no new category enabled | Signed category-specific approval and fulfillment matrix is absent. |
| CFG-13 | BLOCKED_POLICY | HR Executive least-privilege grants and report denial retained | Owner acceptance and verified account mapping are absent. |
| CFG-14 | BLOCKED_POLICY | Financial/unclassified evidence remains fail-closed; audit retention preserved | Approved classification reviewer/retention responsibility is absent; no live reclassification authorized. |
| CFG-15 | BLOCKED_POLICY | Restricted cases remain deny-by-default beyond current opener scope | Approved investigator, reviewer, appeal and evidence assignments are absent. |
| CFG-16 | BLOCKED_AUTHORIZATION | No role/account/project mappings were inferred or granted | Approved UUID-level operator and account mapping/readback is unavailable. |
| SO-01 | PARTIAL | Payroll assignment conflict detection and export refusal; `test_site_attendance.py` and HR suite pass | Complete duplicate/roster override/stale digest cases and live review dispositions. |
| SO-02 | BLOCKED_POLICY | Existing historical owner and MEP/HR checks preserved; no alternate actor bypass | Approved historical reassignment policy and eligible substitute assignments are absent. |
| SO-03 | BLOCKED_POLICY | Locked/closed payroll protections retained; original records are not edited | Approved evidence-linked correction lifecycle and payroll rules are absent. |
| SO-04 | PARTIAL | Existing report includes version-only unclassified evidence; reservation/report tests pass | Independent live classification review and CFG-14 governance are unavailable. |
| SO-05 | BLOCKED_POLICY | Generic category creation remains prohibited; current categories unchanged | Approved category matrix is absent. |
| SO-06 | PARTIAL | Existing incomplete valuation/stock reconciliation retained; synthetic report run returned 7 incomplete valuations and 3 stock-activity rows | Counts are synthetic test-database output only; production dispositions and threshold authorization are unavailable. |
| HR-01 | BLOCKED_AUTHORIZATION | No business-role grants were widened; authorization suite passes | Named least-privilege operator duty assignments are absent. |
| HR-02 | BLOCKED_POLICY | Current versioned payroll rules and validation retained | Approved worked examples and policy inputs are absent. |
| HR-03 | BLOCKED_POLICY | Original closed payroll evidence and correction guards retained | Approved payment/recovery execution policy and independent Finance authority are absent. |
| HR-04 | PARTIAL | Existing closed-run original payslip read regression is covered by HR tests; original publication remains immutable | Replacement statement publication depends on approved correction/settlement policy. |
| HR-05 | BLOCKED_AUTHORIZATION | Existing compensation/payment authorization gates retained | Named Finance/HR capability assignments and duty matrix are absent. |
| HR-06 | BLOCKED_POLICY | Existing restricted case scope and encrypted evidence retained | Approved case investigator/decision/appeal process is absent. |
| HR-07 | BLOCKED_AUTHORIZATION | Reviewed manual employment-change application and reroute retained; no automatic actor introduced | Approved scheduled execution identity and authorization are absent. |
| HR-08 | BLOCKED_POLICY | Current recruitment transitions preserved; no maker identity fabricated | Management decision on recruitment independence is absent. |
| HR-09 | PARTIAL | API-bound leave baseline/review/fallback/route-refresh CLI actions and regressions in `test_garrisonctl_hr_leave.py` | Complete live actor/readback and stale/replay API matrix. |
| HR-10 | PARTIAL | CLI lifecycle inventory and accepted leave actions documented; CLI tests pass | Full accepted admin-operation coverage and policy-gated workflows remain. |
| OPS-01 | UNVERIFIED | Public readiness endpoint returned HTTP 200 with database connected | Deployed SHA, release receipt, schema/image IDs and worker/beat readback were not independently available. |
| OPS-02 | PARTIAL | Current local source tree: full backend 1,522 passed/6 skipped; frontend 15 files/75 tests and production build passed; Chrome 91 passed/1 skipped; fresh disposable PostgreSQL upgrade to Alembic head 202605310116 passed. Full lint, typing, OpenAPI and generated-type checks passed. | No hosted CI or push-triggered run exists for local candidate `69abcd2f907044df12204ebfa9a477170f71c2bb`; this assignment forbids remote writes. |
| OPS-03 | PARTIAL | Existing report executed read-only against synthetic DB; six categories ran, aggregate synthetic rows: 28 legacy material, 7 incomplete valuation, 3 stock activity, 1 legacy attendance, 2 attendance eligibility, 19 unclassified evidence | Production report execution and protected ledger require separate authorization. |
| OPS-04 | BLOCKED_AUTHORIZATION | No live findings were accessed or altered | Assigning owners and applying live disposition requires approved production read access and task-specific authority. |
| OPS-05 | PARTIAL | Isolated mocked notification/mail tests and both browser shards pass | Approved live recipient/provider and worker/beat readback are unavailable. |
| OPS-06 | BLOCKED_POLICY | No managed leave policy or scheduler was activated | CFG-01–09 approvals, balances, calendar coverage and live reviewer roster are missing. |
| OPS-07 | BLOCKED_AUTHORIZATION | No backup or production data was restored | Approved backup destination, key custody, RPO/RTO and restore authorization are unavailable. |
| OPS-08 | BLOCKED_AUTHORIZATION | Synthetic role/browser regression runs completed | Named UAT owner and authorized representative accounts/acceptance are unavailable. |
| OPS-09 | COMPLETED | Slice 102 historical results are explicitly tied to their earlier local run; this register separates baseline CI/workflow evidence from this candidate | No hosted or live claims are made for the uncommitted candidate. |

### Candidate verification snapshot

- Local baseline and remote `main`: `7203f00f0bf504d563d63b6090c848b8da51a5e0`; branch `main`.
- Local candidate: uncommitted working tree based on that SHA; Alembic has one head,
  `202605310115`.
- Fresh disposable PostgreSQL full backend suite: **1,466 passed, 6 skipped**,
  18 warnings. The six skips are five Docker-opt-in forward-stack tests and one
  Docker-ingress test.
- Frontend: `npm ci`, lint, API type check, Vitest (**14 files / 66 tests**) and
  production build passed. Build retains the existing large-chunk advisory.
- Chrome: shard 1 **39 passed**; shard 2 **50 passed, 1 skipped** (the dedicated
  support-custody mode test). A focused leave lifecycle scenario also passed.
- Backend Ruff, Mypy (465 source files), OpenAPI check, Alembic heads, 279 release
  safety tests, production Compose validation, release shell syntax and
  `git diff --check` passed. Graphify updated successfully.
- The six-category read-only report was run only on synthetic disposable data.
  No live database, private employee data, live mail, hosted candidate CI or
  production release/readback was used for this candidate.
- The implementation fingerprint reported at delivery excludes this ledger
  file itself, the pre-existing `docker-compose.yml` user change, and the
  pre-existing Celery beat `-shm`/`-wal` user files. On 2026-11-26, the
  implementation-scope SHA-256 was
  `8895d16a17bb318a151e38953cd1ed8009265da7cf18c7209bc769bb24782474`
  over 34 changed/new feature files.

## 26-finding audit addendum · local candidate based on `37dab2ad`

This addendum records the separate 26-finding assignment whose audit reference
and `origin/main` at preflight were `37dab2ad14d981b71ac048884df3cc47337aab9f`.
The actual local checkout was already at `7175a69133fbed3d8eda1728b979ef2493d5c52d`
(`feat: harden workflow audit remediation`), with the audit implementation
committed locally and additional uncommitted changes preserved. The candidate
remains local and unpushed; its single Alembic head is `202605310116`. These IDs
belong to the 26-finding audit and are not replacements for similarly named IDs
in the 60-finding register above. No production state was read or changed.
`COMPLETED` means local behavior and focused evidence passed; it does not mean
policy activation, production release or UAT.

| Finding | Status | Local implementation and executed evidence | Remaining dependency |
| --- | --- | --- | --- |
| INV-01 | COMPLETED | `InventoryService.consume_daily_report_materials` scopes eligible nondeleted stock to the exact report project and locks active locations and stock in stable order. PostgreSQL regressions in `test_daily_reports.py` cover central/unassigned and foreign-project stock, inactive/deleted locations and deleted stock, reserved stock, and competing reports for one stock row. | None for local behavior; no historical stock repair was performed. |
| INV-02 | COMPLETED | The inventory service resolves exact normalized code before exact normalized name, rejects ambiguous matches, inactive/deleted/nonconsumable items and mismatched units, and validates positive finite Decimal quantities before movement. `test_daily_reports.py::test_report_approval_uses_exact_code_before_a_matching_name`, `test_report_approval_rejects_ambiguous_name_and_unit_mismatch`, and `test_report_approval_rejects_ineligible_item` cover these paths. | None for local behavior. |
| INV-03 | COMPLETED | `ReportService._consume_report_materials` requires exact consumed-line count, including zero. The service validates all lines before posting; PostgreSQL regressions cover all-lines rollback, repeated-line aggregation, single-location/no-reserved sufficiency, empty reports, authorized stock-receipt retry, concurrent reports, and failed-approval state/audit/notification rollback. `ApprovalInboxPage` displays allowlisted line-specific messages via `formatApiError`; its browser path is covered in `daily-report.e2e.ts`. | None for local behavior; browser verification is limited to rendering the actual error contract with a deterministic mocked 409, paired with real API regression coverage. |
| HR-01 | COMPLETED | `decide_leave_request` uses the shared managed legacy-credit reconciliation guard before balance/debit writes under the payroll and employee locks. `test_hr_leave_accrual.py::test_managed_leave_approval_requires_reconciliation_for_legacy_credit` verifies unreconciled-credit denial, reviewed negative adjustment, stale receipt rejection, concurrent accrual/approval, duplicate decision serialization, and exactly one taken ledger debit; existing generic-policy tests preserve unmanaged behavior. | No production entitlement or employee balance was read or changed. |
| SEC-01 | COMPLETED | `dashboard_service.py` intersects project scope with document service visibility and classification before SQL counting; `test_dashboard_pending_document_count_uses_document_scope_and_classification` passed for scoped supervisor and financial director projections. | Production visibility remains unverified. |
| NOT-01 | COMPLETED | `notification_service.py`, `task_outbox.py`, `tasks/outbox.py`, and `tasks/email.py` persist dispatch state with notifications, lease and retry delivery, and retain ambiguous outcomes for review. Transaction rollback, broker retry, provider result, duplicate delivery and expired-claim tests in `test_notifications.py` passed. | Live provider receipt and worker/beat health remain unverified; no exactly-once external-mail claim. |
| NOT-02 | COMPLETED | `api/v1/notifications.py`, `notification_repository.py`, `NotificationsPage.tsx`, and `notifications.ts` implement bounded stable pagination and previous/next navigation; `test_notification_pagination_unread_parity_and_bulk_read_are_complete` and frontend notification tests passed. | None for local behavior. |
| NOT-03 | COMPLETED | `NotificationRepository.mark_all_read` performs one user-scoped update across unread nondeleted rows, including muted/superseded rows, preserving existing read timestamps; notification regression passed. | None for local behavior. |
| NOT-04 | COMPLETED | Dashboard unread badge uses `NotificationRepository.unread_count` with the same muted/superseded/deleted predicates; notification parity regression passed. | None for local behavior. |
| NOT-05 | COMPLETED | `frontend/src/pages/notifications/workflowLinks.ts` allowlists the two verified internal destinations and rejects external, protocol-relative and prefix-lookalike links; `NotificationsPage.test.ts` passed. | None for local behavior. |
| HR-07 | COMPLETED | `hr.py` and `hr_workforce_service.py` advertise only eligible revision-bound route actions and exclude subject/submitter; `test_hr.py` authorization cases and the browser restoration path passed. | Live account assignments remain unverified. |
| HR-04 | COMPLETED | `HRWorkspacePage.tsx` renders the advertised reasoned restoration action, retains input on failure and refreshes state after success; the fallback-restoration Chrome workflow passed. | None for local behavior. |
| HR-05 | COMPLETED | Scoped HR projections expose the actual final actor and localized decision time; backend actor-projection test and direct-supervisor Chrome workflow passed. | Live account names and decisions were not accessed. |
| HR-06 | COMPLETED | `hr.py` exposes a paginated HR-only data-quality projection and `HRWorkspacePage.tsx` links to the existing employee editor without revealing source dates or adding bulk mutations; backend authorization test and data-quality Chrome workflow passed. | Live data counts and corrections require authorized HR review. |
| LIFE-04 | BLOCKED_AUTHORIZATION | Existing manual reviewed employment-change apply path and manager reroute are retained; no scheduled identity was fabricated. | Approved system execution identity, scheduling authority and audit source are absent. |
| HR-02 | BLOCKED_POLICY | Existing annual-block verification and zero-carry rollover protections remain in place; no exception receipt or waiver was created. | An approved source policy permitting closure exceptions and named independent decision authority are missing. |
| HR-03 | BLOCKED_POLICY | Additional leave types remain inactive until configured through existing reviewed policy paths. | Approved sick, maternity and unpaid eligibility, entitlement/pay treatment, evidence, limits, half-day and expiry rules are missing. |
| PAY-01 | BLOCKED_POLICY | Existing reviewed payroll policy, Decimal accounting and write restrictions remain unchanged. | Approved jurisdiction, currency, period, pay components, ordering/rounding and worked examples are missing. |
| PAY-02 | BLOCKED_POLICY | Existing frozen time/leave input and export guards remain unchanged. | Approved reconciliation rules for payroll periods, overtime and unpaid leave are missing. |
| PAY-03 | BLOCKED_POLICY | Closed payroll runs and original settlements remain immutable; no finance execution path was added. | Approved positive/negative/zero correction treatment, named independent Finance authority and external evidence rules are missing. |
| PAY-04 | BLOCKED_POLICY | Existing employee payslip publication/read path remains intact; no replacement statement was issued. | Approved correction statement publication and settlement/recovery policy are missing. |
| PAY-05 | BLOCKED_POLICY | Locked attendance and payroll source records remain protected; no direct correction was made. | Approved discrepancy-to-correction authority and calculation policy are missing. |
| LIFE-01 | BLOCKED_POLICY | Historical attendance recorder and assigned-engineer checks remain unchanged. | Approved scoped substitute delegation, work-date evidence and eligible reviewer assignment are missing. |
| LIFE-02 | BLOCKED_POLICY | Existing encrypted opener-scoped HR case access and deny-by-default permission state remain unchanged. | Approved case investigator, independent decision/appeal assignments and evidence scope are missing. |
| LIFE-03 | BLOCKED_POLICY | Existing recruitment transitions remain unchanged; no maker identity or approval was fabricated. | Management decision on requisition and offer maker/checker independence is missing. |
| IMG-01 | PARTIAL | Local `rg` found no image task producers; synchronous photo upload/thumbnail behavior remains. Celery registration and support task-name mappings remain because queued-work migration was not authorized. | Production queued-task drain state is unavailable, so compatibility task stubs were retained. |

The policy-blocked items above do not block independent local fixes. The
local candidate has no hosted CI, deployment or independent production
readback; those states are recorded separately from local verification below.

### 26-finding verification record · prior local checkpoint

- Final pre-commit checkout was `main` at `37dab2ad14d981b71ac048884df3cc47337aab9f`;
  a read-only fetch confirmed `origin/main` still matched. The candidate remains
  local and unpushed. Its implementation-scope SHA-256 is
  `d515a8114fbe599e28ac71c265cb052e8ffc057df4c66c21f85f698ea4edd79f` over 46
  changed/new files, excluding this completion ledger to avoid a self-referential
  hash. No staged changes were present before final review.
- A fresh disposable PostgreSQL database upgraded from empty to Alembic head
  `202605310116`. A populated forward-upgrade rehearsal from `202605310115` to
  `202605310116` preserved a synthetic outbox row and its pre-existing fields;
  the new due index exists. No production database was used.
- Backend `ruff check .`, `mypy .` (466 source files), and
  `scripts/export_openapi.py --check` passed. The full backend suite passed
  **1,479 tests**, with **6 skipped** (five explicit Docker-opt-in stack tests
  and one local Docker-ingress test) and **18 warnings** (Celery queue and
  HTTPX cookie deprecations). The six failures from the first run were traced to
  legacy test fixtures/assertions that omitted required synthetic stock, assumed
  an empty shared test database, or expected pre-outbox synchronous mail. Those
  cases were corrected and all six passed in a focused rerun before the clean
  full-suite rerun.
- Frontend lint and generated API type check passed; Vitest reported **15 files
  and 72 tests passed**; the production build passed with the existing large
  bundle warning. The full Chrome suite on the same application runtime passed
  **89 tests with 1 skipped** before two additional E2E specifications were
  added. The current direct-supervisor final-decision, reasoned fallback
  restoration, and HR data-quality workflows then passed in a focused run (**3
  passed**); the full Chrome suite was not rerun after those test-only additions.
- `git diff --check` and `graphify update .` passed. No hosted CI, push, merge,
  deploy, production readback, live notification delivery, policy activation,
  production data disposition or business UAT is claimed.

### Current local verification · 2026-11-27

- Source verification began on branch `main`, base commit `7175a69133fbed3d8eda1728b979ef2493d5c52d`, against audit/origin reference `37dab2ad14d981b71ac048884df3cc47337aab9f`; a read-only fetch confirmed `origin/main` remained there. The 23 relevant modified tracked files were reviewed and tested, then committed locally as `69abcd2f907044df12204ebfa9a477170f71c2bb`. The working tree is clean; local `main` is two commits ahead of `origin/main`. The audit commit was not pushed.
- Fresh disposable PostgreSQL database `garrison_backend_full_resume_20261127` was upgraded to `202605310116`; full `pytest -q -rs` passed: **1,522 passed, 6 skipped, 18 warnings** in 521.76 seconds. Skips: five Docker-opt-in forward-stack tests and one explicit Docker-ingress test. An earlier full run on a reused database had eight failures; its first reported failure was caused by persisted overlapping calendar state. That run is not counted as passing; the clean-database run passed, including the calendar case.
- Focused report approval regressions passed on PostgreSQL, including all-line rollback, retry after authorized stock receipt, empty reports, ineligible/deleted stock and locations, and competing reports. The managed-leave reconciliation/concurrency regression passed separately. The full backend run also includes these tests.
- Frontend checks passed: ESLint, generated API types check, Vitest (**15 files / 75 tests**) and production build. Playwright collected 92 tests and completed **91 passed, 1 skipped**; the skipped support-custody case requires `SUPPORT_CUSTODY_MODE=single_owner`. The daily-report UI line-error/retry flow and HR route-restoration/data-quality browser paths ran. The report test uses a deterministic mocked 409 to exercise safe UI messaging; real stock denial/rollback/retry are covered by PostgreSQL API tests.
- Backend Ruff passed; Mypy passed with no issues in 466 source files; `scripts/export_openapi.py --check`, `git diff --check` and Alembic single-head check passed. Current head remains `202605310116`. No schema change was made in this follow-up; the existing populated `202605310115`→`202605310116` rehearsal is recorded above.
- The earlier full run against a reused test database reported eight failures, including a persisted overlapping-calendar fixture. That run is retained as history and not counted as a passing check; the full fresh-database run above is the controlling result.
- The tested non-ledger patch SHA-256 was `fdde47239970417674ee3f34705b8276b47aaf6515c8450f19e36f7f80b321c2` across 22 modified tracked files, calculated against base `7175a69133fbed3d8eda1728b979ef2493d5c52d` with `git diff --binary <base> -- . ':!docs/HR_COMPLETION_LEDGER.md' | shasum -a 256`. The ledger is excluded to avoid a self-referential digest. The local commit contains that tested source/test patch; changes after full checks were documentation-only.
- No production database or employee data, live mail recipient, hosted CI, deployment, or independent production readback was used. No push, merge, policy activation, role grant, destructive operation, or history rewrite was performed. Production status, approved policy inputs, live dispositions and UAT remain separately blocked or unverified as listed in the 26 findings.
