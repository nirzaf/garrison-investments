# Optional Post-Release Acceptance and Evidence Ledger

This is an optional follow-up ledger for the internal beta, not a release authorization checklist. Routine beta deployments rely on exact-candidate CI and the technical host checks in the [operations runbook](OPERATIONS_AND_DEPLOYMENT.md) and [beta release policy](BETA_RELEASE_POLICY.md). A host receipt may retain the literal status `Deployed — Formal Acceptance Pending`; that status records that this optional ledger was not completed and does not block further beta iterations.

Use the decision records and strict validators below only when the business owner requests a formal acceptance exercise. A passing deployment does not imply business sign-off, and an open optional acceptance item does not imply that the technical release failed.

The release and production facts in this ledger are point-in-time snapshots. For current deployment status, use the active `DEPLOYED` receipt and the dated snapshot in the [operations runbook](OPERATIONS_AND_DEPLOYMENT.md#current-beta-release-snapshot). Preserve older evidence as historical; do not rewrite it to match a later release.

## Confirmed scope and operating boundaries

- **Product scope:** `launch_readiness_only`; logistics scheduling, dispatch, fleet management, and delivery stock posting are not included.
- **Excluded requirement:** `G-01` remains excluded.
- **Audit retention:** Owner direction selects `retain_only` for this release. Keep destructive audit deletion disabled. The signed policy, class definitions, legacy inventory, and runtime proof still need to be recorded; no purge is authorized by this direction.
- **UAT platform scope:** Desktop Chrome is the routine automated browser target. Other browsers and physical iOS/Android targets are not universal release gates. Run additional scenarios when the change or a requested acceptance exercise calls for them.
- **Environment:** Production is the acceptance target. Staging has been abandoned and is not part of the acceptance evidence.
- **Data and personal evidence:** Keep real approvals, assignment exports, business samples, production receipts, and customer evidence in the approved restricted evidence store. Commit only blank templates and sanitized documentation.

<a id="current-hr-recruitment-release-reconciliation"></a>

## Historical HR recruitment release snapshot — 2026-11-15

As of 2026-11-15, `main` and `origin/main` point to
`f322d81059a679b982e72527e212e735b4ccc5de`. The commit contains HR-008/HR-010
recruitment changes and Alembic revision `202605310014`. Self-hosted CI run
[43735043858](https://github.com/nirzaf/garrison-investments/actions/runs/43735043858)
passed for this SHA. Production deployment run
[43736276674](https://github.com/nirzaf/garrison-investments/actions/runs/43736276674)
failed before activation: the host release script found pending database
migrations and requires the reviewed maintenance procedure. No migration or
deployment was run as part of this reconciliation.

The latest successful production receipt remains run
[43717032813](https://github.com/nirzaf/garrison-investments/actions/runs/43717032813),
for SHA `be61f5b74ce9701ba83f70261b03fe6219bd2d72` and schema
`202605310013`. A fresh public readiness request returned `ready` with the
database connected. The failed deployment stopped at the pre-activation
migration guard, and no later successful production run is recorded. However,
this review did not have access to the Hostinger `DEPLOYED` receipt or a direct
production Alembic query, so the current live SHA/schema are **last verified as**
`be61f5b` / `202605310013`, not independently re-read. Do not describe
`202605310014` as deployed or accepted. Its production maintenance and post-
deployment verification remain open; authenticated HR UAT and business
acceptance are separate from technical deployment and are optional beta follow-up.

The documentation inventory, per-file disposition, and source-backed findings
are recorded in the local [documentation audit](DOCUMENTATION_AUDIT.md). It
covers the 59 Markdown files tracked at baseline `f322d81`; the audit artifact
itself is additional. This is a source/documentation review, not production
verification, release acceptance, or business sign-off.

<a id="six-owner-decisions"></a>

## Optional owner decision register

| ID | Required owner | Required decision and evidence | Current closure state |
| --- | --- | --- | --- |
| **D-27-SCOPE** | Business sponsor | Sign the frozen accepted-scope inventory digest, `launch_readiness_only`, and explicit `G-01` exclusion. | Scope direction is known. The [scope inventory](ACCEPTED_SCOPE.md) at production SHA `1399710589f8f2d82bac2e79326bc9b88bbb888d` had byte SHA-256 `10d98679c75856ae9884790a0c4128b4e5040afaa1cedcd4184209a4a507a593`. Recompute the digest from the final frozen inventory before seeking authenticated approval. |
| **D-28-POLICY** | Records owner | Approve the retain-only policy ID/revision, event classes and predicates, deadlines, unknown-record disposition, and hold behavior. Attach the exact policy and its digest. Keep purge disabled. | Read-only production preview on release `9aa8f2316de9682af5b6d046eeb8f884f4f0c532` at `2026-11-14T17:21:38Z`: 222 records; 222 unclassified, 114 without deadlines, 108 with future deadlines, 0 purge-eligible. `LOG_PURGE_ENABLED=false`; the retention policy is currently `unconfigured` with no revision or digest. No deletion is enabled; signed policy and reviewed legacy classifications are still missing. |
| **D-29-RECOVERY** | System owner | Approve positive RPO/RTO, capture/publication limits, backup cadence and retention, independent destination/failure domains, key custodians, operators, coverage, and exercise interval. | Production maintenance for candidate `be61f5b74ce9701ba83f70261b03fe6219bd2d72` verified encrypted application and Grafana backup objects before migration `202605310013`. The encrypted application backup from 11:12 UTC on 2026-11-15 restored into disposable PostgreSQL at revision `202605310012`, and the isolated database passed the upgrade to `202605310013`. A separate synthetic authenticated format 2 rehearsal restored HR document objects and rejected wrong-key and tampered-artifact inputs. The production backup destination remains on the Hostinger failure domain, and its independent capture timer and service were absent. Approved recovery objectives, independent production publication, production key custody, and a timed off-host database and object restore remain outstanding. |
| **D-30-OPERATIONS** | Operations owner | Approve the production monitor profile, health targets, transport/sender, recipient groups, responders, thresholds, maintenance windows, and escalation/acknowledgement limits. | A deployed off-host monitor, recipient-confirmed firing/resolution delivery, and backup-freshness/failure-path evidence are outstanding. |
| **D-32-SUPPORT** | QA lead | Approve the exact desktop OS/Chrome version, role/scenario matrix, network profiles, numeric performance/data budgets, and named testers. | Candidate `be61f5b74ce9701ba83f70261b03fe6219bd2d72` passed [self-hosted CI](https://github.com/nirzaf/garrison-investments/actions/runs/43708858463) on attempt 2, including 51 Chrome regressions, 874 backend tests, and 50 frontend tests with no failures or skips in the successful reports. [Production deployment](https://github.com/nirzaf/garrison-investments/actions/runs/43717032813) records the exact SHA and schema `202605310013`. Readiness and database connectivity are healthy, login and service worker return HTTP 200, and anonymous HR directory and assignment requests return 401. At verification time production had zero active HR Manager accounts and zero HR employee records, so authenticated HR production UAT remains unexecuted. Named QA testers, the approved desktop OS and Chrome version, the role/scenario matrix, network and performance budgets, and human acceptance remain outstanding. |
| **D-33-BUSINESS** | Finance/data owner | Approve the role/project assignment export, five business samples, timezone, currency/precision/tax/rounding, thresholds, numbering, imports/control totals, four final signatories, and release authorizer. | Production currently reports USD, Asia/Qatar, and material-approval threshold `1000.00`; these observed values need business confirmation. Assignment reconciliation, five accepted samples, independently checked import/control totals, and final acceptance signatures remain outstanding. |

Every decision record needs an authenticated approval artifact bound to the canonical digest of its decision JSON (excluding `approval_ref`). An independent reviewer must verify the approval provenance. A chat message, name in a JSON field, or GitHub actor does not replace the signed artifact or independent verification.

<a id="operational-and-final-acceptance-gates"></a>

## Optional operational and final acceptance checklist

When a formal acceptance exercise is requested, decision signatures do not substitute for execution evidence. The closure bundle for that exercise should include:

- Read-only Hostinger verification on 2026-11-15 calculated the production configuration digest `e8e5a2e4096f3053037d1e9d0add587d704435fd0ac5dfaa4cec2dac51be706a` for live SHA `1399710589f8f2d82bac2e79326bc9b88bbb888d` from 20 protected files. This is a measured value for that release. Recompute the profile for the frozen acceptance candidate and obtain independent approval.

- Exact-candidate CI reports, deployment/readback, schema heads, image IDs, frontend/service-worker hashes, and the complete host `DEPLOYED` receipt.
- Production retention preview, complete legacy classifications/dispositions, retain-only setting, and scheduled-equivalent operational evidence. Do not manufacture a purge demonstration.
- Authenticated, independent database-and-object backup sets and a timed restore on an isolated host, with object/control-total verification and measured RPO/RTO.
- Off-host monitoring evidence for request/task signals, alert firing and resolution, human acknowledgement, backup freshness, redaction, and primary-host-loss detection.
- Desktop Chrome execution of the frozen role/scenario matrix, including degraded network, persisted results, failure/retry and business-chain checks.
- Reviewed legacy exception dispositions, business data reconciliation, zero unresolved in-scope defects, an approved observation cycle, and substitute-operator handover.

Only after those receipts are validated should the four D-33 final signatory roles (`business_sponsor`, `finance_data_owner`, `qa_lead`, `operations_owner`) approve the exact acceptance-bundle digest. Do not infer approval for repair, purge, production data changes, or deployment from a different-purpose decision.

## Evidence templates and runbook

- [Release-closure templates and canonical digest rules](templates/release-closure/README.md)
- [Operations and deployment runbook](OPERATIONS_AND_DEPLOYMENT.md)
- [Accepted release scope](ACCEPTED_SCOPE.md)
