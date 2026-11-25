# Roles and permissions

Business sign-in accepts the ten role keys below. Their current portal and HR grants are defined in [the frontend role fixture](../frontend/src/pages/roles/rolePermissions.json)
and [the backend permission definitions](../backend/app/utils/permissions.py). The
independent [business matrix test fixture](../backend/tests/business_role_matrix.json)
records the 160 historical source decisions. The current catalogue grants HR workflow permissions to HR Manager. A role grant is only one authorization boundary:
services also check record ownership, project membership, state, and current account
status.

## Supported roles

| Role key | Display name |
| --- | --- |
| `managing_director` | Managing Director |
| `operations_director` | Operations Director |
| `group_project_manager` | Group Project Manager |
| `mep_project_manager` | MEP Project Manager |
| `quantity_surveyor` | Quantity Surveyor |
| `senior_site_supervisor` | Senior Site Supervisor |
| `site_supervisor` | Site Supervisor |
| `hr_manager` | HR Manager |
| `hr_executive_reader` | HR Executive |
| `administrative_executive` | Administrative Executive |

The original eight keys (`admin`, `general_manager`, `operation_manager`,
`project_manager`, `civil_engineer`, `civil_supervisor`, `store_keeper`,
`accounts`) and the later `hr_executive` key are retired. They are not aliases, valid login roles,
assignment options, import targets, seed defaults, or worker privileges. Historical
records and explicit rejection/migration tests may still contain those strings.

