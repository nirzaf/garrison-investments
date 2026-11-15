# Role catalogue cutover

> Historical runbook for the original ten-role cutover. See [Roles and permissions](ROLES_AND_PERMISSIONS.md) for today's nine-role catalogue. The current manifest utility validates against the role keys in its checked-out source, so the historical counts below do not describe current command output.

This runbook describes the one-time account-role migration for the exclusive
ten-role catalogue. It does not authorize a production cutover. The latest role
specification explicitly retires the former eight roles, including `admin`, and
requires every account (active, inactive, and soft-deleted) to receive a reviewed
mapping before activation.

## Preconditions

Before generating or applying a manifest:

1. Confirm the candidate application, frontend, and worker release contains only the
   target catalogue and has passed its required tests.
2. Obtain the accepted decisions for role scope and operations, exact account
   mappings, the designated production authorization, and the maintenance window.
   The named people in the source matrix are not verified database identities.
3. Verify a restorable backup and rehearse this command against a disposable
   PostgreSQL copy. Decide how pending approvals, outbox work, and queued imports
   will be paused or reconciled through their owning workflows.
4. Schedule maintenance, stop/drain API writers, workers, scheduled tasks, and
   administrative writers, and verify they remain stopped for the transaction.

Do not infer that a code review or role-design approval authorizes production writes.
Keep the user mapping and evidence references in a restricted operator location;
never commit those files or include names, emails, credentials, or OTPs in output.

## Generate and review the account manifest

From `backend/`, export a UUID-only template to a new restricted path:

```sh
umask 077
uv run python -m scripts.migrate_role_catalogue \
  --export-template /restricted/garrison-role-map.json
chmod 600 /restricted/garrison-role-map.json
```

The command refuses to overwrite an existing file. The template includes every
database account, its exact current role, timestamp, access revision, active state,
and soft-delete timestamp. It excludes account names and email addresses. Complete
the target role and reviewed evidence references for every row. The manifest also
requires operator, authorization, and maintenance-window references.

Verify all identity evidence independently. Do not use a name/email similarity
guess, silently omit an account, delete an unmapped account, or map unknown status
to a low-privilege role. A missing or ambiguous mapping blocks cutover.

## Dry run and apply

The normal command is read-only. It validates manifest syntax, private file
permissions, complete account coverage, unique UUIDs, exact database preconditions,
target role keys, and at least one usable post-cutover Managing Director or
Operations Director. Output is sanitized counts and the exact manifest SHA-256.

```sh
uv run python -m scripts.migrate_role_catalogue \
  --manifest /restricted/garrison-role-map.json
shasum -a 256 /restricted/garrison-role-map.json
```

Review the digest and the dry-run output against the separately approved evidence.
Only the designated operator may apply it after independently confirming that
production is in the approved maintenance window and all writers are stopped:

```sh
uv run python -m scripts.migrate_role_catalogue \
  --manifest /restricted/garrison-role-map.json \
  --apply \
  --confirm-manifest-sha256 EXACT_REVIEWED_SHA256
```

## Rehearsal-only gates and pending-work inventory

Run the following read-only commands against the disposable rehearsal database,
never against production as a substitute for the authorized cutover procedure:

```sh
uv run python -m scripts.migrate_role_catalogue --inspect-pending-workflows
uv run python -m scripts.migrate_role_catalogue --verify-current
```

The workflow inspection reports counts grouped by approval type/status, import
template/status, and task-outbox task/status. It contains no user identifiers,
names, addresses, comments, or payloads. These counts identify work that needs
separate owner review; they do not decide whether an item should be retained,
reassigned, paused, or cancelled. Use each owning workflow and the reviewed
account mapping to produce a restricted reconciliation record before activation.
The current-catalogue gate verifies every stored role against the ten-key set
and requires at least one active, unlocked, credentialed MD/OD account. It is a
read-only check, not evidence that an actual rehearsal or production migration
has run.

