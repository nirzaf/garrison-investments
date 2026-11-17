# Garrisons administration CLI

`garrisonctl` uses the portal's FastAPI endpoints for account, project, finance, workforce and import operations. The authenticated account's permissions and project scope apply. The same API audit records identify the actor. Host commands use the existing deployment, recovery and monitoring tools.

## Install and connect

Use Python 3.14 on macOS or Linux and the backend dependencies. Run commands from `backend/`.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.garrisonctl --version
python -m scripts.garrisonctl --help
python -m scripts.garrisonctl capabilities --json
```

Set `GARRISON_API_BASE_URL` to the intended HTTPS origin. The local default is `http://127.0.0.1:8000`. `--base-url` overrides it. Plain HTTP is limited to loopback. `GARRISON_ENVIRONMENT` or `--environment` labels the response and has no effect on permissions or the destination.

```bash
python -m scripts.garrisonctl auth login --email director@example.com
python -m scripts.garrisonctl auth whoami --json
python -m scripts.garrisonctl roles permissions --json
python -m scripts.garrisonctl auth logout --json
```

Login prompts privately for the password and delivered OTP. An origin-bound, owner-only session file under `~/.config/garrisonctl/` stores the access token and rotating refresh token. Use `--session-file` to select another file in a private directory. An expired access token is refreshed before a command sends its request. If the refresh session has expired, use `auth logout --local-only` to remove the unusable file, then sign in again. The local-only option leaves server revocation to the session's expiry or the normal account revocation process.

For automation, provide an already issued short-lived bearer through `GARRISON_ACCESS_TOKEN` or `--token-file`. The token file must be a regular, owner-only file. A short-lived bearer alone has no refresh or server logout capability. Use secure terminal prompts for account creation and password resets. Keep sessions, tokens, user import files and reconciliation inputs out of Git and shared logs.

## Commands

| Group | Commands | Required access |
| --- | --- | --- |
| Identity | `auth login`, `auth whoami`, `auth logout`, `roles list`, `roles permissions` | Own session. Role directory and another role's permissions require `users:read` |
| Users | `users list`, `show`, `create`, `update`, `set-role`, `activate`, `deactivate`, `reset-password` | `users:read` or `users:manage` as shown by capabilities |
| Projects | `projects list`, `show`, `members list`, `members assign`, `members revoke` | Scoped `projects:read` or `projects:manage` |
| Policy | `config show`, `config validate`, `config plan`, `config apply`, `config verify`, `finance policy show`, `finance policy validate`, `finance policy reconciliation` | Local validation, authenticated API, director finance access, or root host operator |
| Finance | `finance invoices list`, `show`, `finance budget show`, `finance reconcile` | Dataset-specific permissions, including `financial:view` and project scope |
| Imports | `imports templates`, `preview`, `run`, `batches`, `status` | `users:manage` |
| Diagnostics | `health check`, `logs search`, `logs tail`, `audit search` | Public readiness or `audit:view` |
| Operations | `backup status`, `backup verify`, `release status` | Host-only, with existing file, policy and credential access |

Each command has `--help` and `--json`. Capabilities lists commands, argument requirements, permissions, execution scope, preview support and whether approval is required. Project membership labels are project context. Company permissions come from the user's account role.

### Workforce administration

Use the existing portal session with the HR permissions assigned to your account.
`hr employees list`, `hr employees get`, `hr leave requests list`,
`hr compliance expiring`, and `hr reports summary` use the same restricted API as
the HR workspace. Mutations use the command's `--dry-run` and
`--apply --expect` options. Treat workbook previews and document links as
restricted records. See the [workforce guide](HR_WORKFORCE.md) for the account
handoff and activation flow.

The current remote workforce command groups are listed below. For exact
arguments and preview support, run `garrisonctl capabilities --json` or the
subcommand's `--help`.

| Prefix | Registered subcommands | Access boundary |
| --- | --- | --- |
| `hr employees` | `list`, `get`, `create`, `update`, `transition`, `link-account` | HR read, manage or sensitive permissions for employee actions. Linking uses `users:manage`. |
| `hr departments`, `hr positions` | `list`, `create` | Employee read or manage permission. |
| `hr access-requests` | `list`, `create`, `decide` | Request stage and actor determine HR versus director access. |
| `hr attendance` | `list`, `import`, `correction` | Attendance recording permission. |
| `hr calendars` | `list`, `show`, `create`, `update`, `decide` | Attendance recording permission. Review and publication also require HR policy management permission. |
| `hr roster` | `list`, `show`, `allocate`, `cancel` | Attendance recording permission. Uses the published work schedule and preserves cancellation history. |
| `hr documents` | `list`, `status`, `upload`, `upload-version`, `decide`, `download` | Manage HR vault files, including independently reviewed candidate CVs and offer PDFs. |
| `hr company-policy` | `list`, `publish` | Publish an edition and pin the current approved company policy file when applicable. |
| `hr my-policy` | `list`, `show`, `download`, `acknowledge` | Read and acknowledge editions visible to the linked employee. |
| `hr leave` | `policy show`, `policy propose`, `policy decide`, `requests list`, `requests submit`, `requests decide`, `balances` | Leave management, leave approval or policy management, depending on the command. |
| `hr requests` | `list`, `show`, `assignees`, `assign`, `resolve` | HR service request processing. Approval and rejection also require sensitive employee access. |
| `hr offers` | `list`, `status`, `draft`, `decide`, `reissue`, `convert` | Follow offer status and version history. Conversion requires an accepted offer and an open requisition with capacity. |
| `hr requisitions` | `list`, `status`, `create`, `decide` | Find requisitions, record requested headcount, and move a requisition through its approval and hiring states. |
| `hr candidates` | `list`, `status`, `create` | Find or register candidates and inspect their details in an owner-only file. |
| `hr applications` | `list`, `status`, `create`, `stage`, `activity`, `shortlist`, `withdraw` | Link a candidate to an open requisition, track the stage, and record screening and evaluation decisions. |
| `hr onboarding` | `list`, `status`, `create`, `task`, `probation` | Track checklists, start direct-hire onboarding and record probation outcomes. |
| `hr interviews` | `list`, `schedule`, `update` | List an application's interviews, schedule a round, and record feedback and outcomes. |
| `hr correspondence` | `templates`, `list`, `status`, `draft`, `decide` | Prepare and independently review rejection correspondence. |
| `hr compliance` | `expiring` | Compliance management. |
| `hr offboarding` | `list`, `initiate`, `custody list`, `custody record`, `settlement list/propose/review`, `complete` | Offboarding management and case preconditions. |
| `hr` | `workbook-reconcile`, `summary`, `reports summary`, `reports sites` | Employee management for workbook reconciliation. Report viewing for summaries and sites. |

Use `hr reports sites` to page through primary site IDs and
`hr reports summary --project-id ID --department-id ID --date-from YYYY-MM-DD --date-to YYYY-MM-DD`
to filter the report. Both dates are required when applying a date range.

Use `hr requests list --status in_review --limit 20 --offset 0` to page through
the HR service queue. `hr requests show --request-id ID` shows status and
assignment. Add `--output PRIVATE.json` to save the full request, including
private text, to a new owner-only file.

For a handoff, obtain the user ID from `hr requests assignees` and put
`assigned_to_id` and `reason` in a private JSON file. For a decision, supply
`status` and any applicable `resolution_notes` or `generated_letter_id`.
Run `hr requests assign --request-id ID --file PRIVATE.json --dry-run`
or substitute `resolve` for a decision. Repeat with `--apply --expect HASH`
to submit the actor-bound plan. Run a fresh dry run if the request changes.
The API enforces the assignee, workflow state, and letter eligibility.

Use `hr documents list --candidate-id ID --document-type candidate_cv` to
find a candidate's vault record. The first upload uses
`hr documents upload --candidate-id ID --category confidential --document-type candidate_cv --title TITLE --file FILE --dry-run`.
Use `candidate_offer` for an offer PDF. Later uploads use
`hr documents upload-version --document-id ID --file FILE --dry-run`.
Apply the corresponding preview with the same arguments and
`--apply --expect PLAN_SHA256`. If an upload response is lost, check
`hr documents status --document-id ID` and compare the recorded version hash
before attempting a replacement.

