# Operations and Deployment Guide

[Documentation index](README.md) · [Architecture](ARCHITECTURE.md) · [Staging](../STAGING_DEPLOYMENT.md) · [Logging and alerts](LOGGING_AND_REMOTE_CLI.md)

Use [production CD](#production-deployments-from-github-actions) for routine releases, the [maintenance procedure](#production-maintenance) for database or stateful changes, and [post-deploy verification](#post-deploy-verification) for live checks and first-administrator setup. [Backup and restore](#3-operations-backup--restore) and [launch evidence](#5-launch-evidence-capture--sign-off) cover recovery and sign-off.

## Environment and configuration

| Environment | Source of truth | Entry point |
| --- | --- | --- |
| Development | [Local Compose](../docker-compose.yml) and [.env.example](../.env.example) | [Getting started](../README.md#getting-started) |
| Staging | [Staging Compose](../docker-compose.staging.yml) and private `.env.staging` | [Staging runbook](../STAGING_DEPLOYMENT.md) |
| Production | [Production Compose](../docker-compose.prod.yml), host override, and private environment file | [portal.garrisons.lk](https://portal.garrisons.lk) |

Use Docker with Compose v2. Keep production configuration and secrets on the host with restricted permissions. See [backend settings](../backend/app/config.py) and the matching Compose file for variable names, defaults, and service overrides.

| Concern | Configuration to check |
| --- | --- |
| Environment and URLs | `APP_ENV=production`, `DEBUG=false`, `FRONTEND_BASE_URL`, and the allowed origins in `BACKEND_CORS_ORIGINS`. |
| Database and queue | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`, and `REDIS_URL` must identify the environment's private services. URL-encode credentials embedded in URLs. |
| Signing keys | Mount the matching RSA private/public files at `JWT_PRIVATE_KEY_PATH` and `JWT_PUBLIC_KEY_PATH`. Production startup validates the configured signing keys. |
| Public ingress | Configure DNS and TLS for the portal and `GRAFANA_DOMAIN`. The host override supplies the production certificate mount. For a standalone Compose setup, the base file mounts `nginx/ssl/`. |
| Object storage | Use the internal `MINIO_ENDPOINT` for the backend and the public portal authority in `MINIO_PUBLIC_ENDPOINT` with `MINIO_PUBLIC_SECURE=true` for browser URLs. Route `/portal-files/` through Nginx and preserve the original `Host`, including any non-default port. Both checked-in Nginx configs use `$http_host` on this route. |
| Proxy trust | Base production Compose trusts loopback and the Nginx address from `NGINX_BACKEND_PROXY_IP`. When resolving Docker subnet overlap, adjust `NGINX_BACKEND_PROXY_SUBNET`, `NGINX_BACKEND_PROXY_DYNAMIC_RANGE`, and `NGINX_BACKEND_PROXY_IP` together. Review the ingress trust configuration when adding a proxy hop. |
| Application email | Set `SMTP_FROM_EMAIL` to the authorized sender. For SMTP, `SMTP_FROM_NAME` controls the message display name. The useSend API payload supplies the sender address, so verify the display name at the provider. [EmailService](../backend/app/services/email_service.py) selects useSend when either `USESEND_API_URL` or `USESEND_API_KEY` is present, so configure the pair together. Confirm receipt of a real OTP after changing mail settings. |
| Recovery and alerting | Set `BACKUP_ENCRYPTION_PASSWORD`, the Grafana administrator and database credentials, and the Loki object-store service credentials. See [alert delivery](LOGGING_AND_REMOTE_CLI.md#alert-delivery) for Grafana-specific settings. |

Compose defaults to digest-pinned Silo and its S3 client for new installations. Existing hosts may set `OBJECT_STORAGE_IMAGE` and `OBJECT_STORAGE_CLIENT_IMAGE`. Treat a provider or image change as stateful maintenance. Verify application objects, backup retrieval, and Loki reads on an isolated copy, and retain the original volume and image for rollback.

## Production deployments from GitHub Actions

[CI](../.github/workflows/ci.yml) uses GitHub-hosted runners for pull requests and pushes to `main`. [Deploy production](../.github/workflows/deploy.yml) is a separate workflow in the `Production` environment. It accepts a successful same-repository `main` push from CI and runs on the dedicated self-hosted runner labeled `garrison-production`. GitHub concurrency and a host lock serialize releases.

If the approval bundle becomes available after CI, dispatch `deploy.yml` from `main` with `ci_run_id` set to the original successful CI run ID. The host verifies the same CI run, current `main` SHA, active deployment run and approval bundle. It checks separation of duties against the deployment run's verified operator. This preserves the job IDs already recorded in the bundle.

The workflow invokes the installed [host release script](../deploy/hostinger-release.sh). The script verifies the CI run and current `main` SHA through GitHub and requires approved evidence before fetching the candidate. After building the exact revision, it compares the image identities, Alembic heads and frontend hashes with the authorization. For runtime changes it also checks protected resources and runs the application and Grafana backup command in a one-off container before activation. It swaps the frontend index atomically, verifies the served sign-in HTML, JavaScript and service worker hashes, and checks public readiness. A successful release advances the `current` link and records the commit, CI run, UTC timestamp, and hashes in `DEPLOYED`. Failed activations follow the [rollback procedure](#rollback).

### Review pipeline time on every release

Compare the exact candidate's Actions run with recent runs that cover the same tests. Record queue time, elapsed CI time, the slowest job and steps, cache hits, and total runner time. Pytest reports its ten longest tests and the browser jobs log individual test durations. Look for independent work to run in parallel, repeated setup, and avoidable rebuilds. Record a measured result after each change and confirm the same required checks and test coverage ran.

The backend suite and Chromium browser suite each run in two shards with separate PostgreSQL, Redis and object storage services. Each job starts its pinned Moto container alongside dependency installation and applies migrations to its own database before testing. Each Chromium shard runs two workers on separate test files with synthetic accounts and projects. The browser jobs type-check the browser tests and build the production bundle. The required frontend job type-checks the application. Each test belongs to exactly one shard. Local `pytest` and `npm run test:browser` still run the full suites by default. The release receipt requires success from all four shards.

Backend sharding assigns whole test modules using measured runtimes for the slowest modules and case counts for the rest. If shard timings diverge across comparable runs, sum JUnit case times by module from both backend reports before adjusting the estimates in [the pytest configuration](../backend/tests/conftest.py).

For deployment, measure time awaiting approval or a runner separately from the phase timings in the host release log. Reuse the reviewed, SHA-tagged staging images when available. The host checks their image IDs and served hashes against the exact release authorization before activation. An edit limited to the backend architecture guide can reuse the running backend image. The release script reads the frontend image hashes in one container before checking the served bytes after activation.

### Host bootstrap and runner maintenance

Provision the existing stack and an initial active release before registering the production runner. The script expects the project `garrison-portal`, an active release under `/opt/garrison-portal/releases/`, and the `garrison-portal_frontend_dist` volume. Under `/opt/garrison-portal/deploy/`, keep the following root-controlled.

| Host item | Purpose |
| --- | --- |
| `production.env` | Private configuration copied into each candidate release. |
| `compose.vps.yml` | Existing stateful resource names, TLS and key mounts, and host-specific overrides. |
| `current` | Link to the last verified release containing `.env`, `.images.env`, `SOURCE_COMMIT`, and its deployment receipt. |
| `deploy.lock` | Host-side serialization across release attempts. |
| `authorizations/<sha>/release_manifest.json` | Restricted, source-bound predeployment evidence and approvals with artifacts under the same release directory. |
| `approval-trust.json` | Root-controlled registry of independently verified approval artifacts, outside the candidate and evidence bundle. |
| `authorized-configuration.json` | Approved configuration digest and protected input hashes, including `production.env` and `compose.vps.yml`. |

Before activation with `rollback-v2 release-contract-v1`, the authorized host operator installs the reviewed [verifier](../backend/scripts/release_contract.py) at `/usr/local/libexec/garrison-release-contract.py` and the [release script](../deploy/hostinger-release.sh) at `/usr/local/sbin/garrison-deploy`. Keep both root-owned and protected from runner writes. The operator verifies the actual approval provenance before adding registry entries. The runner account needs only noninteractive `sudo` for the release script. Older installed scripts reject the four-argument protocol before activation.

On the VPS, use this Bash helper from an authorized operator session to target the active production project. Define it again after a release advances `current` so the file paths follow the new release.

```bash
state=/opt/garrison-portal/deploy
release=$(readlink -f "$state/current")
prod() {
  docker compose --project-name garrison-portal --project-directory "$release" \
    --env-file "$release/.env" --env-file "$release/.images.env" \
    -f "$release/docker-compose.prod.yml" -f "$state/compose.vps.yml" "$@"
}
```

### Production maintenance

Pending Alembic revisions and changes to PostgreSQL, Redis, the S3 service, its initializer, the Grafana database initializer, Compose volumes, or networks require a reviewed maintenance window. Production CD blocks those changes before activation. A change in rollback generation also requires a maintenance window so incompatible clients and scheduled writers are quiesced before switching.

1. Identify the candidate SHA, successful CI run, deployed SHA, current database revision, and affected volumes. Review the migration, data repair prerequisites, and compatibility with the running application. Rehearse the exact change against an isolated restore.
2. Record the backup object names and tested recovery plan. The pre-activation database backup uses `--skip-retention` to preserve existing backups. It supplements the independently verified database and file recovery set. Coordinate with the deployment operator so routine CD and maintenance cannot overlap. Quiesce affected writers when the change requires a consistent database or object snapshot.
3. Apply the approved migration or infrastructure change using the candidate's images and the host override. Compare the resulting Alembic revision and persistent resource layout with the plan before resuming writes.
4. Verify health, data and permissions, relevant background jobs, and the affected browser workflow. Capture the deployment and restore evidence. If a rollback needs data recovery, account for writes after the recovery point before reopening traffic.

For the first owner-aware offline rollout, stop the previous Celery beat and worker and drain active application writes before migration. Keep an ingress write block in place through activation and the read-only smoke checks. The deployment probe needs GET access to the sign-in page, frontend entry asset, service worker, and readiness endpoint. Remove the block after verifying the new application and worker and confirming no legacy writers are running.

### Upgrade an existing PostgreSQL 16 database

Fresh volumes initialize with PostgreSQL 18.6. Existing PostgreSQL 16 data requires a major-version migration. The PostgreSQL 18 image mounts `pgdata` at `/var/lib/postgresql`.

1. Record the Compose project, source volume, and deployed revision. Stop application, worker, and Grafana writes for the final cutover. With PostgreSQL 16 available, take and verify application and Grafana dumps and capture the roles and grants needed for restore.
2. Create a fresh PostgreSQL 18 volume and set `volumes.pgdata.name` in the environment's Compose override. Use that override and the same Compose project throughout the rollout.
3. Start PostgreSQL 18, provision the roles and empty databases, and restore both dumps using PostgreSQL 18 client tools with SQL errors fatal.
4. Compare the Alembic revision, representative records, and permissions, then verify the app and Grafana before resuming writes. Keep the prior volume and backups. Before writes resume, the prior runtime can return to its original volume. Later rollback requires reconciling new data.

### Post-Deploy Verification

On the production host, with the [active Compose helper](#host-bootstrap-and-runner-maintenance) defined:

```bash
cat "$release/DEPLOYED"
prod ps --all
curl --fail --silent --show-error https://portal.garrisons.lk/health
curl --fail --silent --show-error https://portal.garrisons.lk/health/readiness
```

Compare the receipt with the GitHub run and the intended SHA. The API readiness endpoint checks PostgreSQL connectivity. Check the queue, storage, and background jobs separately when the release affects them. Confirm the one-shot `grafana_db_init` and `loki_minio_init` jobs completed successfully when the stack was initialized or those jobs were rerun. If one fails, inspect its logs before starting dependent services. Verify Grafana `/api/health` through its configured HTTPS hostname. Test a fresh authenticated object preview and download if the release affects ingress or storage. For app changes, exercise the affected business workflow in the permitted environment and record the result.

On an empty production database after the schema is ready, create the approved first administrator in an interactive host terminal:

```bash
prod exec backend python scripts/bootstrap_admin.py \
  --email admin@example.com --full-name "Portal Administrator"
```

The command prompts for a temporary password and the account must change it after sign-in. Use the approved administrator address and confirm that it receives and can use a login OTP from the configured sender.

### Local production Compose rehearsal

Run the [repository verification commands](../README.md#verification) for the affected code. For configuration-only changes, render the production Compose model from the repository root:

```bash
docker compose --env-file .env.example -f docker-compose.prod.yml config --quiet
```

For a runtime rehearsal, use a scratch checkout with a unique Compose project, loopback-only host ports, test-only configuration, signing keys, and a TLS certificate for the test hostname. Start PostgreSQL, run `alembic upgrade head` in the backend image, then bring up the full stack. Keep the project, environment files, and overrides consistent across commands. Verify the SPA, readiness, and a fresh signed preview inside the same-origin iframe.

## 3. Operations, Backup & Restore

### Scheduled jobs

The [Celery Beat schedule](../backend/app/tasks/celery_app.py) is the source of truth. All listed times are UTC.

| Cadence | Jobs |
| --- | --- |
| Every minute | Dispatch the task outbox for report exports. |
| Hourly | Check late reports and low stock, and process approval reminders. |
| Daily | Database backups at 01:00, notification cleanup at 03:00, log archival and purge at 03:30, and supplier TDS expiry checks at 04:00. |
| First day of the month at 02:00 | Monthly database backups. |

### Backup and restore

[backup.py](../backend/scripts/backup.py) creates encrypted PostgreSQL dumps for the application and Grafana and writes them to the configured S3 bucket. Daily application backups use `backups/daily/` and monthly backups use `backups/monthly/`. Grafana backups use `backups/grafana/daily/` and `backups/grafana/monthly/`. The default retention is 30 days for daily backups and 12 months for monthly backups. The application upload bucket and Loki operational log data require their own recovery decisions.

Run a backup on demand through the active Compose helper:

```bash
prod exec -T backend python scripts/backup.py --target all
```

Add `--monthly` for the monthly prefix. Record both uploaded object names. To prove recovery, download both encrypted objects to a restricted working directory, decrypt each to a `.sql.gz` file using the configured secret and `openssl enc -d -aes-256-cbc -pbkdf2`, and restore to separate empty databases in an isolated PostgreSQL instance. Prepare roles referenced by the dumps as `NOLOGIN` roles where appropriate. Verify the application schema and representative records and check Grafana's restored metadata. Keep the recovery exercise separate from production data and credentials.

[restore_dry_run.py](../backend/scripts/restore_dry_run.py) inspects a decrypted plain SQL or gzip SQL dump, records its hash, and can execute the restore using `psql` with fatal SQL errors. From a prepared backend environment with the disposable database URL in `RESTORE_DATABASE_URL` and a securely stored decrypted dump:

```bash
cd backend
python scripts/restore_dry_run.py \
  --backup-file /path/to/decrypted-backup.sql.gz \
  --output /path/to/recovery-evidence.md
```

Check for `Restore status: executed` in the evidence. With no restore database URL, the receipt is `validated-only`. Include the backup object name, timestamp, operator, target isolation, and verified results with the receipt.

### Independent database and file recovery drill

Agree on the backup destination, key custodian, retained evidence, recovery point and recovery time targets before accepting a release. Use a destination that remains accessible if the portal host and its object storage are unavailable. Keep the manifest private because it includes object identifiers. Store deployment configuration and keys through the approved recovery procedure.

[The backup-set tool](../backend/scripts/backup_set.py) captures the application database and required files. It reads database references from the same PostgreSQL snapshot as the dump. The set includes active and superseded document versions, report PDFs, current invoice and supplier attachments, and photo originals and generated variants for active and recoverable records. If policy retains replaced attachment objects, supply their keys from the approved inventory with `--extra-objects`. Supply `BACKUP_GRAFANA_DATABASE_URL` in the private environment to include the Grafana database. Capture during a recorded write pause that also covers the object store and any Grafana database included in the set.

From the authorized backend environment, set `BACKUP_ENCRYPTION_PASSWORD` privately. Create a new set directory on the approved destination and verify its encrypted artifacts.

```bash
python -m scripts.backup_set capture \
  --source-sha "$RELEASE_SHA" \
  --consistency-note "$WRITE_PAUSE_EVIDENCE" \
  --destination /private/independent-storage/backup-set
python -m scripts.backup_set verify /private/independent-storage/backup-set
```

The `verify` command checks artifact presence, size and SHA-256. For a recovery exercise, mount the set in a disposable environment with its own empty PostgreSQL databases and new object bucket. Configure `RESTORE_DATABASE_URL`, optional `RESTORE_GRAFANA_DATABASE_URL`, `RESTORE_OBJECT_ENDPOINT`, `RESTORE_OBJECT_BUCKET`, `RESTORE_OBJECT_ACCESS_KEY`, and `RESTORE_OBJECT_SECRET_KEY` privately. The tool accepts only loopback PostgreSQL databases named `garrison_restore_test_*` and a new loopback bucket named `garrison-restore-test-*`. Disable outbound mail and scheduled business jobs in the restored application.

For the approved D-29 recovery policy, pass `--policy "$RECOVERY_POLICY"` when capturing, publishing, fetching and restoring a format 2 set. Supply `BACKUP_AUTH_KEY_FILE` and `BACKUP_AUTH_KEY_ID` through the operator's restricted environment, separately from the backup encryption password. The independent destination uses its approved `DR_BACKUP_*` settings and separate publisher and reader credentials. Publish with `python -m scripts.backup_set publish "$LOCAL_SET" --policy "$RECOVERY_POLICY" --receipt "$PUBLICATION_RECEIPT"`. The publisher verifies the remote encrypted artifacts before it writes the signed completion record. A substitute operator can fetch a complete set with `fetch "$BACKUP_SET_ID" --policy "$RECOVERY_POLICY" --destination "$ISOLATED_SET"` and then restore it with `--require-authenticated`. Retain the existing format 1 sets for historical recovery and record their checksum-only assurance.

The [scheduled capture service](../deploy/backup-set.service) invokes the [capture wrapper](../deploy/capture-recovery-set.sh) under the same host lock as deployment. Set `RECOVERY_POLICY`, `RECOVERY_CAPTURE_TEMPLATE`, `RECOVERY_CAPTURE_ENV`, `RECOVERY_PUBLISH_ENV`, and the two authentication key variables in the root-owned scheduler environment. Set `RECOVERY_CONFIGURATION_ROOT` to a dedicated root-owned directory containing only the approved nonsecret recovery configuration. Keep the policy, capture inventory, credentials and authentication key outside that directory. Install the service and wrapper only after exercising the write pause and recovery against the approved destination. Choose the timer interval from the approved recovery point target and measured capture duration.

The wrapper uses one private `.scheduled-capture` workspace under `/opt/garrison-portal/recovery/scheduled/`. It removes that workspace after verified publication and writer recovery. When publication fails after writers resume, the next run retries the same signed set before creating another capture. If its publication deadline has passed, the active release changed, or writer recovery is unverified, review `last-attempt.json` and resolve the pending set with the recovery operator. Review historical `capture-*` directories separately before reclaiming their disk space.

The scheduler signs and publishes `last-scheduled-attempt.json` to the approved recovery prefix after writer recovery. The publisher needs write and readback access to this status object, and the independent monitor needs read access. Verify the first scheduled attempt record before switching the monitor. A failed attempt can trigger an alert while the previous successful set is still within the recovery point objective. If status publication fails, the scheduler exits with a failure and keeps the local `last-attempt.json` for investigation. Only a verified complete set advances backup freshness.

When rotating the authentication key or changing the policy revision, use a new approved destination prefix. Keep the previous prefix and escrow the exact policy bytes, key ID, authentication key and decryption material until the retained sets expire. Verify a complete set under the new policy before changing the monitor. Preview expired sets with the separate retention command; apply only the reviewed plan using authorized retention credentials.

```bash
python -m scripts.backup_set restore /private/independent-storage/backup-set
```

The restore checks decrypted bytes before writing and checks the resulting schema, database references, and restored object checksums. Start the isolated application and open the required protected files under authorized and forbidden accounts. Include the backup set identity, source SHA, schema head, UTC timings, missing or corrupt artifact tests, key access, and actual recovery results in the release evidence. Local fixtures establish tool behavior. The release still requires a drill with the approved destination, retained data scope, operator, and measured targets.

### Data checks and repairs

| Case | Operator action |
| --- | --- |
| Import source shape | Use the [import validation guide](import_templates/README.md). If using a backend container, mount the templates at `/docs/import_templates` or pass the source explicitly. |
| Historical invoice overpayments | Run `prod exec -T backend python scripts/report_payment_overages.py --i-understand`. Use the read-only output to reconcile payments with Finance. |
| Duplicate offline drafts | Run `prod exec -T backend python scripts/repair_offline_duplicates.py --i-understand` to list candidates. Consolidation requires a maintenance window, a reviewed pair, and `--apply --keep <uuid> --duplicate <uuid>`. The script moves photo and retry references and soft-deletes the duplicate in one transaction. |
| Inventory reservation drift | Run `prod exec -T backend python scripts/report_inventory_reservation_drift.py --i-understand` to compare recorded balances with the derived reservations and find cancelled requests that still have open approvals or reserved lines. Review findings with Inventory before authorizing repairs. Migration `202605300003` repairs derived reservations and validates existing stock constraints. Reconcile any legacy negative on-hand values before retrying a migration blocked by that constraint. |
| Legacy supervisor verification | Once read-only inspection is authorized, run `prod exec -T backend python scripts/report_supervisor_verification.py --i-understand`. Review unresolved verification bindings and their candidate counts with the workflow owner. |
| Legacy photo quota overages | Once read-only inspection is authorized, run `prod exec -T backend python scripts/report_media_quota_drift.py --i-understand`. Review the report and supervisor update IDs and active-photo counts with the records owner. The scan excludes deleted photos and attachments. |

### Offline storage upgrade

The owner-aware worker upgrades the portal's IndexedDB to version 3. Have operators close older portal tabs and reopen the portal on the new build. Confirm the active worker has upgraded before testing account switches on shared devices. Older workers cannot open version 3. A worker already running before activation can finish requests it already sent, so wait for the older clients to close before accepting the rollout. Keep the owner-aware worker during rollback or disable offline sync until a compatible build is ready.

The old `reportDrafts` and `photoQueue` stores and the `garrisons.supervisor-update-draft` local storage entry are quarantined. The app leaves them unread because ownership cannot be established from their keys. If the owner authorizes disposal, remove only these legacy entries for the portal origin after confirming that no older clients remain. Keep the owned stores and session state intact.

Apply the report revision migration before activating the report API and frontend together. Report creation with a `local-*` idempotency key requires an `X-Offline-Owner` header matching the authenticated user. A report edit without `expected_revision`, or a keyed single-file daily-report upload without `expected_report_revision`, returns a conflict and asks the user to reload. These checks apply before replaying a previous result. Keep revision fields on rollback, and use only workers that verify ownership and preserve revision checks.

### Rollback

Automatic rollback requires matching [rollback generations](../deploy/rollback-generation), previous backend Alembic heads that match the live database, and the retained frontend image. Generation 1 requires the owner-aware service worker, report revision enforcement, and deadline-aware audit retention. Generation 2 also requires the policy checks and safeguards for legacy audit records. Keep destructive purge disabled during the switch. Change the generation when a release invalidates the previous release's ability to use the same data and client state safely.

If a compatible rollback runs, verify readiness and the served assets against the previous release receipt. If no compatible rollback exists, the script records `ACTIVATION_FAILED` under the candidate release, stops Nginx and the application writers, and leaves `current` pointing at the last verified release. Keep the maintenance write block in place, verify that ingress and writers are stopped, and reconcile actual containers and static assets before activating a compatible forward fix. The failure receipt can exist even if the application or static assets were partly switched.

For an authorized rollback after a successful release, apply the same generation and schema checks and use the same host override. If data recovery is required, follow the approved recovery plan and record the recovery point. Use the [container log fallback](LOGGING_AND_REMOTE_CLI.md#incident-fallback) if the observability stack is unavailable.

## User acceptance

Use sample data only in an approved non-production environment. Follow the [seed setup](../README.md#getting-started) and the [roles and permissions reference](ROLES_AND_PERMISSIONS.md). At launch or when affected, verify account creation, permission and project scope, daily report submission and review, document and photo access, signed previews, exports, and login mail. Include iOS Safari and Android Chrome when validating mobile capture and offline retries. Record the tested role, scenario, result, and any accepted issue.

## 5. Launch Evidence Capture & Sign-Off

Freeze the source SHA and approved configuration. Collect the signed scope, retention, recovery, operations, device/support and business decisions together with executed control receipts. Use the [unsigned release templates](templates/release-closure/README.md) and keep sensitive evidence private. Record the operator and approvers as separate roles and have the trusted reviewer verify the actual approvals before populating the approval registry.

Run strict predeployment validation against the frozen bundle before activation:

```bash
cd backend
python scripts/launch_evidence.py --target production --commit "$RELEASE_SHA" \
  --manifest "$RELEASE_MANIFEST" --evidence-root "$PRIVATE_EVIDENCE_ROOT" \
  --trust-registry "$APPROVAL_TRUST_REGISTRY" --phase predeploy --validate-only \
  --output "$PREDEPLOY_REPORT" --json-output "$PREDEPLOY_VERDICT"
```

After deployed readback, live checks, the approved observation cycle, and final owner acceptance, run the same command with `--phase final` and separate verdict paths. Only the final successful verdict can certify the frozen scope. The existing collection command below remains useful for a draft evidence summary.

[launch_evidence.py](../backend/scripts/launch_evidence.py) checks the supplied URLs and records hashes for attached evidence files. Run it from a trusted checkout using private output paths and the actual release values:

```bash
cd backend
python scripts/launch_evidence.py --target production \
  --output /path/to/private/production-launch.md \
  --health-url https://portal.garrisons.lk/health \
  --readiness-url https://portal.garrisons.lk/health/readiness \
  --commit "$RELEASE_SHA" --run-url "$DEPLOY_RUN_URL" --approver "$APPROVER" \
  --backup-object "$APPLICATION_BACKUP_OBJECT" \
  --restore-log /path/to/private/restore-evidence.md \
  --uat-signoff /path/to/private/uat.md
```

The script records the supplied backup object name. Attach the Grafana backup reference and the actual restore results to the sign-off record.
