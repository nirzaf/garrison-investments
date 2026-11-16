# Documentation inventory and evidence audit

- Audit date: 2026-11-15
- Repository baseline: `f322d81059a679b982e72527e212e735b4ccc5de` (`main`)
- Inventory scope: the 59 Markdown files tracked at that baseline. This audit file is additional.

This is a source and documentation review. It is not a production inspection,
runtime test, deployment approval, business decision, or formal acceptance
record. The [post-release ledger](POST_RELEASE_ACTIONS.md) remains the only
release-status ledger.

## Method and limits

- Listed the tracked Markdown files at the baseline and classified each by its
  owning topic, lifecycle, source authority, and disposition.
- Compared current behavior claims with the linked routes, services, models,
  permissions, migrations, CI/deployment workflows, and release evidence where
  available. Source code and database migrations are authoritative for
  executable behavior; generated API types and guides are supporting references.
- Every path received an owner/lifecycle classification. Detailed source checks
  focused on the findings below, role parity, schema-column coverage, and the
  cited release records. A `retain` disposition is an inventory/audit decision,
  not sentence-by-sentence certification of every page.
- Checked the standard schema pages against SQLAlchemy metadata: 34 table pages
  were checked for missing or extra columns. The HR schema page is a separate
  constraints/relationships reference and explicitly distinguishes production
  revision `202605310013` from pending revision `202605310014`.
- Used the exact-source CI and deployment records already linked by the release
  ledger. The live host receipt and production Alembic state were not directly
  re-read for this audit; production state below is therefore attributed to
  that ledger, not independently certified here.
- No application code, database, credentials, or production configuration were
  changed. No application tests were run for this documentation-only review.

## Findings and evidence