A different HR Manager can use
`hr documents download --document-id ID --version N --output NEW_FILE`
to review the exact candidate file in a new mode-0600 file. If object storage
uses a different public origin from the API, specify its trusted origin with
`--object-origin https://HOST`. The CLI verifies size and checksum before
writing and omits the signed link from output.
Use `hr documents decide --document-id ID --version N --sha256 DIGEST --decision approve --dry-run`
with the downloaded checksum. For `reject`, add
`--reason-file PRIVATE_FILE.txt`. Apply the reviewed plan with
`--apply --expect PLAN_SHA256`.

Use `hr requisitions list --code CODE` to find an exact code, or
`--req-status STATUS --limit 20 --offset OFFSET` to page through a stage.
Create a draft with `hr requisitions create --file PRIVATE.json --dry-run`.
Supply `requisition_code`, `title` and any optional hiring fields, including
`headcount_requested`, `target_join_date`, `justification` and
`budget_notes`. Apply the reviewed file with `--apply --expect PLAN_SHA256`.
If a response is lost, look up the original code before retrying.

Use `hr requisitions decide --requisition-id ID --file PRIVATE.json --dry-run`
with a `status` and, for rejection, the reason in `notes`. Submitting a draft
requires recruitment access. Every other transition also requires
`hr:employees:sensitive`. Repeat with
`--apply --expect PLAN_SHA256`. Review a fresh preview after a change to the
requisition. Budget notes, justification and rejection reasons stay out of
console output. To review them, use
`hr requisitions status --requisition-id ID --output NEW_FILE.json`.

Use `hr offers status --offer-id ID --json` to check the offer state. Add
`--output NEW_FILE.json` to review terms and notes in a new owner-only file. Run
`hr offers list --application-id ID --limit 20` to find versions for an
application. Draft with `hr offers draft --file PRIVATE.json --dry-run`.
The owner-only terms file includes `application_id`, `offer_code` and
`proposed_title`. It can also include a validity date, join date, department,
position, currency and notes. Use a new code for
`hr offers reissue --offer-id ID --file PRIVATE.json --dry-run` and omit the
application ID from the replacement file. Reissue preserves the original offer
and verifies the links in both directions. Recruitment offers do not accept
salary values.
Include `document_version_id` to attach the candidate's approved offer PDF
from the HR vault. Reissuing an offer with a PDF requires a different
approved version. The offer status reports the pinned version identifier.

Use `hr offers decide --offer-id ID --file PRIVATE.json --dry-run` with the
requested `status` and optional `notes` and `valid_until`. The deadline may
be changed before or at issuance. Approval requires the existing
`hr:employees:sensitive` permission. Apply any offer preview with the same
file and `--apply --expect PLAN_SHA256`. If the result is uncertain, check
the offer code and current version before retrying. Offer notes are omitted
from terminal output.

Run
`hr offers convert --offer-id ID --employee-code CODE --dry-run --json`
and repeat with `--apply --expect PLAN_SHA256` after reviewing the plan.
Supply `--probation-days` in both calls when needed. The command verifies the
converted employee through the offer and reports the onboarding case ID.
If the result is uncertain, check the offer status before taking further action.

Use `hr onboarding list --employee-id ID` and
`hr onboarding status --case-id ID` to find a case and its task IDs. Add
`--output NEW_FILE.json` to save private evidence for review. For direct hires,
`hr onboarding create --file PRIVATE.json --dry-run` takes `employee_id`,
`start_date`, and optional `probation_end_date` and `owner_user_id`.

`hr onboarding task --case-id ID --task-id ID --file PRIVATE.json --dry-run`
takes `status` and optional `evidence_notes`. Completion and waiver require
evidence. Waiver and case closure require sensitive HR access. The portal
checks that the employee does not approve their own checklist.

After the checklist is complete and the employee has moved to
`on_probation`, use
`hr onboarding probation --case-id ID --file PRIVATE.json --dry-run`.
Supply `outcome` and `reason`, plus `new_end_date` for an extension or
`confirmed_category` when confirming a probation-category employee.
Apply each reviewed plan with the same file and `--apply --expect PLAN_SHA256`.
Re-run the preview after an intervening task or employee change.

Use `hr candidates list --code CODE` for an exact candidate lookup. Register
a candidate with `hr candidates create --file PRIVATE.json --dry-run` and
include `candidate_code`, `full_name` and any optional contact or experience
fields. Use `hr applications create --file PRIVATE.json --dry-run` with
`candidate_id`, `requisition_id` and optional `screening_notes`. Apply each
preview with the same file and `--apply --expect PLAN_SHA256`. After an
uncertain write, check the original candidate code or use
`hr applications list --candidate-id ID --requisition-id ID`.

Use `hr applications status --application-id ID` to check the application.
For private details, add `--output NEW_FILE.json` to application or candidate
status. Record screening, interview, evaluation, offer or rejection with
`hr applications stage --application-id ID --file PRIVATE.json --dry-run`.
Use the requested `stage` and optional `screening_notes` or `overall_score`.
Rejection requires `rejection_reason`. Evaluation requires a completed
interview. Re-run the preview if the record changes before applying.
To shortlist an application in screening, use
`hr applications shortlist --application-id ID --dry-run`, then apply with
`--apply --expect PLAN_SHA256`. Use
`hr applications activity --application-id ID --limit 20` to read recorded
stages and actors.
Then use `hr applications withdraw --application-id ID --decision-file FILE --dry-run`.
The owner-only JSON file contains `expected_stage`, `reason`, and
`retention_decision`. A decision of `retain_until_review` also requires
`retention_review_on` in YYYY-MM-DD format and `retention_policy_reference`.
Use `policy_review_required` if these values are pending. Apply the same
file with `--apply --expect PLAN_SHA256`. The preview and receipt omit the
withdrawal reason.

Use `hr interviews list --application-id ID` to check an application's rounds.
For `hr interviews schedule --file PRIVATE.json --dry-run`, the owner-only JSON
contains `application_id`, a new `interview_id` UUID and `scheduled_at`
including a UTC offset. Optional fields are `round_number`, `interview_type`,
`interviewer_user_id` and `interviewer_name`. Repeat with the same file and
`--apply --expect PLAN_SHA256`. Keep the same interview UUID for an identical
retry. If the result is uncertain, list the interviews and check that UUID.
With an active `interviewer_user_id`, scheduling sends a generic portal
invitation. A name alone is for the HR record and sends no notification.

For `hr interviews update --application-id ID --interview-id ID --file PRIVATE.json --dry-run`,
include the fields that should change from `status`, `recommendation`, `score`
and `feedback_notes`. Apply the reviewed plan in the same way. Review a fresh
preview after a concurrent edit. The CLI omits interviewer names, scores and
feedback text from console output.

Use `hr correspondence templates` to find an active rejection template
and `hr correspondence list --application-id ID` to check existing drafts.
Prepare correspondence for a rejected application with
`hr correspondence draft --application-id ID --draft-id NEW_UUID --template-id ID --dry-run`.
Repeat with the same UUID and arguments and `--apply --expect PLAN_SHA256`.
If the write result is uncertain, read the draft using the same UUID.

An independent reviewer can open the exact record with
`hr correspondence status --application-id ID --draft-id ID --output NEW_FILE.json`.
The file contains protected content and is created with mode 0600. The command
refuses to overwrite an existing file. Review the contents in private and use
its digest with
`hr correspondence decide --application-id ID --draft-id ID --decision approved --content-sha256 DIGEST --dry-run`.
For `rejected`, also supply `--reason-file PRIVATE_FILE.txt` with the review
reason in UTF-8. Apply the reviewed plan with `--apply --expect PLAN_SHA256`.
The CLI reports the persisted decision without printing the letter or reason.
Approval records the decision in HR and does not send an email.

`hr leave requests submit` previews the selected employee's leave units from
the published schedule and rechecks the quote on apply. Omit `--days` to use
the calculated amount or supply it to assert the expected total. For permitted
single-day half-day leave, pass `--half-day-period morning` or
`--half-day-period afternoon`. If the quote changes, review a fresh dry run.

