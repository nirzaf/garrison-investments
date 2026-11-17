# Support identity and case evidence

The support schema is additive and has no production operator grants. Models live in [support identity](../../backend/app/models/support_identity.py),
[case access](../../backend/app/models/support_cases.py),
[custody](../../backend/app/models/support_custody.py), and
[oversight and backup receipts](../../backend/app/models/support_oversight.py).

| Tables | Purpose |
| --- | --- |
| `support_operators`, `support_credentials` | Separate technical identities with status and grant epoch. Credentials hold a unique credential digest, public key, signature counter and revocation time. |
| `support_login_challenges` | Two-minute single-use assertions tied to one operator and grant epoch. |
| `support_email_otps` | One email verification per accepted passkey challenge. Stores a keyed code digest, transport acceptance, expiry, failed-attempt count and use time. |
| `support_sessions` | Digests of opaque session and CSRF values. Absolute expiry is 60 minutes, idle expiry is 15 minutes, and revocation or an epoch mismatch denies access. |
| `support_operator_grants`, `support_cases`, `support_case_members`, `support_case_requests` | Case authorization intersects a live operator grant, case state, membership and an explicitly linked source request. |
| `support_custody_actions`, `support_custody_proofs`, `support_custody_events` | Independently reviewed suspension and capability changes, session- and stage-bound proofs, and append-only custody decisions. |
| `support_registrations` | Two one-use invitation digests per reviewed enrollment or recovery, with proof expiry and consumption state. |
| `support_case_actions`, `support_case_action_proofs`, `support_case_action_events` | Revision-bound proposals, session-bound passkey proofs and immutable applied decisions for scope, evidence verification and closure. |
| `support_case_projects` | Independently reviewed project references currently in case scope. |
| `support_bootstrap`, `support_bootstrap_events` | Single approved inaugural custodian pair, activation receipt and append-only enrollment audit. |
| `support_case_subjects`, `support_directory_reads` | One independently approved account per case and append-only reads of its masked projection. Account history survives source deletion. |
| `support_business_actions`, `support_business_approvals`, `support_business_proofs`, `support_business_events` | Immutable case-bound business authentication proposals, independent decisions, one-use proofs and applied audit. |
| `support_business_contacts` | Append-only attestations of offline owner contact. Only an eligible custodian can record one with a fresh proof bound to the exact action and opaque evidence reference. |
| `support_recovery_deliveries` | One durable delivery row per applied recovery proposal. References the opaque reset challenge, tracks acceptance separately from the user's password-reset completion, and stores no reset code or email address. |
| `support_case_audit_reads` | Bounded assigned-case audit disclosures and filter timestamps. |
| `support_permission_views`, `support_permission_view_events` | Case-bound permission view lease tied to the requesting technical session. Opening, reading and ending the view append an audit record. |
| `support_health_events` | Append-only diagnostic requests and disclosures, with technical operator and correlation identifiers. |
| `support_case_events` | Append-only case creation, member reads and revisioned triage events. |
| `support_auth_events`, `support_log_reads` | Append-only sign-in decisions and evidence reads. PostgreSQL blocks row changes, deletion and truncate. |
| `support_log_streams` | Technical session, case and request scope for each live evidence connection. Stores open, expiry and close timestamps. |
| `support_evidence_exports`, `support_evidence_proofs` | Immutable case, linked request, filters and SHA-256 with independent approval and one-use download. Only proof and receipt metadata are retained. |
| `support_oversight_events` | Append-only disclosure and per-operator read rate-limit events (`surface`, `action`, optional `case_id`, `request_id`, `occurred_at`). Triggers block updates, deletes and truncate. |
| `support_backup_receipts` | Append-only attested backup and restore-drill receipts (`receipt_kind`, `backup_set_id`, `manifest_sha256`, `target_domain`, `outcome`, `rpo_minutes`, `rto_minutes`, `captured_at`, `verified_at`, `signer_key_id`, `recorded_by`) without host paths or object keys. |

