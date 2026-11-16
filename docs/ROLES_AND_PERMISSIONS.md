# Roles and permissions

The portal accepts exactly the nine role keys below. Their current portal and HR grants are defined in [the frontend role fixture](../frontend/src/pages/roles/rolePermissions.json)
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
| `administrative_executive` | Administrative Executive |

The original eight keys (`admin`, `general_manager`, `operation_manager`,
`project_manager`, `civil_engineer`, `civil_supervisor`, `store_keeper`,
`accounts`) and the later `hr_executive` key are retired. They are not aliases, valid login roles,
assignment options, import targets, seed defaults, or worker privileges. Historical
records and explicit rejection/migration tests may still contain those strings.
There is no technical administrator role or role-based bypass.

## Permission matrix

| Permission | MD | OD | Group PM | MEP PM | QS | Senior Site Supervisor | Site Supervisor | HR Manager | Administrative Executive |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `users:manage` | ✓ | ✓ | | | | | | | |
| `users:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `projects:manage` | ✓ | ✓ | ✓ | ✓ | | | | | |
| `projects:read` | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | | |
| `audit:view` | ✓ | ✓ | | | | | | | |
| `dashboard:company` | ✓ | ✓ | | | | | | ✓ | ✓ |
| `dashboard:scoped` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `reports:view` | ✓ | ✓ | ✓ | ✓ | | | | ✓ | |
| `reports:submit` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | |
| `reports:approve` | ✓ | ✓ | ✓ | ✓ | | | | ✓ | |
| `inventory:view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `inventory:manage` | ✓ | ✓ | | | | | | | |
| `suppliers:manage` | ✓ | ✓ | | ✓ | ✓ | | | | ✓ |
| `documents:view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `documents:manage` | ✓ | ✓ | | | | | | | |
| `financial:view` | ✓ | ✓ | | | | | | | |

MD = Managing Director; OD = Operations Director; Group PM = Group Project Manager; MEP PM = MEP Project Manager; QS =
Quantity Surveyor. The grant sets are explicit: a permission does not imply another
permission, and a role receives no future permission by default.

## HR permissions

HR Manager is the portal’s HR role and has permissions for standard employee records,
recruitment, onboarding, attendance recording, leave processing, ordinary HR
documents and compliance, service requests, and HR summaries. Only HR Manager
receives sensitive employee, attendance approval, leave approval, HR policy and
offboarding grants. Directory reads and private documents are separate from
account administration. An HR Manager can authorize a linked direct manager to
recommend specific time and leave requests when the company policy is enabled.
The authorization applies to that reporting relationship and does not grant
HR directory, document or final-decision permissions. See [HR and workforce](HR_WORKFORCE.md).

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
- `financial:view` grants read access to protected financial fields; it does not
  grant invoice, payment, or other finance mutations. Financial writes without an
  explicit matrix permission remain unavailable.
- Inventory management is granted only to MD and OD. That grant is required to
  create, reserve, issue or cancel material requests. Other inventory viewers
  receive scoped reads and can use the scoped request-project lookup.
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
  Group and MEP Project Managers, and HR Manager. The service rejects a
  self-approval and requires project membership for non-director decisions.
  [Role eligibility](../backend/app/utils/permissions.py) · [Report service](../backend/app/services/report_service.py) · [Supervisor service](../backend/app/services/reporting_service.py)
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