The synthetic legacy test route reserves `super_admin` with `platform:access`
and `platform:overview:read`. Business assignments, HR account links, workbook
imports and role cutover use the business catalogue above. The technical portal
defaults to disabled. Its separate operator registry uses an enrolled passkey
followed by a single-use email code and grantable technical capabilities
(`operator.manage`, nine bounded case/custody/view/log grants, and twelve
read-only oversight/monitor grants in [support oversight models](../backend/app/models/support_oversight.py)).
None of those technical capabilities grant any business role or financial or HR
write authority. Browser sessions use a host-only cookie and a separate
server-side session. The [activation procedure](OPERATIONS_AND_DEPLOYMENT.md#super-admin-activation)
describes operator enrollment, ingress, oversight bounds, and production verification.

## Super Admin People & Access

Single-owner activation includes the existing `company.directory.read` grant.
Revision `202605310100` adds it to an already activated, active single owner
with `operator.manage` when missing, records the grant in the audit log, and
revokes that operator's older technical sessions. Sign in again to open
People & Access. Paired operators still receive this grant through the
existing custody workflow. Account changes, session actions, and project
assignments require their own capabilities.

## View as User

People & Access offers **View as User** for active accounts to operators with
`company.directory.read` and `simulation.start`. The reviewed preview requires
an open or investigating case assigned to the operator and bound to the
account. Creating a case from the profile also requires `cases.manage`.
Paired custody requires an independent eligible reviewer. Single-owner
custody uses the enrolled owner's passkey in the proposing session.
The preview uses the subject's current business role and the intersection of
the subject's project access and the reviewed case scope. See [the support
preview workflow](LOGGING_AND_REMOTE_CLI.md#view-as-user).

## Feedback access

All authenticated business roles can submit feedback from the portal header.
Inbox reads and status changes require a technical session with
`operator.manage` behind the dedicated support ingress. Status changes also
require the support session's CSRF token and current report revision.
See [feedback and triage](LOGGING_AND_REMOTE_CLI.md#user-feedback-and-triage).

## Project creation boundary

Managing Directors and Operations Directors may create projects with zero or more initial BOQ items and add priced BOQ items later from editable project details. Each later item is validated and audited while the project row is locked; existing items are preserved. Existing director-only CSV/XLSX project and priced BOQ imports remain unchanged. Financial values continue to require `financial:view`.

MEP Project Managers may create Planning projects with milestones and without a budget or initial BOQ items. The server rejects any initial status other than planning. This creation-only capability does not grant downstream financial visibility, budget or BOQ update authority, approvals, or assignment rights; their existing checks and redaction remain unchanged. Creation does not grant membership or company-wide visibility. A director must assign project access through the existing membership workflow before the creator can read or manage the project. Group Project Managers remain unable to create projects or add priced BOQ items. No account role or database schema changes are required.

Rollback: revert the BOQ route/service and matching frontend/API contract changes together using the supported release process. Keep persisted project and BOQ records intact.

## Evidence classification and confidentiality

Document and photo uploads are initially `unclassified` unless an invoice or
contract document type is already classified as financial. The uploader may
access their own pending material, while a separate actor with `documents:manage`
can classify it with a reason; the decision is audited. A reviewer cannot use
this permission to bypass the owning record's existing project or entity scope.
Operational evidence becomes visible under those same existing scope rules.
Financial evidence requires `financial:view` for metadata, file links, originals,
and previews. Search and list queries apply the same classification boundary.
No role grants were changed for this workflow. Historical evidence left
unclassified by the migration requires manual review. D04's business confirmation
about company and private document scope remains pending.

## Permission matrix

| Permission | MD | OD | Group PM | MEP PM | QS | Senior Site Supervisor | Site Supervisor | HR Manager | Administrative Executive | HR Executive |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `users:manage` | ✓ | ✓ | | | | | | | | |
| `users:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `projects:manage` | ✓ | ✓ | ✓ | ✓ | | | | | | |
| `projects:read` | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | | | |
| `audit:view` | ✓ | ✓ | | | | | | | | |
| `dashboard:company` | ✓ | ✓ | | | | | | ✓ | ✓ | |
| `dashboard:scoped` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `reports:view` | ✓ | ✓ | ✓ | ✓ | | | | | | |
| `reports:submit` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | |
| `reports:approve` | ✓ | ✓ | ✓ | ✓ | | | | | | |
| `inventory:view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | |
| `inventory:manage` | ✓ | ✓ | | | | | | | | |
| `suppliers:manage` | ✓ | ✓ | | ✓ | ✓ | | | | ✓ | |
| `documents:view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ |
| `documents:manage` | ✓ | ✓ | | | | | | | | |
| `financial:view` | ✓ | ✓ | ✓ | | | | | | | |

MD = Managing Director; OD = Operations Director; Group PM = Group Project Manager; MEP PM = MEP Project Manager; QS =
Quantity Surveyor. The grant sets are explicit: a permission does not imply another
permission, and a role receives no future permission by default.

## HR permissions

HR Manager has permissions for standard employee records,
recruitment, onboarding, attendance recording, leave processing, ordinary HR
documents and compliance, service requests, and HR summaries. Only HR Manager
receives sensitive employee, attendance approval, leave approval, HR policy and
offboarding grants. Directory reads and private documents are separate from
account administration. An HR Manager can authorize a linked direct manager to
recommend specific time and leave requests when the company policy is enabled.
The authorization applies to that reporting relationship and does not grant
HR directory, document or final-decision permissions. See [HR and workforce](HR_WORKFORCE.md).

HR Executive currently receives `users:read`, `dashboard:scoped`, and
`documents:view`. The source matrix's `reports:view` selection is withheld under
D11 pending owner sign-off; do not restore report access without that decision.
The [HR task assessment](HR_WORKFORCE.md#hr-executive-scope-and-proposed-hr-tasks)
records the source decision and proposed workflows separately.

The backend defines 16 standard and 21 HR permission keys. No current role is
granted `hr:cases:restricted`, `hr:payroll:approve`, `hr:payroll:prepare`,
or `hr:payroll:sensitive`.
HR Manager has `hr:training:manage` for training and `hr:performance:manage` for setting up and calibrating reviews. Linked employees and explicitly authorized current direct managers act only on their own or assigned reviews.
The associated permission-gated workflows cannot be operated by assigning a
current portal role. [Permission definitions and grants](../backend/app/utils/permissions.py)

## Authorization rules

- Only Managing Director and Operations Director have company-wide resource scope.
  Other project-scoped reads and writes require current project membership where the
  owning service enforces it. An empty membership set does not mean unrestricted.
- The API and service remain authoritative. Hiding a menu or button is not an
  authorization check. Current role, active state, access revision, ownership,
  membership, and workflow state are rechecked on protected actions.
- User management uses target-role ceilings. Directors may manage the nine supported
  roles directly. HR access requests require HR review and director fulfillment. Self-elevation,
  self-role change, self-deactivation, and self-password reset are blocked. Changes
  to access revoke refresh sessions and pending OTP challenges.
- Imports require `users:manage` and the permission for that import domain.
  Project and priced BOQ imports require director scope. Queued imports revalidate
  the submitting account before writes.
- Managing Director and Operations Director have company-wide financial read
  access. Group Project Manager can read budgets, priced BOQ, material-request
  costs, invoices and financial summaries for assigned projects. Company-wide
  catalogue costing and finance reconciliation are director-only. Budget edits
  and priced BOQ changes require a director. Invoice and payment writes remain
  unavailable under the current role policy.
- HR Manager retains existing HR permissions, including attendance review.
  Site-report reading and approval are outside the HR Manager grant.
- Managing Director and Operations Director retain general inventory management.
  Both supervisor roles can create and correct their own material requests and
  register inventory on assigned projects. They can save and resume private drafts
  and select eligible assets from the registration chain. The assigned MEP Project Manager
  verifies a submitted material request, and the assigned Group Project Manager
  then reviews it. When a configured threshold applies, the designated director
  reviews the later stage. Overdue visibility does not confer decision authority.
  Directors and assigned Administrative Executives can
  process approved requests within their scope. Directors retain cancellation
  authority. Assigned Quantity Surveyors can read submitted registrations.
  General catalogue and stock permissions remain separate.
  [Inventory routes](../backend/app/api/v1/inventory.py) · [Inventory service](../backend/app/services/inventory_service.py)
- Company dashboard access does not imply company-wide project, report, document,
  audit, or financial access. Those paths enforce their own permission and scope.
- Submission and viewing are separate report permissions. A submitter without
  `reports:view` may recover only their own allowed work; do not widen the role
  matrix to make a page load.
- Official daily report authoring is available to the two directors, the Group
  and MEP Project Managers, and Quantity Surveyor. The two supervisor roles
  author supervisor updates. Assigned-project scope applies outside the two
  director roles. Daily-report decisions are available to eligible directors,
  Group and MEP Project Managers. The service rejects a
  self-approval and requires project membership for non-director decisions.
  [Role eligibility](../backend/app/utils/permissions.py) · [Report service](../backend/app/services/report_service.py) · [Supervisor service](../backend/app/services/reporting_service.py)
- Assigned Quantity Surveyors review applicable area and quantity evidence and
  assigned MEP Project Managers confirm technical progress. The assigned engineer
  reviews staged inventory and site attendance. An independent HR Manager verifies
  attendance after the engineer. Site attendance access does not grant access to
  other employees’ personnel records or change payroll policy.
- Approval visibility and action eligibility differ. Normal self-approval and
  former global override powers are denied. Each owning workflow service applies its
  own transition and scope checks.

## Verification

Run the source-transcribed role contract and user/auth regressions from
`backend/`:

```sh
pytest -q tests/test_permissions.py tests/test_users.py tests/test_auth.py
pytest -q tests/test_authorization_matrix.py tests/test_scope_authorization.py
```

These database-backed suites require the project's disposable PostgreSQL, Redis and
object-store services. Skipped or unexecuted cases are not release evidence.

The one-time role-data cutover and its external approval requirements are documented
in [Role catalogue cutover](ROLE_CATALOGUE_CUTOVER.md). Production account mapping
and activation are not performed by ordinary role-assignment APIs.
