# Business role policy decisions

This record separates the source checkbox matrix from action and data-scope rules
that the matrix does not define. The source-backed matrix and hashes are in
[`backend/tests/business_role_matrix.json`](../backend/tests/business_role_matrix.json).

## Decision register

| ID | Topic | Current record | Release effect |
| --- | --- | --- | --- |
| D01 | Replace legacy role catalogue | **Directed by the user:** retire the eight legacy roles, including `admin`, and use the source matrix's ten-role set and sixteen standard permissions. That source set included `hr_executive`; later migration `202605310011` retired that role. The current application catalogue has ten business roles and 37 permission keys (16 standard plus 21 HR). HR Executive uses the distinct key `hr_executive_reader` and receives only the four owner-authorized standard grants from column J. | The role replacement is implemented in application code. This records source-decision lineage; it is not production account-migration approval. See [current roles](ROLES_AND_PERMISSIONS.md) and [the HR Executive retirement migration](../backend/alembic/versions/202605310011_retire_hr_executive.py). |
| D02 | Report authoring without `reports:view` | Proposed source-aligned behavior: submitters can access only their own drafts and permitted evidence. | Implement narrowly; production acceptance remains pending. |
| D03 | Project scope and initial commercial setup | Proposed: Managing Director and Operations Director have company resource scope; Group/MEP Project Managers are membership-scoped; initial priced project setup remains director-only. | No company-wide scope for dashboard-only roles. Business confirmation remains pending. |
| D04 | Company and private document scope | Proposed: company-wide director scope; other roles need active project membership. Unscoped/company documents require explicit classification. | Do not broaden null-project document access. Business confirmation remains pending. |
| D05 | User administration ceilings | Directors approve and apply account changes. HR Managers request changes through the HR workflow and may review requests prepared by a different HR Manager. | Preserve one usable director account and prohibit self-role elevation. HR Manager retains operational HR authority. HR Executive holds the four [read grants](HR_WORKFORCE.md#hr-executive-scope-and-proposed-hr-tasks). |
| D06 | Financial confidentiality | Proposed: only roles granted `financial:view` may read finance and other monetary detail; omit withheld values rather than returning zero. | Finance writes remain denied for all roles because the matrix grants no write permission. Business confirmation remains pending. |
| D07 | Operations without a permission key | No implied grants for finance writes, generic overrides, special backdating, purge/configuration, or non-report decisions. | Deny/remove unsupported operations. Business confirmation remains pending. |
| D08 | Separation of duties | Proposed: no submitter self-approval; no override bypass. | Enforce in workflow services. Business confirmation remains pending. |
| D09 | Company dashboard versus resource details | Proposed: company aggregates for directors, HR Manager, and Administrative Executive; each underlying project/report/document/finance endpoint keeps its own grant and scope. | Aggregate access cannot imply record detail or finance access. Business confirmation remains pending. |
| D10 | Account UUID mapping and production cutover | No UUID mapping or signed account manifest is present in this repository change. | A reviewed complete manifest, rehearsal, recovery evidence, and separate production authorization are required before data changes. |

## Provenance and limits

The input guideline records source hashes `14908d4dd6137a7fec539f384cbdbf75604575d94369f445ae87a6da1bc4fdcc`
and `facb5c27a718eeeec8ab9329444f3f9681bc11c2b9f7b9bd47c7a381caad6a3b` and an
original review status of **Pending review**. D01 is separately recorded as the
user-directed role replacement. This file does not fill the HTML reviewer or
approval fields and does not identify database accounts by job title or name.

The independent test fixture preserves the original matrix HTML header line and
worksheet coordinates: role/person rows 4–5, decision rows 6–21, review row 22,
and guide rows 5–20 plus 22. The fixture’s person labels are source references,
not verified identities for account assignment.

The D02–D10 entries are implementation proposals, not signed business decisions.
No production account, permission, database, or deployment change is authorized
by this record.


## HR workforce scope

The HR implementation changes the earlier role-only D05 behavior for HR Manager.
Direct platform user mutations remain with the two directors. HR uses the
reviewed account handoff, and generic audit and project-document grants are
separate from the HR workspace. See [HR and workforce](HR_WORKFORCE.md).
