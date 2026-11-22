# Beta lifecycle and release policy

Garrisons is an internal beta. The team may ship small, frequent improvements
once the exact candidate passes the repository's required CI and the existing
deployment checks. Beta releases do not wait for a general-purpose production
readiness dossier, signed governance bundle, extended observation cycle, or
full device matrix.

This policy removes optional acceptance paperwork as a universal release gate.
It does not weaken authentication, authorization, privacy, audit, data
integrity, migration, incident-response, or production authorization controls.

## Routine beta release

For a change that does not alter persistent data or stateful infrastructure:

1. Keep the change focused and review the affected behavior.
2. Run focused regressions and require the CI job set for the triggering event
   to pass for the exact candidate SHA, as specified below.
3. Use the existing production workflow and its host-side configuration,
   schema/migration, backup-key, and readiness checks.
4. Check the deployed receipt and the user flow affected by the change. Record
   known limitations as beta follow-up work.

## CI job contracts

The checked-in [CI workflow](../.github/workflows/ci.yml) uses two deliberate
job sets:

- A push to `main` runs the five-job release gate: backend lint/types/OpenAPI,
  frontend lint/types/tests/build, Compose validation, and backend test shards
  1 and 2. Successful CI for that exact push is the event that can trigger
  automatic production deployment.
- Pull requests and `workflow_dispatch` run the seven-job full matrix: the same
  five jobs plus Chrome browser regression shards 1 and 2. A manual full run is
  supplementary verification; it does not itself deploy production.

The host release verifier reads the policy marker from the exact tested workflow
file and requires the corresponding job set. A workflow without the fast-main
marker retains the seven-job contract. Do not remove or skip required checks to
meet a timing target.

The literal receipt status `Deployed — Formal Acceptance Pending` records that
the optional formal-acceptance bundle was not completed. It does not mean the
technical deployment failed or block the next beta iteration.

## When a change must stop

Stop or roll back a candidate when evidence shows a material issue in the
affected scope, including:

- required CI fails for the exact candidate;
- authentication, authorization, private-data access, audit integrity, or
  transactional business invariants regress;
- the application, a required worker, or a changed core workflow is unhealthy;
- configuration, schema, migration compatibility, or a live incident hold
  fails an existing technical deployment check; or
- a stateful or destructive operation lacks the maintenance and recovery steps
  required by the current deployment procedure.

An unrelated open acceptance item, optional browser/device exercise, unsigned
business sample, or missing governance document is not by itself a blocker for
an otherwise safe beta feature release. An issue that directly affects the
changed workflow remains in scope and must be addressed or explicitly accepted
through the applicable existing authority.

## Stateful and security-sensitive changes

Beta cadence does not authorize bypassing production controls. Database
migrations, PostgreSQL or object-storage changes, destructive maintenance,
incident reconciliation, changes to ingress or secrets, and other stateful
operations continue to use the technical checks and maintenance process in the
[operations runbook](OPERATIONS_AND_DEPLOYMENT.md). Keep evidence, receipts,
backups, and rollback material truthful and preserve historical records.

Chrome browser regression runs in the pull-request and manual full-regression
job set. It is not part of the five-job push gate. Additional browser,
physical-device, independent-recovery, monitoring, business-template, or extended
UAT evidence is collected when the changed risk or an owner-requested
acceptance exercise calls for it; it is not a universal beta release gate.

## Status and scope

The beta may be deployed to the internal production environment. Do not call it
generally available or claim formal business acceptance unless those facts are
separately verified. Keep known limitations and decisions in the owning guide,
and use [post-release actions](POST_RELEASE_ACTIONS.md) as an optional follow-up
ledger rather than a deployment authorization checklist.