To reverse approved leave, preview
`hr leave requests decide --leave-request-id ID --decision cancelled --notes "Decision reference" --dry-run`.
Use a reference or short reason suitable for the employee to see. Apply with
`--apply --expect PLAN_SHA256`. The server verifies the original debit and
blocks changes to a closed leave year or approved payroll. The CLI reads
the selected request's decision state before and after applying. Its
preview and receipt omit the leave reason, attachments and decision notes.
`hr leave requests list --status submitted --limit 25 --offset 0` lists
the first page of the review queue and reports the total matching count.

Use `hr leave policy propose --file POLICY.json --dry-run` to preview a
dated proposal. The JSON uses the leave policy creation contract, including
`effective_from` and `effective_to`. A second HR Manager uses
`hr leave policy decide --policy-id ID --decision approved --dry-run`
or chooses `rejected` and provides `--reason`. Apply either command with
its own `--apply --expect PLAN_SHA256`. Use `hr leave policy show` to
inspect the effective windows and current decisions.

`hr leave accrual post --employee-id ID --leave-type-id ID --year YYYY --dry-run`
previews a closed annual period. Add `--month N` for an approved monthly
policy. Add `--through-month N` to preview an inclusive range of closed
months in that year. Review each policy and ledger reference, then apply with
`--apply --expect PLAN_SHA256`. Catch-up credits only missing periods, and an
ineligible period prevents the range from posting. Use the same dry run to
read back stored ledger references after posting or an uncertain result.

HR time administrators can use the command groups `hr attendance`,
`hr attendance corrections`, `hr timesheets`, and `hr overtime`.
Each group has `list` and `show --record-id ID`. Use a private terminal
when reading records with employee notes. Lists can filter by
`--employee-id ID`.

Use `create --file FILE --dry-run` with the corresponding request fields
in an owner-only JSON file. Manual attendance uses `employee_id`,
`work_date`, `attendance_status` and `worked_hours`. A correction uses
`employee_id`, `work_date`, `requested_status`,
`requested_worked_hours`, `reason` and the existing
`attendance_entry_id` when applicable. A timesheet uses `employee_id`,
`period_start`, `period_end`, `regular_hours`, optional
`overtime_hours` and `submit`. An overtime request uses `employee_id`,
`work_date`, `requested_hours` and `reason`.

Review with `decide --record-id ID --file FILE --dry-run`. The JSON
supplies `decision` plus any note or approved hours required by the
existing workflow. The CLI reads the current revision itself where the
API supports it. Confirm either write with `--apply --expect PLAN_SHA256`.
Previews bind the signed-in actor and request hash. Review plans also bind
the read record. Write receipts omit private notes and include the saved
status read back from the server.

For CSV imports, use `hr attendance import --file INPUT --dry-run
--output REVIEW` with an owner-only CSV. Use the portal's attendance CSV
template. The optional review path must be new. It records row errors and
the reviewed clock timestamps. Invalid rows block the batch and produce
no apply plan. Use the same CSV with `hr attendance import --file INPUT
--apply --expect PLAN_SHA256`. The CLI rechecks the signed-in actor,
the exact CSV bytes and the server preview. Its receipt contains row
numbers and the IDs of the submitted entries, which you can inspect
with `hr attendance show --record-id ID`. Clock times and employee
codes stay out of the import command's terminal output.

Use `hr calendars list` or `hr calendars show --calendar-id ID` to
read the schedule, effective dates, status and revision. To prepare a
calendar, use `hr calendars create --file FILE --dry-run`. To replace the
fields of a draft, use `hr calendars update --calendar-id ID --file FILE
--dry-run`. Use an owner-only JSON file with `code`, `name`,
`work_days_json`, `standard_start_time`, `standard_end_time`,
`daily_hours`, `effective_from`, `effective_to`, `timezone`, and optional
`project_id` and `is_default`. The CLI reads the current revision for updates.

Use `hr calendars decide --calendar-id ID --action ACTION --dry-run`
with `submit`, `approve`, `publish` or `return_to_draft`. Approval
requires a different HR Manager from the creator and submitter.
Returning to draft requires `--reason`. Confirm each write
with `--apply --expect PLAN_SHA256`, using the same account and input
as the preview. The CLI reads back the saved status and revision.

Use `hr roster list --date-from YYYY-MM-DD --date-to YYYY-MM-DD` for up
to 31 days, with optional employee and project filters. Use
`hr roster show --allocation-id ID` to read the exact record. List and
show include employee names and any cancellation reason.

Use `hr roster allocate --allocation-id ID --employee-id ID --project-id ID
--work-date YYYY-MM-DD --dry-run`. Generate and keep a UUID for each
intended allocation. Reuse that UUID if the same active allocation has to
be retried. The preview binds the requested employee, project and date.
The server resolves the published calendar or shift when it applies the
allocation, and the receipt includes the saved hours and shift.

Use `hr roster cancel --allocation-id ID --file FILE --dry-run` with an
owner-only JSON file containing `reason`. Confirm both commands with
`--apply --expect PLAN_SHA256`. The CLI checks the saved record after each
write. Write receipts omit names and the cancellation reason.

Use `hr company-policy publish --file FILE --dry-run` with the edition fields
in an owner-only JSON file. A file-backed edition includes `document_id`
and `document_version_number` for the approved company policy file.
A replacement includes `supersedes_policy_id` and a later effective
date. The preview binds the edition input and the file checksum.
Confirm with `--apply --expect PLAN_SHA256`.

Linked employees use `hr my-policy list` and `hr my-policy show
--policy-id ID` to inspect available editions. Use `hr my-policy
download --policy-id ID --output NEW_FILE` for the pinned file. Specify
`--object-origin` if the signed file is served from the authorized
object-storage origin. The CLI verifies size and checksum before
creating a new owner-only file.

After reviewing the edition, run `hr my-policy acknowledge --policy-id ID
--edition LABEL --file-version N --dry-run` and confirm with
`--apply --expect PLAN_SHA256`. Omit `--file-version` for a text edition.
A receipt applies only to the named edition and pinned version.

Use `hr leave date-evidence candidates` to find approved cross-month
leave missing dates. Filter with `--employee-id ID` when reconciling a
known employee. Results flag requests that need payroll correction
because an approved run already covers them.

Use `hr leave date-evidence list --request-id ID` to inspect the
approved leave and its proposals, or `show --request-id ID --proposal-id
ID` for the exact review digest. Propose with `hr leave date-evidence
propose --request-id ID --file FILE --dry-run`. The owner-only JSON
contains `proposal_id` (a new UUID), `work_dates` (an array of ISO dates)
and an opaque `evidence_reference`. A separate reviewer runs `hr leave
date-evidence decide --request-id ID --proposal-id ID --decision approved
--digest DIGEST --dry-run` or sends `--decision rejected`. Confirm either
write with `--apply --expect PLAN_SHA256`. The CLI verifies that an
approval retained the exact submitted dates on the request.

Payroll commands require the corresponding prepare, approve and sensitive
permissions. The current portal role catalogue has no payroll grant. With
separately authorized test permissions, use
`hr payroll calculate --run-id ID --roster-file FILE --dry-run` for a draft,
with a JSON array of employee UUIDs. Use
`--time-sha256 TIME_SHA256 --leave-sha256 LEAVE_SHA256` together to retain
the source files and totals reviewed for that roster and period. The
server rechecks the supplied digests before freezing the snapshot. Use
`hr payroll snapshot --run-id ID` to inspect the frozen inputs and amounts,
then `hr payroll approve --run-id ID --dry-run` as an independent reviewer.
Each write requires its own `--apply --expect PLAN_SHA256`. On approval,
the server rechecks roster eligibility and the approved compensation
terms, and compares any attached source digests with the current sources.
If the terms or evidence have changed, review fresh inputs and prepare a
new run for the open period. The earlier snapshot stays available for
review. Review payroll output in an authorized private terminal.

Use `hr payroll time-inputs --period-id ID --roster-file FILE` to preview
locked time inputs. Supply a JSON array of employee UUIDs in an owner-only
file. Review the roster, the date window and any blocking issues. When the
preview supplies a digest, rerun the same command with
`--sha256 CSV_SHA256 --output FILE`. The CLI verifies the CSV digest and
creates a new owner-only file. The export contains time quantities and opaque
record IDs. Approved overtime must reconcile to the timesheet. Payroll rates,
salary, and payment instructions stay in their own workflows.