The apply mode takes the user-access advisory lock, locks all account rows in UUID
order, rechecks the full manifest, and performs changes in one database transaction.
It writes only supported target roles, increments every account's access revision,
updates timestamps, revokes refresh sessions and pending OTPs, and records sanitized
before/after audit events correlated to the supplied evidence references. This
invalidates all existing sessions because the effective role policy is being
replaced, including accounts whose key does not change.

If any precondition or write fails, the transaction rolls back. Do not restart the
old API or workers against partially changed data. Fix the reviewed manifest or
candidate and repeat the dry run. A verified exact rerun with the same manifest
digest is a no-op; a different prior migration receipt or divergent current role
state fails closed.

## Verification and reopen

After the transaction, while still in maintenance:

- Verify every `users.role`, including inactive and soft-deleted users, is one of
  the ten supported keys; compare the count by role to the approved manifest.
- Verify the exact role catalogue and 16-key grant matrix in backend and frontend.
- Verify no active/usable director was lost and that old access/refresh/OTP
  credentials cannot establish a session.
- Reconcile queued/pending work and run the approved positive and negative role
  checks against the candidate API. Do not treat this database transaction as
  atomic with deployment, browser caches, task queues, or object storage.
- Reopen traffic and workers only after the release owner records the required
  evidence and authorizes reopening.

For a disposable post-migration rehearsal, run `--verify-current` again after
the role transaction and verify the account counts against the reviewed manifest.
Capture the command, database identity, candidate SHA, and result in the
restricted rehearsal evidence. Do not put account rows or mapping manifests in
this repository.

After commit, normal corrections may move only among the ten supported roles,
must advance access revisions, revoke sessions, and append audit records. Do not
restore an old role, old authorization build, or a database backup over later
business activity as a routine rollback.

## Local synthetic migration rehearsal

On 2026-11-15, the cutover transaction was exercised against a freshly created
local PostgreSQL 18.6 database (`garrison_role_atomic_20261115_01`) on the
loopback-only `garrison-roles-postgres` test container. The schema was upgraded
through `202605310006`; the application worktree was based on `9aa8f231` and had
uncommitted changes. The database contained three synthetic accounts only; it
was dropped after the rehearsal.

The run injected a failure after the first account audit event and verified the
transaction restored roles, access revisions, active/deleted state, refresh
tokens, OTP challenges, and audit rows. A subsequent apply updated all three
synthetic accounts, incremented revisions, revoked three refresh sessions,
consumed three OTP challenges, preserved inactive/deleted states, and wrote
three account audit events plus one migration receipt. Replaying the exact
manifest returned `already_applied_noop` without another revision increment or
receipt. Manifest SHA-256: `b3a2f88128ad44c4284938bb5ada7eee4f980f66cb7133b52e1efd8e9cb91ece`.

This is local synthetic transaction evidence only. It does not satisfy the
production UUID-mapping, pending-work reconciliation, backup/recovery, business
decision, maintenance authorization, cutover, or post-cutover acceptance gates.

A second fresh local database (`garrison_role_cli_rehearsal_20261115_01`) exercised
the documented CLI. Its two synthetic accounts included one inactive and
soft-deleted account. `--export-template` produced a mode-0600 manifest; the
completed manifest passed CLI dry-run with SHA-256
`b7f3d02c3beb0d21188e7e27eaf9b37bc7d9841d5f19146d7296b6ac83589eef`. Before and
after dry-run, the account roles/revisions, live refresh-token and OTP counts,
and migration-audit count were identical. Digest-confirmed CLI apply succeeded;
`--verify-current` reported zero unsupported roles and one usable director;
`--inspect-pending-workflows` found no synthetic pending work; exact apply replay
returned `already_applied_noop`. Post-apply checks confirmed both sessions were
revoked, both OTPs consumed, preserved inactive/deleted state, and one migration
receipt. The temporary database and manifest were removed after verification.