| Document | Finding | Current claim | Verified behavior | Source evidence path:line | Severity | Resolution |
| --- | --- | --- | --- | --- | --- | --- |
| [docs/BUSINESS-ROLE-DECISIONS.md](BUSINESS-ROLE-DECISIONS.md):11 | Original role count was easy to misread as current. | D01 directs use of the source matrix's ten roles and 16 standard permissions. | The source fixture has ten historical roles, including `hr_executive`; current code exposes nine roles and 37 permission keys. `hr_executive` is absent from current role definitions and is guarded by the retirement migration. | `docs/BUSINESS-ROLE-DECISIONS.md:11`; `backend/tests/business_role_matrix.json:36-46`; `docs/ROLES_AND_PERMISSIONS.md:10-28,68-72`; `backend/app/utils/permissions.py:6-28`; `backend/alembic/versions/202605310011_retire_hr_executive.py:17-29` | P2 — role-policy clarity | D01 now states the source/current lineage and current counts. No role or permission code changed. |
| [docs/HR_WORKFORCE.md](HR_WORKFORCE.md):33 | Source capability could be mistaken for deployed recruitment capability. | Recruitment is marked `CODED`, with migration 014 explicitly noted as pending production. | Candidate SHA `f322d81` passed CI, but deploy run 43736276674 stopped at the migration guard. Last successful receipt in the ledger is schema 013; live schema was not independently re-read here. | `docs/HR_WORKFORCE.md:29-35`; `backend/alembic/versions/202605310014_hr_recruitment_followups.py:1-20`; `docs/POST_RELEASE_ACTIONS.md:16-37`; Actions runs [43735043858](https://github.com/nirzaf/garrison-investments/actions/runs/43735043858) and [43736276674](https://github.com/nirzaf/garrison-investments/actions/runs/43736276674) | P1 — release-state clarity | README now says its feature list is source-level. Deployment, live readback, HR UAT, and acceptance remain open in the release ledger. |
| [docs/BUSINESS-ROLE-DECISIONS.md](BUSINESS-ROLE-DECISIONS.md):22-37 | Decision provenance must not be confused with authenticated approval. | D02–D10 are proposals; the input matrix's review status is pending; this file says it does not authorize production changes. | The repository records proposed implementation rules and source provenance, not signed decisions or verified production account mappings. This review did not inspect external approval stores. | `docs/BUSINESS-ROLE-DECISIONS.md:22-37`; `backend/tests/business_role_matrix.json:2-16`; `docs/POST_RELEASE_ACTIONS.md:45-56` | Informational — no mismatch found | Kept the pending/proposed wording. No approval was inferred. |
| [docs/ACCEPTED_SCOPE.md](ACCEPTED_SCOPE.md):1-3 | Scope direction and formal acceptance are separate. | Scope is `launch_readiness_only`, excludes G-01, and remains unsigned. | The scope page and release ledger both say authenticated approval and formal acceptance remain pending; no signatory record was validated here. | `docs/ACCEPTED_SCOPE.md:1-3`; `docs/POST_RELEASE_ACTIONS.md:1-12,58-71`; `docs/OPERATIONS_AND_DEPLOYMENT.md:358-377` | Release gate — acceptance pending | Retained the unsigned status and release-ledger ownership. |
| [STAGING_DEPLOYMENT.md](../STAGING_DEPLOYMENT.md):1-5; [historical guides](PRODUCTION_READINESS_REVIEW.md):1-3; [role cutover](ROLE_CATALOGUE_CUTOVER.md):1-3 | Older procedures could be reused as current instructions. | The documents label staging retired, the July review historical, and the original role cutover historical. | Those labels direct operators and readers to current production/role guides. This was a lifecycle classification check, not a line-by-line revalidation of each historical claim. | `STAGING_DEPLOYMENT.md:1-5`; `docs/PRODUCTION_READINESS_REVIEW.md:1-5`; `docs/ROLE_CATALOGUE_CUTOVER.md:1-9`; `graphify-out/2026-11-13/GRAPH_REPORT.md:1-3` | Informational — historical status clear | Retained historical files; the documentation map points to current guides. |
| [docs/schema/README.md](schema/README.md):5-7; [docs/schema/hr.md](schema/hr.md):3-13 | Schema documentation must distinguish model columns from live constraints and pending migrations. | The index describes core and HR schema references; the HR page says production 013 plus pending 014. | The 34 standalone core table column lists match SQLAlchemy metadata; all 48 HR model tables appear in the HR inventory. This audit did not query production PostgreSQL or verify every constraint/type narrative. | `docs/schema/projects.md:7-26`; `backend/app/models/project.py:12-36`; `docs/schema/hr.md:3-13`; `backend/alembic/versions/202605310014_hr_recruitment_followups.py:13-52` | Informational — column coverage checked; constraints limited | No schema docs changed. Kept the 013/014 boundary explicit and recorded column-only coverage. |
| [docs/OPERATIONS_AND_DEPLOYMENT.md](OPERATIONS_AND_DEPLOYMENT.md):69-115 | CI speed opportunities need exact-candidate evidence. | Operations guide asks each release to compare queue, elapsed time, slow steps, and cache behavior. | Run 43735043858 passed; total wall time was 787s. Compose checkout spent about 108s fetching; backend pytest/JUnit case sums diverged. A single sample does not prove a stable workflow or shard optimization. | `docs/OPERATIONS_AND_DEPLOYMENT.md:69-115`; `.github/workflows/ci.yml:97-128`; `backend/tests/conftest.py:8-26`; Actions run 43735043858 and its JUnit artifacts | P2 — performance investigation | Added one exact-source measurement and follow-up checks. No workflow, checkout, or shard changes were made. |
| [docs/POST_RELEASE_ACTIONS.md](POST_RELEASE_ACTIONS.md):14-37 | Release ledger separates production deployment from formal acceptance. | It records latest successful release, failed pending-migration attempt, and limits on direct live readback. | Available evidence supports last verification at SHA `be61f5b`/schema 013 and says the 014 deployment stopped before activation; current live state was not independently observed in this audit. | `docs/POST_RELEASE_ACTIONS.md:1-12,14-43,58-71`; `.github/workflows/deploy.yml:1-43`; Actions run 43736276674 | Release gate — live state not re-read | Preserved the single ledger and added a link to this audit; no deployment status was inferred. |

## Markdown inventory and per-file disposition

`Current` means the page is intended for present use; `Historical` means it is
kept to explain an earlier state; `Generated` means it is a tool output;
`Template` means it is deliberately unsigned; `Instruction` means it governs
agent/tool behavior. `Source-checked` is limited to the claims stated in the
review-depth cell; `Classification-only` means title/introduction and lifecycle
were checked without verifying behavior. `Column-only` means documented column
names were compared with model metadata, not constraints or narrative. “Retain”
records disposition, not a claim that runtime behavior was exercised.

### Instructions and tool configuration

| File | Owner/use and lifecycle | Review depth | Source pointer | Audit disposition / change |
| --- | --- | --- | --- | --- |
| [.kilo/agents/architect.md](../.kilo/agents/architect.md) | Kilo architect agent; Instruction | Classification-only; content not source-checked | Agent configuration | Retain; no change. |
| [.kilo/agents/test-engineer.md](../.kilo/agents/test-engineer.md) | Kilo test-engineer agent; Instruction | Classification-only; content not source-checked | Agent configuration | Retain; no change. |
| [.trae/skills/graphify/SKILL.md](../.trae/skills/graphify/SKILL.md) | Trae Graphify tool; Instruction | Classification-only; content not source-checked | Graphify skill definition | Retain; no change. |
| [AGENTS.md](../AGENTS.md) | Repository maintainers and agents; Current instruction | Instruction content reviewed; no executable behavior inferred | Source maps, CI/deploy workflows, and runbooks linked in the file | Retain; no change. |

### Product, role, and operations guides

| File | Owner/use and lifecycle | Review depth | Source pointer | Audit disposition / change |
| --- | --- | --- | --- | --- |
| [README.md](../README.md) | Product overview and developer setup; Current | Focused source check of source-versus-production boundary; feature rows not exhaustively verified | [Routes](../frontend/src/App.tsx), [API routers](../backend/app/api/v1/), [release ledger](POST_RELEASE_ACTIONS.md) | Added a note that feature inventory describes source capability, not automatic production activation or acceptance. |
| [STAGING_DEPLOYMENT.md](../STAGING_DEPLOYMENT.md) | Staging retirement notice; Historical/retired | Classification-only; retirement label checked | [Production workflow](../.github/workflows/deploy.yml) | Retain; no change. |
| [backend/ARCHITECTURE.md](../backend/ARCHITECTURE.md) | Backend contributor guide; Current | Classification and link-pointer check; procedures not executed | [FastAPI app](../backend/app/main.py), [backend tests](../backend/tests/) | Retain; no change. |
| [docs/ACCEPTED_SCOPE.md](ACCEPTED_SCOPE.md) | Release scope inventory; Current but unsigned | Focused source check of scope and unsigned status; no owner approval verified | [Source feature map](../README.md), [release ledger](POST_RELEASE_ACTIONS.md) | Retain unsigned status; no decision inferred. |
| [docs/ARCHITECTURE.md](ARCHITECTURE.md) | System architecture and invariants; Current | Source spot-check of runtime and release links; not a full behavior audit | [Runtime sources](../backend/app/main.py), [production Compose](../docker-compose.prod.yml) | Retain; no change. |
| [docs/BUSINESS-ROLE-DECISIONS.md](BUSINESS-ROLE-DECISIONS.md) | Role/source decision lineage; Current record | Source-checked for D01 lineage and D02–D10 status | [Current permissions](../backend/app/utils/permissions.py), [source matrix](../backend/tests/business_role_matrix.json) | Clarified D01's historical ten-role matrix versus the current nine-role catalogue; D02–D10 remain proposed/pending. |
| [docs/CLI_ADMINISTRATION.md](CLI_ADMINISTRATION.md) | `garrisonctl` user guide; Current | Focused pointer/overview check; command catalog not exhaustively compared or run | [CLI entry point](../backend/scripts/garrisonctl.py), [HR CLI registration](../backend/scripts/garrisonctl_hr.py) | Retain; no change. |
| [docs/HR_WORKFORCE.md](HR_WORKFORCE.md) | HR operator guide; Current, source-backed | Focused source review of recruitment claims, migration 014, and release caveat; other workflows not exhaustively checked | [HR routes](../backend/app/api/v1/hr.py), [workforce service](../backend/app/services/hr_workforce_service.py), [migration 014](../backend/alembic/versions/202605310014_hr_recruitment_followups.py) | Migration 014 is clearly marked pending production; authenticated UAT remains open. |
| [docs/LOGGING_AND_REMOTE_CLI.md](LOGGING_AND_REMOTE_CLI.md) | Logging and remote-log guide; Current | Classification and source-pointer spot-check only | [Logs API](../backend/app/api/v1/logs.py), [observability config](../observability/) | Retain; no change. |
| [docs/OPERATIONS_AND_DEPLOYMENT.md](OPERATIONS_AND_DEPLOYMENT.md) | Release, maintenance, recovery, and evidence runbook; Current | Source-checked for CI timing and release-state sections; remaining operations not executed | [CI](../.github/workflows/ci.yml), [deploy workflow](../.github/workflows/deploy.yml), [host release script](../deploy/hostinger-release.sh) | Added the exact `f322d81` CI timing sample and measured checkout/shard follow-ups; no workflow changes. |
| [docs/POST_RELEASE_ACTIONS.md](POST_RELEASE_ACTIONS.md) | Single release and acceptance ledger; Current | Focused source/evidence review of HR release state; external decisions not authenticated | [Release validator](../backend/scripts/release_contract.py), [operations runbook](OPERATIONS_AND_DEPLOYMENT.md) | Replaced the audit-missing statement with a link to this audit; preserved pending production/acceptance gates. |
| [docs/PRODUCTION_READINESS_REVIEW.md](PRODUCTION_READINESS_REVIEW.md) | Review dated 2026-07-27; Historical | Classification-only; historical date/scope label checked | [Current operations runbook](OPERATIONS_AND_DEPLOYMENT.md) | Retain; no change. |
| [docs/README.md](README.md) | Documentation navigation map; Current | Navigation and local-link check; destination behavior not exhaustively verified | Links to the owning guides and their code sources | Retain; no change. |
| [docs/ROLES_AND_PERMISSIONS.md](ROLES_AND_PERMISSIONS.md) | Current role and authorization guide; Current | Source-checked for role and permission parity only; no authorization matrix behavior tests run | [Permission definitions](../backend/app/utils/permissions.py), [role fixture](../frontend/src/pages/roles/rolePermissions.json) | Nine current roles and 37 permission keys align; retain. |
| [docs/ROLE_CATALOGUE_CUTOVER.md](ROLE_CATALOGUE_CUTOVER.md) | Original ten-role cutover instructions; Historical | Classification-only; historical label and link checked | [Current role catalogue](ROLES_AND_PERMISSIONS.md), [retirement migration](../backend/alembic/versions/202605310011_retire_hr_executive.py) | Retain; no change. |
| [docs/import_templates/README.md](import_templates/README.md) | Import operator guide; Current | Focused entry/link check; import behavior not exhaustively verified | [Import page](../frontend/src/pages/admin/ImportPage.tsx), [import API](../backend/app/api/v1/imports.py) | Retain; no change. |

### Database schema references

The schema index and 34 standalone core-table pages below were compared with the
corresponding SQLAlchemy models for column coverage. Each page links to its
model; relationship and constraint claims remain subject to the migration and
live-schema distinction stated in the index. HR is summarized separately in
`docs/schema/hr.md`.

| File | Model/source pointer | Review depth | Audit disposition / change |
| --- | --- | --- | --- |
| [docs/schema/README.md](schema/README.md) | [Models](../backend/app/models/), [migrations](../backend/alembic/versions/) | Index/revision-boundary spot-check only | Retain; no change. |
| [activity_log.md](schema/activity_log.md) | [activity_log.py](../backend/app/models/activity_log.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [approvals.md](schema/approvals.md) | [approval.py](../backend/app/models/approval.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [auth_otp_challenges.md](schema/auth_otp_challenges.md) | [auth.py](../backend/app/models/auth.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [auth_refresh_tokens.md](schema/auth_refresh_tokens.md) | [auth.py](../backend/app/models/auth.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [boq_items.md](schema/boq_items.md) | [boq_item.py](../backend/app/models/boq_item.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [daily_report_approval_history.md](schema/daily_report_approval_history.md) | [daily_report.py](../backend/app/models/daily_report.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [daily_reports.md](schema/daily_reports.md) | [daily_report.py](../backend/app/models/daily_report.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [document_versions.md](schema/document_versions.md) | [document.py](../backend/app/models/document.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [documents.md](schema/documents.md) | [document.py](../backend/app/models/document.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [hr.md](schema/hr.md) | [hr.py](../backend/app/models/hr.py), [migrations](../backend/alembic/versions/) | HR table inventory and 013/014 wording spot-checked; no live DB query | Lists 48 HR model tables; retains production-013/pending-014 distinction. |
| [idempotency_records.md](schema/idempotency_records.md) | [idempotency_record.py](../backend/app/models/idempotency_record.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [import_batches.md](schema/import_batches.md) | [import_batch.py](../backend/app/models/import_batch.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [inventory_assets.md](schema/inventory_assets.md) | [inventory.py](../backend/app/models/inventory.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [inventory_items.md](schema/inventory_items.md) | [inventory.py](../backend/app/models/inventory.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [inventory_location_stock.md](schema/inventory_location_stock.md) | [inventory.py](../backend/app/models/inventory.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [inventory_movements.md](schema/inventory_movements.md) | [inventory.py](../backend/app/models/inventory.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [invoices.md](schema/invoices.md) | [finance.py](../backend/app/models/finance.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [material_request_lines.md](schema/material_request_lines.md) | [inventory.py](../backend/app/models/inventory.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [material_requests.md](schema/material_requests.md) | [inventory.py](../backend/app/models/inventory.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [notifications.md](schema/notifications.md) | [notification.py](../backend/app/models/notification.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [payments.md](schema/payments.md) | [finance.py](../backend/app/models/finance.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [photos.md](schema/photos.md) | [photo.py](../backend/app/models/photo.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [project_members.md](schema/project_members.md) | [project_member.py](../backend/app/models/project_member.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [project_milestones.md](schema/project_milestones.md) | [project_milestone.py](../backend/app/models/project_milestone.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [project_tasks.md](schema/project_tasks.md) | [project_task.py](../backend/app/models/project_task.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [projects.md](schema/projects.md) | [project.py](../backend/app/models/project.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [report_equipment.md](schema/report_equipment.md) | [daily_report.py](../backend/app/models/daily_report.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [report_exports.md](schema/report_exports.md) | [report_export.py](../backend/app/models/report_export.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [report_manpower.md](schema/report_manpower.md) | [daily_report.py](../backend/app/models/daily_report.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [report_material_consumption.md](schema/report_material_consumption.md) | [daily_report.py](../backend/app/models/daily_report.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [storage_locations.md](schema/storage_locations.md) | [inventory.py](../backend/app/models/inventory.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [supervisor_updates.md](schema/supervisor_updates.md) | [supervisor_update.py](../backend/app/models/supervisor_update.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [suppliers.md](schema/suppliers.md) | [supplier.py](../backend/app/models/supplier.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [task_outbox.md](schema/task_outbox.md) | [task_outbox.py](../backend/app/models/task_outbox.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |
| [users.md](schema/users.md) | [user.py](../backend/app/models/user.py) | Column-only; constraints and narrative not reviewed | Column names match; retain. |

### Templates and generated reports

| File | Owner/use and lifecycle | Review depth | Source pointer | Audit disposition / change |
| --- | --- | --- | --- | --- |
| [docs/templates/release-closure/README.md](templates/release-closure/README.md) | Release owner; unsigned evidence templates | Classification/link check; no approval artifact authenticated | [Release contract](../backend/scripts/release_contract.py), [ledger](POST_RELEASE_ACTIONS.md) | Retain; templates remain blank/unsigned. |
| [graphify-out/2026-11-13/GRAPH_REPORT.md](../graphify-out/2026-11-13/GRAPH_REPORT.md) | Generated Graphify snapshot dated 2026-11-13; Historical | Classification-only; graph contents not source-revalidated | Generated graph corpus | Retain as dated snapshot; no change. |
| [graphify-out/GRAPH_REPORT.md](../graphify-out/GRAPH_REPORT.md) | Generated Graphify report dated 2026-11-15; Generated snapshot | Classification-only; graph not refreshed for this audit | Generated graph corpus | Retain; no change. |

## Per-file change log

### `README.md`

- **Change:** Added a note that the feature table describes source code and is
  not proof that every feature is active or accepted in production.
- **Why:** HR follow-up code is present in the candidate source while migration
  `202605310014` remains pending in the available deployment evidence.
- **Supporting source:** `README.md:7-12`; `docs/HR_WORKFORCE.md:29-35`;
  `docs/POST_RELEASE_ACTIONS.md:16-37`; Actions runs 43735043858 and 43736276674.

### `docs/BUSINESS-ROLE-DECISIONS.md`

- **Change:** Clarified D01 as a ten-role source-matrix decision whose
  `hr_executive` role was later retired; recorded today's nine roles and 37
  permissions.
- **Why:** The source decision and current catalogue differ after migration
  `202605310011`; the old sentence could be read as a current ten-role grant.
- **Supporting source:** `docs/BUSINESS-ROLE-DECISIONS.md:11`;
  `backend/tests/business_role_matrix.json:36-51`;
  `backend/app/utils/permissions.py:6-28`;
  `docs/ROLES_AND_PERMISSIONS.md:10-28,68-72`;
  `backend/alembic/versions/202605310011_retire_hr_executive.py:17-29`.

### `docs/OPERATIONS_AND_DEPLOYMENT.md`

- **Change:** Added the exact `f322d81` CI sample, job/test timings, and measured
  checkout and shard investigation candidates.
- **Why:** The operations guide requires timing review for each release. This
  sample shows a 108-second fetch and divergent backend case-time totals, but
  does not justify changing checks, checkout safety, or shard weights alone.
- **Supporting source:** `docs/OPERATIONS_AND_DEPLOYMENT.md:69-115`;
  `.github/workflows/ci.yml:97-128`;
  `backend/tests/conftest.py:8-26`; Actions run 43735043858 and its JUnit
  artifacts.

### `docs/POST_RELEASE_ACTIONS.md`

- **Change:** Replaced the audit-missing placeholder with a pointer to this
  inventory and findings artifact. The previously recorded HR release
  reconciliation remains intact.
- **Why:** Keep release status in this one ledger while making the separate
  documentation-audit evidence discoverable.
- **Supporting source:** `docs/POST_RELEASE_ACTIONS.md:14-43` and this audit's
  findings/inventory sections. No production state was changed or inferred.

### `docs/DOCUMENTATION_AUDIT.md` (new)

- **Change:** Added the baseline inventory, source-evidence matrix, per-file
  review depth, changed-file rationale, and coverage limits.
- **Why:** The previous documentation had no complete inventory or matrix and
  did not distinguish source review from classification-only review.
- **Supporting source:** Scope and evidence are linked in each matrix row and
  inventory record; validation results are recorded below.

## Remaining coverage

The 59-file inventory is complete for the pinned baseline, but this is not an
exhaustive behavioral audit of every sentence or feature. The following limits
remain:

- The `.kilo` and `.trae` files, retired staging notice, dated historical
reviews, generated Graphify reports, and unsigned templates received the
classification or spot checks stated in the inventory; their full contents
were not revalidated against current runtime behavior.
- The 34 core schema pages were compared for column names only. Constraints,
relationships, type/default narratives, and current production DDL were not
fully inspected. The 48-table HR inventory was spot-checked against source
models, not live PostgreSQL.
- Product and CLI guides marked focused, pointer, or classification-only were
not checked sentence by sentence or exercised through every role/workflow.
- HR workflows, Chrome browser UAT, production authorization, and persisted
business outcomes were not executed in this documentation review. CI results
are linked exact-source evidence only.
- Production migration/deployment state was not directly read during this
review; the release ledger's last verified state remains the evidence boundary.
- D-27–D-33 approval artifacts, signatures, policy digests, and external
business acceptance were not authenticated here. No missing names, dates,
approvals, or evidence references were inferred.
- No local application test, integration test, or browser session was run for
this documentation-only change.

## Current release and operational unknowns

These are intentionally left to the existing release ledger and evidence owners:

- Production migration `202605310014`, deployment activation, direct live schema
  readback, and authenticated HR Manager UAT were not completed by this audit.
  The latest available deployment record stopped at the pre-activation
  migration guard.
- No current production `DEPLOYED` receipt was retrieved during this audit; the
  ledger records the last verified production release and explicitly marks its
  limitations.
- The audit did not authenticate or sign scope, business, finance, operations,
  recovery, or QA decisions. It does not close any D-27–D-33 acceptance gate.
- CI timings are single-run observations. The checkout delay and shard imbalance
  should be compared with another exact-source run before altering runner
  configuration, repository checkout behavior, test weights, or concurrency.
- The dated Graphify outputs were not refreshed. The repository's explicit
  `/graphify` invocation rule was not triggered by this audit.

## Verification performed

- Baseline and worktree inspected: `main` at `f322d81059a679b982e72527e212e735b4ccc5de`; pre-existing local changes were preserved.
- Tracked Markdown inventory: 59 files before adding this audit.
- Schema/model inspection: 34 standalone core table pages checked against SQLAlchemy model columns; no missing or extra columns were recorded.
- Exact-source CI evidence: run `43735043858` passed all seven required jobs; downloaded JUnit artifacts show 875 backend cases and 52 Chrome cases with no failures or skips, plus 50 frontend tests.
- Role reference parity: the current frontend fixture, backend permission definitions, and role guide agree on nine roles and 37 permission keys.
- Markdown links: all local paths and heading anchors in the 59 baseline Markdown files and this audit artifact passed validation.
- Exact-source deployment evidence: run `43736276674` failed at the pending migration guard before activation; see the [release ledger](POST_RELEASE_ACTIONS.md#current-hr-recruitment-release-reconciliation).
- No application test suite or browser session was run locally; the CI browser results are linked evidence, not an interactive browser test by this audit.