Use `hr payroll leave-inputs --period-id ID --roster-file FILE` to preview
paid and unpaid approved leave against the same roster. The command checks
approval debits and cancellation reversals. For approved requests spanning
periods, each CSV includes only the units for approved work dates in that
period. Pending requests, ledger discrepancies and legacy approvals spanning
periods without retained work dates block download. Resolve the reported
issues before reviewing the digest again.
Use `--sha256 CSV_SHA256 --output FILE` to save the reviewed export. The
download contains record IDs, dates and leave units. Private reasons, names
and attachments stay in the leave workflow.

Use `hr compensation list --employee-id ID` for effective dates, current
status and approvals. `hr compensation show --employee-id ID --term-id ID`
shows the same metadata for one term. Add `--output FILE` to save an exact
review copy as a new owner-only file. That read is audited by the HR API.
CLI output omits salary, allowances and rejection reasons.

To propose terms, save owner-only JSON containing `employee_id`,
`effective_from`, `base_salary` as decimal text, `currency`, and
`pay_frequency`. Include `allowances_json` only when required. Run
`hr compensation propose --file FILE --dry-run`, then apply the same
input with `--apply --expect PLAN_SHA256`. The proposal stays pending.
A different eligible reviewer saves and inspects the exact term, then
previews `hr compensation decide --review-file SNAPSHOT --file DECISION --dry-run`.
The private decision JSON takes `"decision": "approve"` or
`"decision": "reject"` with a reason. Apply the matching review plan.
The CLI rejects stale or different terms and reads back the recorded
outcome. The HR API still enforces independent review and the locked
payroll boundary.

Use `hr benefits types list` to inspect the catalogue without printing
reimbursement ceilings. `hr benefits types show --benefit-type-id ID
--output FILE` saves the exact policy as a new owner-only review file.
Propose a type with `hr benefits types propose --file FILE --dry-run`.
Use decimal text for a reimbursement ceiling and supply its currency.
An independent reviewer previews `hr benefits types approve --review-file
FILE --dry-run` and applies the matching plan.

Assign coverage with `hr benefits assignments create --file FILE --dry-run`.
Provide the employee ID, benefit type ID and effective dates in owner-only
JSON. Assignments for capped policies require approval and an end date.
Apply the reviewed plan with `--apply --expect PLAN_SHA256`. The CLI
checks the resulting assignment and refuses overlapping coverage.
`hr benefits assignments list --employee-id ID` omits coverage notes.

Use `hr cases list` to see cases you opened and `hr cases show --case-id
ID --output FILE` to save the audited detail in a new owner-only file.
Terminal output omits the case title, case code, employee ID, narrative
and resolution. These commands require the separate restricted case
permission. No production role currently carries it.

Use `hr cases open --file FILE --dry-run` with owner-only JSON containing
`case_code`, `case_type`, `title`, `details` and optional
`employee_id` and `severity`. Use `hr cases update --review-file REVIEW
--file UPDATE --dry-run` with a private update file containing
`status` (`investigating`, `action_taken` or `closed`) and optional
`resolution_notes`. Omit the notes to preserve the existing text.
Apply either command with `--apply --expect PLAN_SHA256`. If someone
changes the case while you review it, save a fresh copy and review again.

Use `hr reimbursement list --employee-id ID` to locate claims and
`hr reimbursement show --claim-id ID --output FILE` to save a new
owner-only review copy. The terminal omits amounts, descriptions,
decision notes and external settlement references. To inspect the
pinned receipt, match its version ID to the document record and use
`hr documents download --document-id ID --version NUMBER --output FILE`
with the required document permission.

Submit with `hr reimbursement submit --file FILE --dry-run`. The
owner-only JSON supplies `employee_id`, `benefit_assignment_id`,
`claim_type` (the approved benefit type code), `claim_date`,
decimal-text `amount`, `description`,
`receipt_document_id`, `receipt_version_number`, a UUID
`idempotency_key` and the currency if different from the API default
of LKR. Use the same file and key when retrying the same submission.
An independent reviewer uses `hr reimbursement decide --review-file
REVIEW --file DECISION --dry-run`. The decision file supplies
`decision` (`approved`, `rejected` or `cancelled`) and `notes`
as required. Apply either command with `--apply --expect PLAN_SHA256`.

Use `hr reimbursement payable --claim-id ID --output FILE` to save the
reviewed unpaid obligation as owner-only JSON. The file contains the claim
reference, an opaque employee ID and the approved amount and currency.
Omit `--output` to check the reference and settlement status in the
terminal. Treat the claim reference as the same obligation on every read.

After external settlement, put `expected_payable_sha256` from the reviewed
file, `settlement_reference`, `settled_amount` as a decimal string and
`settled_currency` in a separate owner-only JSON file. An authorized
operator who did not approve the claim can run
`hr reimbursement confirm-paid --claim-id ID --settlement-file FILE --dry-run`,
then apply with `--apply --expect PLAN_SHA256`. The command verifies the
confirmed status and keeps the amount and external reference out of its
terminal output.

Use `hr advance list --employee-id ID` to locate an advance and
`hr advance show --advance-id ID --output FILE` to save the exact record
to a new owner-only JSON file. The terminal receipt shows identifiers,
status, payable digest and repayment count. Use the private file to
review principal and external references.

Run the appropriate command with `--dry-run` before applying it with
`--apply --expect PLAN_SHA256`.

| Command | Arguments and private JSON |
| --- | --- |
| `hr advance submit` | `--file FILE` with `employee_id`, `benefit_assignment_id`, `requested_on`, `amount`, `currency` and an `idempotency_key` UUID. Reuse the key for an unchanged submission. |
| `hr advance decide` | `--advance-id ID --decision approved\|rejected\|cancelled`. The reviewer must be independent. |
| `hr advance confirm-disbursement` | `--advance-id ID --file FILE` with the external `reference`, `occurred_on`, exact `amount`, `currency` and `expected_payable_sha256` from the approved record. |
| `hr advance record-repayment` | `--advance-id ID --file FILE` with the external `reference`, `occurred_on`, `amount` and `currency`. |

Use ISO dates and decimal strings for amounts. If a confirmation loses its
response, use `show` to verify whether the external reference was recorded.

Use `hr payroll policies list` to locate a policy. A payroll preparer can
run `hr payroll policies propose --file FILE --dry-run` with an owner-only
JSON file containing `code`, `name`, `rules_json`, and `controlled_record`.
The controlled record includes the restricted document reference, version,
effective date, approval reference, and worked examples. Use
`hr payroll policies update --policy-id ID --file FILE --dry-run` to correct
the same pending proposal. The update file supplies the revised name, rules,
and controlled record. Confirm either write with `--apply --expect PLAN_SHA256`.