## Current boundary

This worktree contains the new-role application changes and prepares the one-time
operator command and runbook. No live inventory, UUID mapping, production
migration, account assignment, maintenance action, or release acceptance is
claimed here. The report source identifies D02–D10 as business/scope
recommendations requiring their own recorded acceptance. Historical role text in
audit, approval, and import history remains unchanged.

## Local implementation verification (not release acceptance)

On 2026-11-15, the uncommitted worktree based on
`9aa8f2316de9682af5b6d046eeb8f884f4f0c532` was checked locally on branch
`main`. This is implementation evidence for that worktree, not a clean candidate
SHA, GitHub Actions result, deployment receipt, business approval, or production
acceptance.

- Backend: a fresh disposable PostgreSQL database was migrated through
  `202605310006`; `uv run pytest -q -rs --durations=10` completed with **861
  passed, 11 warnings** in 148.80 seconds. No skips were reported.
- Backend checks: `uv run ruff check .`, `uv run mypy .` (220 source files), and
  `uv run python scripts/export_openapi.py --check` passed.
- Frontend: `npm test` passed **50 tests in 10 files**; `npm run lint`,
  `npm run build`, and `npm run api:types:check` passed. Vite reported the
  existing bundle-size warning for the main JavaScript chunk.
- Chrome: `npm run test:browser -- --workers=2` completed with **42 passed** on
  Google Chrome using a fresh disposable migrated database, local Redis, and a
  local Moto S3 endpoint. No Edge run was included.
- `git diff --check` passed. The working tree remained dirty; these results do
  not bind to a commit containing the changes.

The legacy-role source scan used:

```sh
rg -n -w 'admin|general_manager|operation_manager|project_manager|civil_engineer|civil_supervisor|store_keeper|accounts' \
  backend/app backend/scripts backend/alembic frontend/src frontend/e2e frontend/public docs/openapi.json \
  --glob '!**/*.map'
```

The reviewed matches were retired-role rejection/explanation fixtures, `/admin/`
route and module names, ordinary variable names, and email addresses—not
accepted role values or authorization grants. The targeted tests separately
reject all eight retired role keys across authentication, assignment, imports,
CLI, queued-worker execution, and project/document scope guards. This local scan
must be repeated and classified on the eventual clean release candidate.

These checks do not complete TASK-35. D02–D10 approvals, the reviewed complete
production UUID manifest, live pending-work reconciliation, verified recovery,
maintenance authorization, production cutover, and post-cutover acceptance remain
outstanding.

## Workstream evidence map

All 35 tasks remain Essential. This table records local implementation evidence;
it is not a declaration that every binary acceptance criterion, business
decision, or production gate is complete. D02–D09 policy proposals remain
unapproved, so decision-dependent behavior remains provisional for release.