[Revision 063](../../backend/alembic/versions/202605310063_support_identity.py)
adds the operator realm and [revision 064](../../backend/alembic/versions/202605310064_support_case_logs.py)
adds case access and audit protections.
[Revision 065](../../backend/alembic/versions/202605310065_support_suspensions.py)
adds suspension and the `operator.manage` capability.
[Revision 066](../../backend/alembic/versions/202605310066_support_case_triage.py)
adds case metadata, revision checks, member lookups and the `cases.manage`
capability. Existing case-evidence rows retain their previous visibility.
[Revision 067](../../backend/alembic/versions/202605310067_support_reviewed_grants.py)
renames the custody tables without rewriting their evidence and adds bounded
grant changes. Keep support ingress disabled if rolling back to code written
before the rename.
[Revision 068](../../backend/alembic/versions/202605310068_support_registration.py)
adds reviewed enrollment and recovery invitations.
[Revision 069](../../backend/alembic/versions/202605310069_support_health.py)
adds restricted, audited health checks.
[Revision 070](../../backend/alembic/versions/202605310070_support_case_actions.py)
adds reviewed case actions.
[Revision 071](../../backend/alembic/versions/202605310071_support_directory.py)
adds reviewed account scope and protects the applied action payload.
[Revision 072](../../backend/alembic/versions/202605310072_support_timeline.py)
adds append-only timeline reads to case audit.
[Revision 073](../../backend/alembic/versions/202605310073_support_business_actions.py)
adds reviewed business authentication actions.
[Revision 074](../../backend/alembic/versions/202605310074_support_case_audit.py)
adds separate, audited access to redacted case audit.
[Revision 075](../../backend/alembic/versions/202605310075_support_account_lifecycle.py)
adds reviewed disable and reactivation actions.
[Revision 076](../../backend/alembic/versions/202605310076_support_permission_views.py)
adds independently reviewed role permission explanations.
[Revision 077](../../backend/alembic/versions/202605310077_support_contact_proof.py)
binds the offline receipt reference to the protected review proof.
[Revision 078](../../backend/alembic/versions/202605310078_recovery_destination_verification.py)
adds nullable keyed email bindings on login challenges and the corresponding
verification digest and timestamp on business users. It leaves existing
addresses unverified until successful email OTP sign-in. Apply the schema
before starting code that reads the new columns.
[Revision 079](../../backend/alembic/versions/202605310079_support_recovery_issuance.py)
binds reviewed recovery to one verified destination and queues the
opaque challenge reference.
[Revision 080](../../backend/alembic/versions/202605310080_support_recovery_delivery.py)
adds dispatch timestamps and records accepted, unknown and cancelled
transport outcomes. An interrupted attempt is kept for operator review.
[Revision 081](../../backend/alembic/versions/202605310081_support_recovery_status_audit.py)
adds the append-only recovery status disclosure event.
[Revision 082](../../backend/alembic/versions/202605310082_support_request_summary.py)
adds one opaque reviewed event reference to request-summary proposals and
reuses the session-bound support view lease and disclosure audit.
[Revision 083](../../backend/alembic/versions/202605310083_support_navigation_view.py)
allows navigation proposals under the same lease and audit rules, with no
permission key, recovery destination or linked source event.
[Revision 084](../../backend/alembic/versions/202605310084_support_case_projects.py)
adds a project reference to the immutable case action receipt and records
the current case project scope keyed by case and project.
[Revision 085](../../backend/alembic/versions/202605310085_support_project_views.py)
binds a project list to the reviewed visible-set digest and a project detail
view to an exact case project reference. Both reuse the short, audited lease.
[Revision 086](../../backend/alembic/versions/202605310086_support_bootstrap.py)
adds the singleton initial custody receipt and its audit events. A
registration invitation belongs to either a reviewed custody action or a
pending initial custodian. The migration creates no operator accounts.
[Revision 087](../../backend/alembic/versions/202605310087_support_cli_login.py)
adds nullable commitments for a CLI challenge's session, CSRF and pairing
values. The ordinary browser sign-in challenge remains compatible. The CLI
binding is single-use and expires with the existing passkey challenge.
[Revision 088](../../backend/alembic/versions/202605310088_support_cli_proofs.py)
adds `support_cli_proofs`, a relay tied to an existing reviewed-action
challenge and its technical session. It stores a public encryption key and
an optional sealed assertion. Collection clears the sealed value and records
the one-time read. Expired relay records cannot deliver assertions.
[Revision 089](../../backend/alembic/versions/202605310089_support_email_otp.py)
adds the second sign-in step for the dedicated technical portal and CLI.
[Revision 090](../../backend/alembic/versions/202605310090_support_log_streams.py)
adds the stored live-stream admission limit and connection history.
[Revision 091](../../backend/alembic/versions/202605310091_support_evidence_export.py)
adds reviewed export receipts, session-bound passkey proofs and the separate export grant.
[Revision 092](../../backend/alembic/versions/202605310092_business_log_streams.py)
adds `business_log_streams` to track and limit active business audit streams across workers.
[Revision 093](../../backend/alembic/versions/202605310093_support_oversight_and_receipts.py)
expands the capability check constraints for the 12 oversight/monitor grants,
creates append-only `support_oversight_events` and `support_backup_receipts`
tables with `prevent_support_audit_change()` triggers, and blocks `downgrade()`.
These revisions follow
the business session revision 062 and create no operator accounts or grants. Keep the schema and retained evidence
during application rollback. See the [operations runbook](../OPERATIONS_AND_DEPLOYMENT.md#super-admin-activation).