An independent payroll approver uses
`hr payroll policies show --policy-id ID --output NEW.json` to save the
review copy in a new owner-only file. After reviewing that copy, pass the
receipt's digest to `hr payroll policies approve --policy-id ID
--review-sha256 REVIEW_SHA256 --dry-run`, then confirm with
`--apply --expect PLAN_SHA256`. If the proposal changes, save and review a
fresh copy. The terminal receipts omit policy rules, document references, and
worked-example amounts. Keep the input and review files outside Git.

The reviewer who approved a locked run can inspect
`hr payroll publish-payslips --run-id ID --dry-run` and publish with
`--apply --expect PLAN_SHA256`. The preview and receipt contain no employee
amounts. Linked employees use `hr payslip list` and
`hr payslip show --run-id ID` for statements published to their own account.
The scheduled pay date is separate from settlement confirmation.

The run approver can use
`hr payroll payment-export register --run-id ID --dry-run` to reconcile
the protected Finance handoff and register it with
`--apply --expect PLAN_SHA256`. Save the exact registered bytes with
`hr payroll payment-export download --run-id ID --sha256 CSV_SHA256 --output FILE`.
Download verifies the receipt digest and creates a new owner-only file.
The CSV contains no names, email addresses or bank details. The employee
mapping is available only in the protected payroll snapshot.

Use `hr payroll settlement summary --run-id ID` for outstanding amounts and
`hr payroll settlement events --run-id ID` for the protected event history.
To acknowledge an external result, run
`hr payroll settlement record --run-id ID --event-file FILE --dry-run`.
The owner-only JSON file contains `event_id`, `payment_reference`, `kind`
(`paid`, `failed` or `reversed`), `amount` as a decimal string, `occurred_on`
as a date, and an opaque `evidence_reference`. A reversal also requires
`reverses_event_id`. Confirm with `--apply --expect PLAN_SHA256`. Use the same
event UUID and evidence reference on retry. Never put account details into
the evidence reference.

After publishing payslips and reconciling every payment, run
`hr payroll close --run-id ID --dry-run`. A separate authorized reviewer
confirms with `--apply --expect PLAN_SHA256`. The plan binds the reviewed
snapshot, CSV and settlement checksums, and apply reads back the closure
receipt. Zero-net payroll uses the checksum of the empty payment export.

For a closed payroll run, `hr payroll correction list --run-id ID
--line-id LINE_ID` shows the current baseline and history. Use the line's
`payment_reference` from the restricted snapshot as `LINE_ID`, including
for a zero-net line. Inspect an exact proposal with `hr payroll correction
show --run-id ID --line-id LINE_ID --correction-id ID` in a private
terminal.

To propose revised amounts, run `hr payroll correction propose --run-id
ID --line-id LINE_ID --file FILE --dry-run`. The owner-only JSON file
contains a fresh `correction_id` UUID, decimal strings for `gross` and
`deductions`, and an opaque `evidence_reference`. The preview binds the
closed snapshot, current baseline, and proposal hash. A separate reviewer
can use `hr payroll correction decide --run-id ID --line-id LINE_ID
--correction-id ID --decision approved --digest DIGEST --dry-run`.
A rejection uses `--decision rejected`. Confirm either write with
`--apply --expect PLAN_SHA256`. Both commands read back the resulting
receipt. Review approval records the correction for follow-up with Finance.

HR Managers and inventory owners can inspect a case's custody history with
`hr offboarding custody list --case-id ID`. Inventory owners first post any
stock return using the inventory workflow, with reference type
`hr_offboarding_cases` and the HR case ID as the reference ID. Then run
`hr offboarding custody record --case-id ID --event-id UUID --kind returned
--movement-id ID --evidence-reference REF --dry-run`. The custody command
records a reference to the existing stock movement. Use a fresh event UUID for
each new event and reuse it when retrying the same event. For `cleared`,
`waived`, or `flagged`, omit the movement ID and supply an opaque evidence
reference for the attestation or exception. Confirm each write with
`--apply --expect PLAN_SHA256`. After an interrupted response, check the
exact receipt with `custody list --case-id ID --event-id UUID` before retrying.

For IT handover, directors use `hr offboarding custody list --area it_admin
--case-id ID`. The record command uses the same preview and apply workflow.
Pass `--area it_admin --device-reference ID` to flag or record a return,
or to waive an already flagged device with an approved evidence reference.
For the final `--kind cleared` sign-off, omit the device reference and supply
the overall handover reference. IT sign-off requires zero unresolved devices
and verified portal deactivation for a linked user. Both HR and directors
can inspect IT receipts with the case ID.

List accessible reviews with `hr performance list`. Read one review with
`hr performance show --review-id ID`. The same participant checks and
publication stage apply as in the portal.

Use `hr performance act --review-id ID --event-id UUID --file action.json
--dry-run` to preview an available review action. Store `action` and any
`notes`, `rating`, or `replacement_reviewer_id` in the owner-only JSON file.
The command gets the current revision from the API. Confirm with
`--apply --expect PLAN_SHA256` using the same file and event UUID. The
receipt confirms the recorded event without displaying the narrative or
rating. Retrying the same confirmation returns that receipt when the actor
can still read the event.

List the course catalogue with `hr training courses list` and an employee's
assignments with `hr training enrollments list --employee-id ID`. Use
`hr training courses create --file course.json --dry-run` with `code` and
`title`, or `hr training enrollments create --file enrollment.json --dry-run`
with `employee_id`, `course_id`, and an optional `scheduled_date`.
Apply with `--apply --expect PLAN_SHA256` as the same HR operator. The command
reads back the created record. The server rejects duplicate course codes,
duplicate open enrollments, and assignments outside current employment.

Use `hr training enrollments update --employee-id ID --enrollment-id ID
--status in_progress --dry-run` to preview a status change. The other
available choices are `no_show` and `cancelled`. Apply with
`--apply --expect PLAN_SHA256`. If the status changed since preview, get
a fresh plan. Record completion with approved certificate evidence.

To verify training against already approved ordinary employee evidence,
use `hr training completion verify --enrollment-id ID --document-id ID
--version-number NUMBER --completed-date YYYY-MM-DD --dry-run`. Add
`--score` when applicable, then confirm with `--apply --expect PLAN_SHA256`.
Check the receipt using `hr training completion show --enrollment-id ID`.
A renewal uses its own enrollment and approved evidence. Inspect configured
scopes with `hr training requirements list` and an employee’s current
requirements with `hr training requirements employee --employee-id ID`.

For separation settlement, use `hr offboarding settlement list --case-id ID`.
A director with Finance access runs
`hr offboarding settlement propose --case-id ID --event-id UUID --outcome
OUTCOME --evidence-reference REF --dry-run`. Use `outstanding`, `settled` or
`nothing_due`. A different director uses `hr offboarding settlement review
--case-id ID --event-id UUID --decision approved --evidence-reference REF
--dry-run`, or records a rejection with its own reference. Both writes require
`--apply --expect PLAN_SHA256`. Check the exact receipt with
`settlement list --case-id ID --event-id UUID` after an interrupted response.
Use opaque references to the approved Finance evidence. Keep financial details
in their approved system of record.

Use `hr employees changes due --limit 20 --offset 0` for approved changes due
as of the server's business date. The list identifies the employee and
indicates whether their current record still matches the reviewed revision.
Use `hr employees changes list --employee-id ID` to inspect reviewed employment
changes. For `changes propose --employee-id ID --file FILE --dry-run`, the
JSON object contains `change_type`, `effective_date`, `reason` and `updates`.
For example, a `transfer` can set `updates.work_location`; specify the employee
revision through the CLI's live preview. A different HR Manager uses
`changes decide --employee-id ID --change-id ID --decision approved --dry-run`.
For a rejection, supply an operational `--reason`. Run
`changes apply --employee-id ID --change-id ID --dry-run` for a due approved
proposal. Each write requires its own `--apply --expect PLAN_SHA256`.

For rehire, use `change_type: rehire` with the new start as `effective_date`.
Set `updates.separation_case_id` to the latest completed eligible separation
and supply `updates.employment_category`. Include `updates.probation_days` for
probationary rehire. Use the existing independently reviewed `changes decide`
and `changes apply` commands. Check old and new periods via
`hr employees periods --employee-id ID`; the new period identifies its
onboarding case and reviewed change. Portal access continues through a fresh
director-fulfilled request.

Run `hr employees periods-missing-start --limit 20 --offset 0` as an
authorized HR Manager to identify closed employment periods whose start date
is missing. The report includes employee and separation references and the
recorded end date. It leaves the original records available for reconciliation
against approved source evidence.

For a `contract_renewal` proposal, `updates` contains
`current_contract_document_id`, `current_contract_version`,
`renewal_contract_document_id`, `renewal_contract_version`, and
`contract_end_date` (`YYYY-MM-DD`). Both referenced versions must be
available to the reviewing HR Managers, and the end date must match the
renewal's vault expiry. Review the exact evidence before approving.

Use `hr request list --status open --limit 25 --offset 0` to page through
open requests. Add `--employee-id ID` to narrow the queue.
Use `hr request assignees` to list eligible HR users. Run
`hr request assign --request-id ID --assignee-id ID --reason "Shift handoff" --dry-run`
before assigning or reassigning an active request. Confirm the preview using
`--apply --expect PLAN_SHA256`. Assignment preserves the request's status and
SLA clock. Use an operational reason without personal or confidential details.

Use `hr request status --request-id ID` to inspect status and assignee.
The current assignee can preview `hr request start --request-id ID --dry-run`
and confirm with `--apply --expect PLAN_SHA256`. An unassigned request
becomes assigned to the operator who starts review.

Use `hr request complete --request-id ID --letter-id ID --dry-run`
to preview completion with an already-issued letter for that employee.
The letter argument is optional. Pass `--response-file FILE` with a JSON
string to share response text. After review, apply with
`--apply --expect PLAN_SHA256`. The preview and receipt omit private letter
and response text.

Use `hr letter list` and `hr letter show --letter-id ID` for your own issued
letters. HR Managers can add `--employee-id ID` to inspect a selected employee's
draft and issued history.

`hr letter draft --employee-id ID --template-id ID --letter-id NEW_UUID --file FILE --dry-run`
renders the letter for review. Use a private JSON file containing an
`extra_vars` mapping, or `{}` if the template needs no inputs. Keep the same
letter UUID for the matching apply and a retry. A different HR Manager uses
`hr letter decide --employee-id ID --letter-id ID --decision issued --dry-run`
to review and issue. For `rejected`, pass `--reason-file FILE` containing a
JSON string. Apply each command with its own `--apply --expect PLAN_SHA256`.
Use a private terminal because previews and reads display letter text.

`hr leave rollover post --employee-id ID --leave-type-id ID --year YYYY --dry-run`
previews the closing balance, carry and expiry for one employee and leave
type. Review the source ledger and reconcile any missing accrual before
applying with `--apply --expect PLAN_SHA256`. Posting closes that source
year. A subsequent dry run shows the existing receipt.

### Inspect identities, roles and projects

```bash
python -m scripts.garrisonctl auth whoami --json
python -m scripts.garrisonctl roles list --json
python -m scripts.garrisonctl roles permissions --role quantity_surveyor --json
python -m scripts.garrisonctl users list --active --role quantity_surveyor \
  --limit 50 --offset 0 --json