| Task | Local implementation evidence | Remaining boundary |
| --- | --- | --- |
| TASK-01 | Independent 10-role/16-permission fixture and decision register. | D02–D10 still need the recorded owner decisions described above. |
| TASK-02 | Ten-role catalogue, fail-closed auth/session checks, retired-role regression cases. | Repeat on the clean candidate. |
| TASK-03 | Exact matrix and permission parity tests; retired-role negative coverage. | Repeat on the clean candidate. |
| TASK-04 | Shared authorization/scope helpers and cross-scope API tests. | D02–D09 acceptance. |
| TASK-05 | Role catalogue API and CLI metadata use the target keys. | Repeat API/CLI verification on candidate. |
| TASK-06 | User-role ceilings, self-change guards, and last-usable-director serialization tests. | D05 owner approval. |
| TASK-07 | User-management revision handling and Chrome role-change workflow. | Business and release acceptance. |
| TASK-08 | Per-template/target import authorization and import API regressions. | D07 owner approval. |
| TASK-09 | Queued import actor/permission revalidation and worker regressions. | Production queue inventory and disposition. |
| TASK-10 | Report endpoint permission boundaries and API regressions. | D02 owner approval. |
| TASK-11 | Own-report authoring/recovery rules and daily-report regressions. | D02 owner approval and business UAT. |
| TASK-12 | Both supervisor roles and current-authority checks; supervisor workflow regressions. | D02 owner approval and business UAT. |
| TASK-13 | Report approval scope and separation-of-duties checks. | D08 owner approval and business UAT. |
| TASK-14 | Project update scope, revision, and closed-project tests. | D03 owner approval. |
| TASK-15 | Narrow project lookups and role-scope API coverage. | D02/D03 approval. |
| TASK-16 | Type-specific approval eligibility, delegation and inbox checks. | D07/D08 approval and pending-approval disposition. |
| TASK-17 | Current-recipient authorization and scheduled notification regressions. | Production pending-work inventory. |
| TASK-18 | Company and scoped dashboard APIs with role coverage. | D09 owner approval. |
| TASK-19 | Analytics role scope, financial filtering and export tests. | D06/D09 owner approval. |
| TASK-20 | Finance read/write separation and sensitive projection tests. | D06/D07 owner approval. |
| TASK-21 | Inventory read scope and price-safety API tests. | D03/D06/D07 owner approval. |
| TASK-22 | Inventory mutation boundaries and material-request workflow tests. | D07 owner approval and pending-work disposition. |
| TASK-23 | Supplier grant asymmetry and supplier API tests. | Clean-candidate role matrix. |
| TASK-24 | Document scope, management, and approver eligibility tests. | D04/D06 owner approval. |
| TASK-25 | Owning-record media and evidence authorization regressions. | Business UAT and candidate rerun. |
| TASK-26 | Audit visibility and retention-safety regressions. | D06/D07 owner approval; retain-only policy evidence remains external. |
| TASK-27 | Ten-role UI catalogue, selectors, navigation and Chrome role coverage. | Candidate build and release acceptance. |
| TASK-28 | Submit-only report editor/navigation browser coverage. | D02 owner approval and business UAT. |
| TASK-29 | Narrow document-page data dependencies and browser coverage. | D04 owner approval and business UAT. |
| TASK-30 | OpenAPI, generated TypeScript, docs, lint and build checks. | Re-run on the exact release candidate. |
| TASK-31 | Full backend/API/auth/scope/concurrency suite: 861 passed locally. | Re-run on the exact release candidate and self-hosted CI. |
| TASK-32 | Chrome-only Playwright suite: 42 passed locally. | QA/business sign-off and candidate-bound results. |
| TASK-33 | Local synthetic transaction and CLI rehearsals, including rollback, replay, and session revocation. | D10 reviewed production mapping; production pending-work and recovery evidence. |
| TASK-34 | Local source scan, retired-role rejection tests, and current-catalogue migration gate. | Repeat scan against a clean candidate; record production recovery/cutover rehearsal. |
| TASK-35 | Not executed. | Separate exact-manifest/candidate authorization, maintenance cutover, and post-cutover acceptance. |

## Legacy-reference release gate

Before activation, review old role-key matches in executable code, seeds,
imports, workers, API metadata, generated contracts, and positive account
fixtures. Search results are evidence to classify, not an automatic defect:
expected occurrences are the explicit rejection/migration tests, the manifest’s
exact pre-cutover role comparison, the source fixture’s retired-key list, and
historical/audit rendering. No old key may be an accepted role, alias,
permission fallback, new account default, import target, or positive login
fixture. Also verify that every former admin-only operation is either backed by
an explicit permission and object/scope rule or remains denied. Preserve
unrelated `/admin/...` route names and code identifiers that name an operator
variable rather than an application role.

Record the exact search command, reviewed files, classifications, and remaining
exceptions in the restricted candidate evidence. Do not treat this document’s
examples as a substitute for searching the release candidate.
