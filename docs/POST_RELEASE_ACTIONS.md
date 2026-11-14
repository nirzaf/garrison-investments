# Release Closure and Formal Acceptance

Production deployment and formal acceptance are separate states. Technical production deployments run automatically from `main` after passing CI and host safety checks and record `Status: Deployed — Formal Acceptance Pending`. This repository has a deployed production baseline, but deployment, a passing CI run, and a healthy readiness endpoint do not by themselves satisfy the attached formal acceptance specification. Until the records and evidence below are present, independently reviewed, and accepted by the optional strict validator ([release_contract.py](../backend/scripts/release_contract.py) / [launch_evidence.py](../backend/scripts/launch_evidence.py)), report status as **Deployed — Formal Acceptance Pending**.

## Confirmed scope and operating boundaries

- **Product scope:** `launch_readiness_only`; logistics scheduling, dispatch, fleet management, and delivery stock posting are not included.
- **Excluded requirement:** `G-01` remains excluded.
- **Audit retention:** Owner direction selects `retain_only` for this release. Keep destructive audit deletion disabled. The signed policy, class definitions, legacy inventory, and runtime proof still need to be recorded; no purge is authorized by this direction.
- **UAT platform scope:** Desktop Chrome only, per the user's latest instruction. Other browsers and physical iOS/Android targets are out of scope. This does not waive the required desktop scenarios, role coverage, degraded-network checks, or QA sign-off.
- **Environment:** Production is the acceptance target. Staging has been abandoned and is not part of the acceptance evidence.
- **Data and personal evidence:** Keep real approvals, assignment exports, business samples, production receipts, and customer evidence in the approved restricted evidence store. Commit only blank templates and sanitized documentation.

## Six owner decisions

| ID | Required owner | Required decision and evidence | Current closure state |
| --- | --- | --- | --- |
| **D-27-SCOPE** | Business sponsor | Sign the frozen accepted-scope inventory digest, `launch_readiness_only`, and explicit `G-01` exclusion. | Scope direction is known; authenticated approval bound to the final inventory digest is outstanding. |
| **D-28-POLICY** | Records owner | Approve the retain-only policy ID/revision, event classes and predicates, deadlines, unknown-record disposition, and hold behavior. Attach the exact policy and its digest. Keep purge disabled. | Retain-only is the selected operating mode; signed policy and complete legacy classification evidence are outstanding. |
| **D-29-RECOVERY** | System owner | Approve positive RPO/RTO, capture/publication limits, backup cadence and retention, independent destination/failure domains, key custodians, operators, coverage, and exercise interval. | Owner values, independent authenticated backup publication, and an isolated full database/object restore drill are outstanding. |
| **D-30-OPERATIONS** | Operations owner | Approve the production monitor profile, health targets, transport/sender, recipient groups, responders, thresholds, maintenance windows, and escalation/acknowledgement limits. | A deployed off-host monitor, recipient-confirmed firing/resolution delivery, and backup-freshness/failure-path evidence are outstanding. |
| **D-32-SUPPORT** | QA lead | Approve the exact desktop OS/Chrome version, role/scenario matrix, network profiles, numeric performance/data budgets, and named testers. | Exact-main CI run `43614318200` on `a0baa90db1c61adfabd285d24c1c69aa8c1b068c` passed every required job, including 34 desktop Chrome browser regressions (21+13; zero failures, errors, or skips) on Google Chrome 157.0.8103.78. Production deploy `43614911464` activated that exact SHA. The host receipt, public readiness check and database connectivity matched; Alembic was `202605310006 (head)`, and production `garrisonctl 1.0.0` health check returned `success`. QA still needs to approve the Chrome OS/version, assign named testers, complete the role/scenario matrix and performance/network budgets, review business/degraded-network results, and sign off. Other browsers and physical mobile targets are out of scope under the user's latest instruction. |
| **D-33-BUSINESS** | Finance/data owner | Approve the role/project assignment export, five business samples, timezone, currency/precision/tax/rounding, thresholds, numbering, imports/control totals, four final signatories, and release authorizer. | Assignment reconciliation, independently checked samples/import totals, and final acceptance signatures are outstanding. |

Every decision record needs an authenticated approval artifact bound to the canonical digest of its decision JSON (excluding `approval_ref`). An independent reviewer must verify the approval provenance. A chat message, name in a JSON field, or GitHub actor does not replace the signed artifact or independent verification.

## Operational and final acceptance gates

The decision signatures do not substitute for execution evidence. The closure bundle still needs, at minimum:

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