python -m scripts.garrisonctl users show --email qs@example.com --json
python -m scripts.garrisonctl projects list --status active --search warehouse --json
python -m scripts.garrisonctl projects show --project-id "$PROJECT_ID" --json
python -m scripts.garrisonctl projects members list --project-id "$PROJECT_ID" --json
```

Use the IDs returned by these reads as `USER_ID` and `PROJECT_ID` in the examples below. Review a member's company role with `users show --user-id "$USER_ID"` if you have user directory access. Compare the role permissions with project memberships to check assignment scope. List commands use `--limit` and `--offset` where supported.

### Account and project changes

```bash
python -m scripts.garrisonctl users create --email qs@example.com \
  --full-name "Quantity Surveyor" --employee-code QS-001 --phone 5550100 \
  --role quantity_surveyor --designation "Quantity Surveyor" --dry-run --json
python -m scripts.garrisonctl users update --user-id "$USER_ID" \
  --phone 5550110 --dry-run --json
python -m scripts.garrisonctl users update --user-id "$USER_ID" \
  --clear-designation --dry-run --json
python -m scripts.garrisonctl users activate --user-id "$USER_ID" --dry-run --json
python -m scripts.garrisonctl users deactivate --user-id "$USER_ID" --dry-run --json
python -m scripts.garrisonctl users reset-password --user-id "$USER_ID" --dry-run --json
python -m scripts.garrisonctl users set-role --email qs@example.com \
  --role quantity_surveyor --dry-run --json
python -m scripts.garrisonctl users set-role --email qs@example.com \
  --role quantity_surveyor --apply --expect "$PLAN_SHA256" --json
python -m scripts.garrisonctl projects members assign --project-id "$PROJECT_ID" \
  --user-id "$USER_ID" --role-in-project "Quantity Surveyor" --dry-run --json
python -m scripts.garrisonctl projects members revoke --project-id "$PROJECT_ID" \
  --user-id "$USER_ID" --dry-run --json
```

Set `PLAN_SHA256` to the returned hash after reviewing the target, actor, current state and intended change. Repeat the same command with `--apply --expect "$PLAN_SHA256"` only after authorization. User mutations use the current update timestamp and project mutations use the current project revision. The API serializes access changes, preserves at least one usable director account, and revokes the target's sessions and pending authentication challenges on access changes or password reset. Account resets preserve the existing password workflow. Project revocation preserves membership history.

Apply uses the same target, identity and arguments as the preview. A stale plan returns exit 4. Read the updated user or membership afterward and keep the write request ID for the audit record. Create and password-reset apply commands prompt for the temporary password at that point.

For a staff roster, look up each verified email and compare the returned
role and account status with the approved assignment. For a new account,
use the approved employee code and phone and a unique temporary password.
Resolve missing or conflicting role and identity values before applying
that row. Role changes on existing accounts use `users set-role` and do
not require a password reset.

`users create` writes the account and reads back its role. Credential
delivery is a separate operation. Send each new account's credentials
individually through the authorized channel after role readback. Record
the account result and the delivery result separately in the restricted
handoff record. Keep temporary passwords out of audit notes and reports.
Distinguish provider acceptance from confirmed receipt. If mail fails or
its outcome is uncertain, check the existing account and the delivery
record before retrying. Coordinate any credential rotation through
`users reset-password` for that same account.

### Inspect or propose finance policy

```json
{
  "business_currency": "USD",
  "business_timezone": "Asia/Qatar",
  "material_approval_threshold": "1000.00"
}
```

```bash
python -m scripts.garrisonctl config show --json
python -m scripts.garrisonctl finance policy show --json
python -m scripts.garrisonctl config validate --file proposed-business-config.json --json
python -m scripts.garrisonctl finance policy validate --file proposed-business-config.json --json
python -m scripts.garrisonctl config plan --file proposed-business-config.json --json
python -m scripts.garrisonctl finance policy reconciliation --json
```

The three values come from the application's environment settings. These are the existing defaults. Supported codes are `USD`, `LKR`, and `QAR`. Deployed environments currently require `USD`. Obtain owner approval and reconcile unlabeled money rows and historical approval labels before enabling another operating currency. The director finance access view reports counts and stored currency labels. It never converts or rewrites historical amounts.

The material estimate is routed with a strict greater-than comparison, so exactly `1000.00` follows the existing lower route. The threshold must fit two decimal places and `Numeric(14,2)`. The business timezone uses IANA identifiers. Production Compose supplies the same timezone to backend processes and the frontend build. Database instants and technical events retain UTC. Invoice total is amount plus the entered nonnegative tax amount, subject to the existing two-decimal limit. Confirm the operating currency, threshold, reporting timezone, and accounting conventions with the owner before changing them.

**Host-only configuration preparation.** The root operator runs both commands from a reviewed checkout on the host with access to its protected deployment state.

```bash
python -m scripts.garrisonctl config plan --file proposed-business-config.json \
  --host-state /opt/garrison-portal/deploy --json
python -m scripts.garrisonctl config apply --file proposed-business-config.json \
  --host-state /opt/garrison-portal/deploy --expect "$PLAN_SHA256" \
  --approval-reference "$APPROVAL_REFERENCE" --apply --json
```

The command holds the deployment lock, rechecks the current environment bytes, and prepares an owner-only `production.env` candidate plus an audit receipt. The approval reference records the operator's approval evidence. Review the candidate on the host and activate it using the existing release procedure. Keep the prior approved environment for rollback and use the runbook to restore it if needed. Currency transitions are blocked pending a reviewed reconciliation and migration. [Production procedure](OPERATIONS_AND_DEPLOYMENT.md#production-deployments-from-github-actions).

After activation, verify the policy against the intended API origin:

```bash
python -m scripts.garrisonctl config verify --file proposed-business-config.json --json
```

### Imports and reconciliation

```bash
python -m scripts.garrisonctl imports templates --type opening_stock --json
python -m scripts.garrisonctl imports preview --type opening_stock --file stock.csv --json
python -m scripts.garrisonctl imports run --type opening_stock --file stock.csv \
  --operation-id "$IMPORT_UUID" --dry-run --json
python -m scripts.garrisonctl imports run --type opening_stock --file stock.csv \
  --operation-id "$IMPORT_UUID" --apply --expect "$PLAN_SHA256" --json
python -m scripts.garrisonctl imports batches --json
python -m scripts.garrisonctl imports status --batch-id "$BATCH_ID" --json
python -m scripts.garrisonctl finance invoices list --project-id "$PROJECT_ID" \
  --status approved --limit 50 --offset 0 --json
python -m scripts.garrisonctl finance invoices show --invoice-id "$INVOICE_ID" --json
python -m scripts.garrisonctl finance budget show --project-id "$PROJECT_ID" --json
python -m scripts.garrisonctl finance reconcile --project-id "$PROJECT_ID" \
  --expected-file expected.json --json
