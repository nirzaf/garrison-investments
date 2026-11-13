# Post-Release Governance and Formal Acceptance Backlog

Production deployments operate under technical CI, source, schema, backup, and live readiness controls while formal governance closure is completed post-release. Until all records below are completed and independently verified, the release status remains **Deployed — Formal Acceptance Pending**.

## Preserved Defaults and Exclusions

- **Delivery scope (`D-27` default):** Preserved as **Launch readiness only** (`launch_readiness_only`). Logistics, fleet management, dispatching, and delivery scheduling are not implemented.
- **Excluded scope (`G-01`):** `G-01` remains excluded from this release.
- **Audit retention safety (`D-28` default):** `LOG_PURGE_ENABLED=false` remains enforced. Automated audit log deletion stays disabled until an approved `D-28-POLICY` retention policy is recorded and verified.
- **Observability and backups (`D-29` / `D-30` defaults):** On-host Grafana/Loki/Alloy containers and existing encrypted database backup tooling (`scripts/backup.py`) remain intact. External restore hosts and off-host alert monitors are optional at initial launch.
- **Optional formal acceptance tooling:** [release_contract.py](../backend/scripts/release_contract.py), [launch_evidence.py](../backend/scripts/launch_evidence.py), and the [release-closure templates](templates/release-closure/README.md) remain available for optional post-release formal acceptance and are not executed automatically by CD.

## Deferred Governance Records

All six governance records are currently **Deferred — Post-release**:

| ID | Status | Responsible role | What remains to be done | Why it matters | Eventual required evidence | Accepted operational risk while incomplete |
|---|---|---|---|---|---|---|
| **D-27-SCOPE** | Deferred — Post-release | Business sponsor | Confirm and formally sign off the included feature inventory, preserving Delivery as launch readiness only and `G-01` excluded. | Establishes an authoritative baseline of delivered capabilities and boundary exclusions. | Signed scope inventory record and digest captured in the release closure package. | Scope relies on documented codebase defaults ([ACCEPTED_SCOPE.md](ACCEPTED_SCOPE.md)); formal sponsor sign-off is not yet recorded. |
| **D-28-POLICY** | Deferred — Post-release | Records owner | Define retention policy ID, audit classes, retention durations, leap-day rules, and legal hold policy, then record formal approval. | Governs lawful retention and prevents unauthorized or premature audit disposal. | Approved retain-only or retention policy file and SHA-256 verification matching `AUDIT_RETENTION_POLICY_*`. | Audit database growth is unbounded until retention is approved because `LOG_PURGE_ENABLED=false` disables all automated deletion. |
| **D-29-RECOVERY** | Deferred — Post-release | System owner | Provision an independent off-host backup destination and isolated restore host, name key custodians/operators, set RPO/RTO and pause/retention limits, and run a restore drill. | Proves encrypted backups can rebuild production independently if the primary host fails. | Signed recovery policy plus timed restore-drill receipt from an isolated restore host. | Backups run locally via `scripts/backup.py` and existing timers, but full-host failure recovery has not been validated against an off-host target. |
| **D-30-OPERATIONS** | Deferred — Post-release | Operations owner | Configure an independent off-host monitor, name primary and backup responders, wire external alert transport/recipients, and validate thresholds, backup freshness checks, and maintenance rules. | Ensures outages, certificate/backup drift, or silent host failures notify responders externally. | Completed monitor profile and verified external alert-delivery receipt (synthetic + recovery). | On-host Grafana/Loki observability and portal `/health/readiness` checks run, but external alerting on full host loss is unverified. |
| **D-32-SUPPORT** | Deferred — Post-release | QA lead | Confirm target test browsers/devices, assign named testers and remaining scenario roles, set measurable acceptance limits, execute formal UAT scenarios, and sign off results. | Provides independent pre-acceptance proof of end-to-end usability and defect triage across user roles. | Signed QA matrix and executed UAT results package. | Automated CI backend tests and Playwright browser regressions guard code changes, while formal human UAT sign-off remains open. |
| **D-33-BUSINESS** | Deferred — Post-release | Finance/data owner | Confirm user/project assignments, five worked financial samples, currency/timezone/precision/tax/numbering rules, material approval thresholds, import control totals, and final business signatories. | Verifies production business calculations, role assignments, and historical data accuracy against financial controls. | Signed business rules schedule, reconciled data import control receipts, and final release acceptance record. | Technical authentication, role isolation, and transactional integrity are enforced in code, while formal business/data reconciliation sign-off is pending. |

## Related Documents

- [Operations and Deployment Runbook](OPERATIONS_AND_DEPLOYMENT.md)
- [Accepted Release Scope](ACCEPTED_SCOPE.md)
- [Release Closure Templates](templates/release-closure/README.md)
