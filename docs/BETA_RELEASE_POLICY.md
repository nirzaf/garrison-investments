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

An explicit owner request to release authorizes the routine beta workflow,
including automatic deployment after push CI. No separate codeword or manual
approval stage is required. Use the routine path for application changes and
forward-compatible migrations supported by the installed launcher.

1. Keep the change focused and review the affected behavior.
2. Run focused regressions and require the applicable push CI jobs to pass for
   the exact candidate SHA.
3. Use the existing production workflow and its host-side configuration,
   schema compatibility, recovery-hold, and readiness checks.
4. Check the deployed receipt and the user flow affected by the change. Record
   known limitations as beta follow-up work.

The literal receipt status `Deployed — Formal Acceptance Pending` records that
the optional formal-acceptance bundle was not completed. It does not mean the
technical deployment failed or block the next beta iteration.

## Iterate from user feedback

Review the [Super Admin feedback inbox](LOGGING_AND_REMOTE_CLI.md#user-feedback-and-triage)
for reproducible issues. Use the report's request references and timestamps to
investigate within authorized logs. Add a focused regression for the failure,
then track the report through the verified release before resolving it.

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

Beta cadence does not authorize bypassing production controls. PostgreSQL major upgrades, object-storage changes, destructive maintenance,
incident reconciliation, changes to ingress or secrets, and other stateful
operations continue to use the technical checks and maintenance process in the
[operations runbook](OPERATIONS_AND_DEPLOYMENT.md). Keep evidence, receipts,
backups, and rollback material truthful and preserve historical records.

The existing Chrome CI suite is the routine browser gate. Additional browser,
physical-device, independent-recovery, monitoring, business-template, or extended
UAT evidence is collected when the changed risk or an owner-requested
acceptance exercise calls for it; it is not a universal beta release gate.

## Status and scope

The beta may be deployed to the internal production environment. Do not call it
generally available or claim formal business acceptance unless those facts are
separately verified. Keep known limitations and decisions in the owning guide,
and use [post-release actions](POST_RELEASE_ACTIONS.md) as an optional follow-up
ledger rather than a deployment authorization checklist.