```

Choose a UUID once for each intended import. Reuse the same UUID and unchanged file on retry. The API scopes the key to the actor and rejects changed file bytes, file names or templates under the same key. Save the preview and batch reference. Inspect batch status after an uncertain connection or partial result before retrying. User import files can contain temporary passwords and must be owner-only. [Import templates and required columns](import_templates/README.md).

The supported import templates are `users`, `projects`, `suppliers`, `materials`, `documents`, `boq`, and `opening_stock`. `imports templates` returns the CSV header. The preview reports invalid row numbers and fields without echoing file contents. Use the batch ID from apply for `imports status`. The invoice list and detail provide `INVOICE_ID`, totals and recorded payments for reconciliation.

Reconciliation accepts a JSON object with the datasets to compare. Replace IDs and values with approved controls. For example:

```json
{
  "members": {"7c764ad1-c6e1-4ad1-a286-84bdd525b7ed": {"role_in_project": "Site engineer"}},
  "budget": {"budget_amount": "1200.00", "remaining_budget": "1000.00"},
  "invoice_totals": {"amount": "180.00", "tax_amount": "20.00", "total_amount": "200.00"}
}
```

- `users` maps user IDs to `role` and/or `is_active`. It compares the authorized directory.
- `members`, `invoices` and `payments` map user, invoice and payment IDs respectively to expected fields. These use `--project-id`. Invoice fields include `amount`, `tax_amount`, `total_amount`, `paid_total`, `outstanding_amount`, `status` and `payment_status`. Payment fields include `amount`, `payment_date` and `method`.
- `budget` compares `budget_amount`, `invoiced_total`, `paid_total` and `remaining_budget` for the project. `invoice_totals` sums the specified invoice money fields over the authorized project invoice list.
- `batches` maps known import batch IDs to `row_count`, `error_count`, `status`, `template_type`, `created` and/or `skipped`. It checks only supplied batch IDs.
- `stock` maps location IDs to `on_hand_qty`, `reserved_qty` and/or `available_qty`. Set `--item-id`. For opening balance controls, compare in an environment where the expected opening balances still represent the stock at the chosen reconciliation point.

Use decimal strings for money and quantities. The command reports matched, missing, unexpected and field mismatches. Run multi-page comparisons against a stable dataset. The API does not supply a shared snapshot across these reads. Reconciliation makes no data corrections.

### Diagnose the portal

```bash
python -m scripts.garrisonctl health check --json
python -m scripts.garrisonctl logs search --severity ERROR --limit 20 --json
python -m scripts.garrisonctl logs tail --seconds 15 --max-events 10 --json
python -m scripts.garrisonctl audit search --action users.updated --json
```

Log reads use the existing audit-logged API. Tail returns a bounded batch of events. Output includes event metadata and omits comments and event payloads. The backup and release commands use protected host artifacts.

```bash
python -m scripts.garrisonctl backup status --monitor-profile "$PROFILE" \
  --profile-sha256 "$PROFILE_SHA256" --json
python -m scripts.garrisonctl backup verify --directory "$RECOVERY_SET" \
  --policy "$RECOVERY_POLICY" --require-authenticated --json
python -m scripts.garrisonctl release status --host-state /opt/garrison-portal/deploy --json
```

Backup status checks the independent backup receipts using the approved monitor profile. Verification checks artifacts without restoring them. Release status reads the current deployment receipt. Use readiness for live database connectivity and follow the incident and restore procedures for recovery. [Operations runbook](OPERATIONS_AND_DEPLOYMENT.md) · [Logging guide](LOGGING_AND_REMOTE_CLI.md).

### Tasks handled by existing tools

| Task | Terminal procedure |
| --- | --- |
| Review CI or deployment | Use `gh run list --branch main` and `gh run view "$RUN_ID"` in the GitHub checkout. Compare the intended commit and run result with `garrisonctl release status` and `health check`. [Production deployment and retry](OPERATIONS_AND_DEPLOYMENT.md#production-deployments-from-github-actions). |
| Inspect live services or bootstrap the first Managing Director | Use the production Compose helper on the authorized host. First-director bootstrap is for an empty installation. Routine account management uses `garrisonctl users`. [Host setup and maintenance](OPERATIONS_AND_DEPLOYMENT.md#host-bootstrap-and-runner-maintenance) · [Post-deploy verification](OPERATIONS_AND_DEPLOYMENT.md#post-deploy-verification). |
| Update mail, ingress, credentials or service settings | Follow the protected host configuration procedure. `garrisonctl config` manages only the three business policy settings. [Environment and configuration](OPERATIONS_AND_DEPLOYMENT.md#environment-and-configuration). |
| Capture, publish or restore backups | Use the recovery scripts with the approved destination, policy, keys and isolated restore target. Verify artifacts before attempting recovery. [Backup and restore](OPERATIONS_AND_DEPLOYMENT.md#backup-and-restore). |
| Diagnose historical data or prepare repairs | Use the named report and repair scripts for the specific defect. Reconcile using the relevant business owner's expected values. [Data checks and repairs](OPERATIONS_AND_DEPLOYMENT.md#data-checks-and-repairs). |
| Review or reverse an activation | Use the existing deployment workflow and verify schema, rollback generation, assets, and readiness from the host. [Rollback](OPERATIONS_AND_DEPLOYMENT.md#rollback). |

Reports, document uploads and approvals, and stock fulfillment remain portal workflows. The active role policy blocks invoice writes and payment entry. The CLI exposes authorized finance reads, project access and approved imports.

## Super Admin command parity

The technical portal uses its own operator identity and session. The business
`garrisonctl auth` session cannot authorize support commands. The inventory
below tracks the technical [support API](../backend/app/api/v1/support.py).
The listed commands are implemented locally. A browser handoff retains the
technical origin, passkey user presence and approval challenge.

| Portal operation | CLI command family | Status |
| --- | --- | --- |
| Initial two-custodian enrollment | `python -m scripts.bootstrap_support` | Implemented as host maintenance for an empty technical registry. The approved pair registers both passkeys in the browser. |
| Sign-in, session profile and sign-out | `support auth login`, `support auth whoami`, `support auth logout` | Sign-in uses a browser handoff with a passkey and a code sent to the registered technical mailbox. |
| Suspend an operator, review and execute | `support custody suspend propose`, `review`, `execute` | Implemented locally. The two decisions require browser passkey handoff. |
| Add or revoke a capability, review and execute | `support custody grant propose`, `review`, `execute` | Implemented locally. The two decisions require browser passkey handoff. |
| Enroll or recover a technical operator, review, execute and register passkeys | `support custody enrollment propose`, `review`, `execute`, `invitation`, `register` | Implemented locally. Decisions use Chrome handoff and native passkey registration runs on the physical device. Invitation files and registration receipts stay private. |
| List, open, inspect or transition a case | `support cases list`, `create`, `show`, `transition` | Implemented locally. Creation and transitions verify the case after the write. Transitions retain the server revision check. |
| Add or remove a case member, business subject or project; link evidence; verify resolution; close | `support cases action propose`, `apply` | Implemented locally. `apply` is the review and application step, backed by one action-bound browser passkey. |
| Look up the approved case account and recent authentication history | `support accounts search`, `support accounts show` | Search takes a case reference and an optional `--selector-file` containing `field` and `value`. Supported fields are `email` (verified), `employee_code`, `name` and `role`. Show matches the supplied account reference. Both write the masked case-scoped projection to a private file. |
| Propose, review or execute session revocation, unlock, disable, reactivation or recovery | `support accounts action propose`, `review`, `execute` | Implemented locally with browser passkey handoff and existing protected-account review and attestation. |
| Read recovery delivery and reset status | `support accounts recovery-status` | Implemented locally. Uses the existing status receipt. |
| Request and open a role permission, navigation, request summary, project list or project detail view | `support accounts action propose`, `review`, `execute` | Implemented locally for all five adapters. The requester must use the same technical session to execute and read the view. |
| Read or end an approved support view | `support views show`, `end` | Implemented locally. `show` selects one of the five fixed projection adapters. Views use the original technical session in either interface. |
| Read runtime request evidence, audit or the case timeline | `support cases logs`, `audit`, `timeline` | Implemented locally. Uses case-bound filters and existing disclosure audits. |
| Read service health | `support health show` | Implemented locally. Uses the technical health API and capability. |
| Follow approved request evidence | `support cases follow-logs` | Reads the same redacted stream as the portal. The bounded sample is written to a private file. |
| Independently reviewed evidence export | `support cases export propose`, `review`, `download` | Requires `logs.runtime` and `logs.export` in the assigned case. The reviewer and requester use fresh passkeys. The original requester session can save the approved CSV once. |
| Read fixed domain overviews (`company`, `projects`, `workforce`, `inventory`, `suppliers`, `documents`, `finance`, `approvals`) | `support overview show` (`--domain`, optional `--case` / `--project`, `--output`) | Implemented locally. Enforces per-domain oversight grant, small-cell suppression (threshold 5 with complementary total suppression) on workforce counts, case+project scope where required, and no monetary amounts or PII. |
| Explain a role permission against policy | `support policy explain` (`--role`, `--permission`, optional `--case`, `--output`) | Implemented locally. Requires `simulation.start` and evaluates canonical role permissions without inspecting user accounts. |
| Read background outbox, Celery execution summaries and Beat schedule | `support monitor jobs` (`--hours`, `--limit`, `--queue`, `--output`) | Implemented locally under `jobs.read`. Excludes task payloads, emails, tokens and stack traces. |
| Read attested backup and restore-drill receipts | `support monitor backups` (`--output`) | Implemented locally under `backups.read`. Reads append-only receipts without host paths or object-store keys. |
| Read non-secret runtime configuration posture | `support config show` (`--output`) | Implemented locally under `config.read`. Reports boolean posture, normalized origins, leaf certificate expiry window and build SHA without secrets. |
| Read incident failure and unknown-delivery summary | `support incidents show` (`--hours`, optional `--case`, `--output`) | Implemented locally under `incidents.read`. Summarizes failed jobs, unknown/failed recovery outcomes and denied support requests without PII or request bodies. |

The [production activation procedure](OPERATIONS_AND_DEPLOYMENT.md#super-admin-activation)
owns the host-only bootstrap. Routine CLI operations must go through the
technical API and its existing authorization and audit records.

To sign in from a private terminal, run `garrisonctl support auth login
--operator <operator-reference> --apply`. Enter the short pairing code on
the page opened at `https://superadmin.garrisons.lk` and approve with the
registered passkey in Chrome. Enter the six-digit code from your technical
mailbox and wait for confirmation. Return to the terminal and press Enter.
The browser approval issues no browser cookie and never receives
the CLI session tokens. The CLI reads back its operator identity before
saving an owner-only technical session file. An explicit `--session-file`
can select a different file. The technical origin is pinned and business
bearer tokens are excluded.

