# Roles and permissions

The portal accepts exactly the ten role keys below. Their grants are the fixed
16-key matrix in [the frontend role fixture](../frontend/src/pages/roles/rolePermissions.json)
and [the backend permission definitions](../backend/app/utils/permissions.py). The
independent [business matrix test fixture](../backend/tests/business_role_matrix.json)
checks the 160 source decisions. A role grant is only one authorization boundary:
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
| `hr_executive` | HR Executive |
| `administrative_executive` | Administrative Executive |

The eight former role keys are retired. They are not aliases, valid login roles,
assignment options, import targets, seed defaults, or worker privileges. Historical
records and explicit rejection/migration tests may still contain those strings.
There is no technical administrator role or role-based bypass.

## Permission matrix

| Permission | MD | OD | Group PM | MEP PM | QS | Senior Site Supervisor | Site Supervisor | HR Manager | HR Executive | Administrative Executive |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `users:manage` | ✓ | ✓ | | | | | | ✓ | | |
| `users:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `projects:manage` | ✓ | ✓ | ✓ | ✓ | | | | | | |
| `projects:read` | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | | | |
| `audit:view` | ✓ | ✓ | | | | | | ✓ | | |
| `dashboard:company` | ✓ | ✓ | | | | | | ✓ | | ✓ |
| `dashboard:scoped` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `reports:view` | ✓ | ✓ | ✓ | ✓ | | | | ✓ | ✓ | |
| `reports:submit` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | |
| `reports:approve` | ✓ | ✓ | ✓ | ✓ | | | | ✓ | | |
| `inventory:view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | ✓ |
| `inventory:manage` | ✓ | ✓ | | | | | | | | |
| `suppliers:manage` | ✓ | ✓ | | ✓ | ✓ | | | | | ✓ |
| `documents:view` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `documents:manage` | ✓ | ✓ | | | | | | | | |
| `financial:view` | ✓ | ✓ | | | | | | | | |

MD = Managing Director; OD = Operations Director; Group PM = Group Project Manager; MEP PM = MEP Project Manager; QS =
Quantity Surveyor. The grant sets are explicit: a permission does not imply another
permission, and a role receives no future permission by default.

## Authorization rules

- Only Managing Director and Operations Director have company-wide resource scope.
  Other project-scoped reads and writes require current project membership where the
  owning service enforces it. An empty membership set does not mean unrestricted.
- The API and service remain authoritative. Hiding a menu or button is not an
  authorization check. Current role, active state, access revision, ownership,
  membership, and workflow state are rechecked on protected actions.
- User management uses target-role ceilings. Directors may manage the ten supported
  roles. HR Manager cannot target a director or another HR Manager. Self-elevation,
  self-role change, self-deactivation, and self-password reset are blocked. Changes
  to access revoke refresh sessions and pending OTP challenges.
- Imports require `users:manage` and the permission for that import domain.
  Project and priced BOQ imports require director scope. Queued imports revalidate
  the submitting account before writes.
- `financial:view` grants read access to protected financial fields; it does not
  grant invoice, payment, or other finance mutations. Financial writes without an
  explicit matrix permission remain unavailable.
- Inventory management is granted only to MD and OD. Other inventory viewers receive
  scoped read access; visibility does not imply stock, master-data, reservation, or
  issue mutation rights.
- Company dashboard access does not imply company-wide project, report, document,
  audit, or financial access. Those paths enforce their own permission and scope.
- Submission and viewing are separate report permissions. A submitter without
  `reports:view` may recover only their own allowed work; do not widen the role
  matrix to make a page load.
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