For a case list, use `garrisonctl support cases list --output
<new-file-in-private-directory>`. Pass `--cursor-from <previous-page-file>`
to fetch another page. Every command that reads a protected payload requires
a new owner-only output file. The terminal reports completion or a sanitized
error. `garrisonctl support auth logout --apply` revokes the technical
session and removes its local file. Both login and logout preview without
`--apply`.

To follow a linked request, run `garrisonctl support cases follow-logs
--case <case-id> --request <request-id> --output <private-file>`.
The command samples for up to 20 seconds or 25 events by default. Use a
new output file and pass `--cursor-from <previous-private-file>` to resume.

For an export, put the linked request ID, UTC `started_at` and `ended_at`
in a private JSON file under `filters`. Set `reason` to `incident_review`
or `audit_review`. The optional filter fields are `limit` and `status_code`.
Run `support cases export propose --case <case-id> --input <request.json>
--dry-run --output <plan.json>`. Apply with `--apply --plan <plan.json>
--expect <plan-sha256> --output <request-receipt.json>`. Repeat that
preview and apply sequence for `export review` as an independent assigned
operator, using the request receipt as input. The original technical CLI
session uses the approved receipt for `export download` and chooses a new
private CSV path. The CLI verifies the approved SHA-256 before it saves the
file. A lost download response requires a new export review.

Use the private JSON payload for the corresponding API request when creating
or transitioning a case or submitting a proposal. For example, with the
case-create fields `external_ref`, `severity` and `reason_code` in a private
file, run:

```sh
garrisonctl support cases create --input private/case.json --dry-run \
  --output private/case-plan.json
garrisonctl support cases create --input private/case.json --apply \
  --plan private/case-plan.json --expect "$APPROVED_PLAN_SHA256" \
  --output private/case-receipt.json
```

Plans bind the technical operator, requested payload, action intent and
applicable case revision. A changed case or operator requires a new plan.
Apply writes the verified receipt to a new private file. An account-action
retry with the same plan reuses the API idempotency key. Case and custody
proposal APIs lack a replay key, so the CLI records that the plan was
submitted before sending it. If the outcome is uncertain, check the case
and proposal state before submitting a new plan.

For an independent decision, use the private proposal receipt as `--input`
to the appropriate `review`, `execute` or case-action `apply` command. For
protected account review, an approved offline-contact UUID can be supplied
from `--contact-file` in a private file. Prepare and approve a matching
dry-run plan. The CLI prompts for the browser handoff and Chrome shows the
action and stage before asking for the passkey. The browser encrypts the
signed response to the terminal's temporary key. The original technical
session retrieves it once and submits it through the existing action API.
Each stage requires its own passkey proof and the same existing approval
rules. Invitations and other sensitive receipts are saved to the requested
private file.

After an approved enrollment or recovery execution, use `support custody
enrollment invitation --input <private-execution-receipt> --slot 1
--output <new-private-device-file>` to prepare one device file. Prepare slot
2 separately. For initial custody, use the private bootstrap bundle as the
input and add `--operator <custodian-reference>`. Give each intended device
only its own file using the approved private channel.

On the device, run `support custody enrollment register --input
<private-device-file> --output <new-private-receipt> --apply`. The command
opens the dedicated registration page in the default browser. In Chrome,
select the single-device file and confirm the passkey. The CLI reads the invitation
status back before writing a receipt. Its states are `registered` while
other required devices are still pending and `activated` once the operator
can sign in. A fresh readback requires an invitation that is still within
its original validity window. The registration link contains no invitation
value and the command never sends a business or technical session token.

The device-file workflow passed 170 backend and CLI tests and six isolated
Chrome scenarios. Chrome rejected a file for the wrong operator, then
registered the passkey from the correct file. The API denied expired and
superseded invitations and confirmed activation only after the required devices registered.

Revision `202605310088` passed 169 backend and CLI tests and six Chrome
scenarios. Chrome approved a case membership change with the encrypted
handoff and the existing case-action endpoint applied it. API tests denied
cross-session collection and admitted exactly one concurrent collection.
The CLI rejected a tampered encrypted response before sending a decision.

The isolated mutation regression ran the CLI through the real support API.
It created a case, advanced its revision through a transition, confirmed the
audit trail and denied an unrelated operator's read. The combined backend
and CLI suite passed 167 tests, including stale-plan and proposal replay
cases.

Revision `202605310087` passed 163 backend and CLI tests and six isolated
Chrome scenarios. The Chrome handoff approved the CLI login in the existing
tab and verified that only the CLI could read back the technical profile.
The API replay test accepted exactly one concurrent passkey submission.

## Output and agent use

JSON writes one envelope to stdout with `format_version`, `command`, `environment`, `outcome`, `changed`, `data`, `errors` and `request_id` where available. A preview has `changed: false`. A null change value indicates that the CLI cannot prove whether a mutation committed or was replayed. Read back the resource, batch or audit record before retrying. Check the exit code even when the envelope contains data.

| Exit | Meaning |
| --- | --- |
| 0 | Successful read, preview, verified operation, or unchanged result |
| 2 | Invalid command, configuration, input or API validation failure |
| 3 | Authentication or authorization failure |
| 4 | Missing record, stale plan or other conflict |
| 5 | Connection, readiness or server failure |
| 6 | Failed or partial operation, interrupted command, or failed verification |
| 7 | Reconciliation found differences |

Agents start with `capabilities --json`, confirm the target and caller with `auth whoami`, then inspect the needed records and prepare a dry run. Production writes require the user's explicit authorization. Keep the returned request ID for audit follow-up. If an access change needs reversing, plan a new authorized change against the current state. For binary rollback after changing access, retain the additive access revision migration and coordinate session invalidation because older binaries did not enforce the access revision claim.
