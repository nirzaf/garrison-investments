# Operations and Deployment Guide

[Documentation index](README.md) · [Architecture](ARCHITECTURE.md) · [Logging and alerts](LOGGING_AND_REMOTE_CLI.md)

Use [production CD](#production-deployments-from-github-actions) for routine releases, the [maintenance procedure](#production-maintenance) for database or stateful changes, and [post-deploy verification](#post-deploy-verification) for live checks and first-administrator setup. [Backup and restore](#3-operations-backup--restore), [release closure](POST_RELEASE_ACTIONS.md), and [formal acceptance evidence](#5-launch-evidence-capture--sign-off) cover recovery and the evidence required for final acceptance.

## Environment and configuration

| Environment | Source of truth | Entry point |
| --- | --- | --- |
| Development | [Local Compose](../docker-compose.yml) and [.env.example](../.env.example) | [Getting started](../README.md#getting-started) |
| Production | [Production Compose](../docker-compose.prod.yml), host override, and private environment file | [portal.garrisons.lk](https://portal.garrisons.lk) |

The former staging deployment is retired and is not a deployment target or part of production acceptance. Its checked-in Compose and application compatibility settings are legacy references; CI retains a focused compatibility test for some of them.

Use Docker with Compose v2. Keep production configuration and secrets on the host with restricted permissions. See [backend settings](../backend/app/config.py) and the matching Compose file for variable names, defaults, and service overrides.

For formal acceptance, bind the production configuration to exact bytes without copying secrets into the evidence bundle. The profile at `/opt/garrison-portal/deploy/authorized-configuration.json` has a `files` map keyed by namespace: `host/` files resolve beneath the deployment state directory, `release/` files resolve beneath the exact candidate archive, and `external/` files resolve beneath `/opt/garrison-portal`. `configuration_sha256` is the SHA-256 of the canonical `files` map (sorted keys, compact separators, UTF-8, `ensure_ascii=False`). The trusted validator checks host and external bytes before predeployment authorization, checks the exact candidate config bytes after archive extraction, and compares every effective Compose bind mount before building or activating anything. It also rejects audit deletion being enabled. This release's required versioned runtime file set is shown in the [authorization profile template](templates/release-closure/authorized-configuration.json).

Generate a proposed profile from a restricted candidate directory on the production host. Extract the exact CI-tested source archive to a private temporary directory; do not use the active release as the candidate. The command below emits file names and hashes only. `docker compose config` output, which can contain resolved environment values, is piped directly to the validator and is not saved or printed:

```bash
state=/opt/garrison-portal/deploy
candidate=/opt/garrison-portal/recovery/config-review/<full-source-sha>
source_sha=<full-source-sha>
install -m 0600 "$state/production.env" "$candidate/.env"
printf 'GARRISON_FRONTEND_IMAGE=garrison-portal-release-frontend:%s\nGARRISON_BACKEND_IMAGE=garrison-portal-release-backend:%s\n' \
  "$source_sha" "$source_sha" > "$candidate/.images.env"
chmod 0600 "$candidate/.images.env"
docker compose --project-name garrison-portal --project-directory "$candidate" \
  --env-file "$candidate/.env" --env-file "$candidate/.images.env" \
  -f "$candidate/docker-compose.prod.yml" -f "$state/compose.vps.yml" \
  config --format json |
  python3 /usr/local/libexec/garrison-release-contract.py \
    --host-state "$state" --configuration-profile-root "$candidate"
```

Use a generated profile only after independently reviewing its paths against the actual service mounts. Put it in the root-owned protected host state after the separately reviewed trusted validator is installed; do not store secret values or their raw bytes in the evidence bundle. The validator requires the host environment and Compose override, the complete versioned runtime file set, JWT key files, and every file mounted from the pinned TLS directory. It rejects missing files, symlink substitution, extra/unapproved bind-mounted configuration, or any file whose bytes differ. Recompute and reapprove the digest whenever one of those files changes. Do not sign the older two-file digest: it does not cover effective runtime configuration.

| Concern | Configuration to check |
| --- | --- |
| Environment and URLs | `APP_ENV=production`, `DEBUG=false`, `FRONTEND_BASE_URL`, and the allowed origins in `BACKEND_CORS_ORIGINS`. |
| Database and queue | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`, and `REDIS_URL` must identify the environment's private services. URL-encode credentials embedded in URLs. |
| Signing keys | Mount the matching RSA private/public files at `JWT_PRIVATE_KEY_PATH` and `JWT_PUBLIC_KEY_PATH`. Production startup validates the configured signing keys. |
| Public ingress | Configure DNS and TLS for the portal and `GRAFANA_DOMAIN`. The host override supplies the production certificate mount. For a standalone Compose setup, the base file mounts `nginx/ssl/`. |
| Object storage | Use the internal `MINIO_ENDPOINT` for the backend and the public portal authority in `MINIO_PUBLIC_ENDPOINT` with `MINIO_PUBLIC_SECURE=true` for browser URLs. Route `/portal-files/` through Nginx and preserve the original `Host`, including any non-default port. Both checked-in Nginx configs use `$http_host` on this route. |
| Proxy trust | Base production Compose trusts loopback and the Nginx address from `NGINX_BACKEND_PROXY_IP`. When resolving Docker subnet overlap, adjust `NGINX_BACKEND_PROXY_SUBNET`, `NGINX_BACKEND_PROXY_DYNAMIC_RANGE`, and `NGINX_BACKEND_PROXY_IP` together. Review the ingress trust configuration when adding a proxy hop. |
| Application email | Set `SMTP_FROM_EMAIL` to the authorized sender. For SMTP, `SMTP_FROM_NAME` controls the message display name. The useSend API payload supplies the sender address, so verify the display name at the provider. [EmailService](../backend/app/services/email_service.py) selects useSend when either `USESEND_API_URL` or `USESEND_API_KEY` is present, so configure the pair together. Confirm receipt of a real OTP after changing mail settings. |
| Recovery and alerting | Set `BACKUP_ENCRYPTION_PASSWORD`, `DOCKER_SOCKET_GID` (`stat -Lc '%g' /var/run/docker.sock`), the Grafana administrator and database credentials, and the Loki object-store service credentials. See [Grafana, Loki, and Alloy](LOGGING_AND_REMOTE_CLI.md#grafana-loki-and-alloy) and [alert delivery](LOGGING_AND_REMOTE_CLI.md#alert-delivery) for collector and alerting settings. |

Compose defaults to digest-pinned Silo and its S3 client for new installations. Existing hosts may set `OBJECT_STORAGE_IMAGE` and `OBJECT_STORAGE_CLIENT_IMAGE`. Treat a provider or image change as stateful maintenance. Verify application objects, backup retrieval, and Loki reads on an isolated copy, and retain the original volume and image for rollback.

## Production deployments from GitHub Actions

[CI](../.github/workflows/ci.yml) uses GitHub-hosted runners for pull requests and pushes to `main`. [Deploy production](../.github/workflows/deploy.yml) is a separate workflow in the `Production` environment. It accepts a successful same-repository `main` push from CI and runs on the dedicated self-hosted runner labeled `garrison-production` only when the repository-level Actions variable `GARRISON_PREDEPLOY_GATE_READY` is exactly `true`. The job condition is evaluated before the runner enters the `Production` environment, so an environment-scoped variable is not sufficient. Leave the repository variable unset/false until the reviewed trusted validator and root-controlled approval store are installed and verified on Hostinger. This readiness switch is a fail-closed deployment interlock, not a release approval; the host still checks the exact SHA and authenticated predeployment evidence. GitHub concurrency and a host lock serialize releases.

The automatic job passes the triggering CI run's tested SHA to the host. For a manual retry, dispatch `deploy.yml` from `main` with `ci_run_id` set to a successful CI run for the current tip. The host checks both invocations against GitHub's CI metadata, required jobs and current `main` before fetching the tested archive.

The installed [host release script](../deploy/hostinger-release.sh) checks protected configuration, audit deletion settings, stateful Compose resources and Alembic heads. It builds from the tested source and takes encrypted application and Grafana database backups before activation. It swaps the frontend index atomically and checks running images, readiness and served HTML, JavaScript and service worker hashes. Success advances `current` and writes `DEPLOYED` with **Deployed — Formal Acceptance Pending**. Failed activations follow the [rollback procedure](#rollback). Formal acceptance follows the [release closure guide](POST_RELEASE_ACTIONS.md#operational-and-final-acceptance-gates).

### Review pipeline time on every release

Compare the exact candidate's Actions run with recent runs that cover the same tests. Record queue time, elapsed CI time, the slowest job and steps, cache hits, and total runner time. Pytest reports its ten longest tests and the browser jobs log individual test durations. Look for independent work to run in parallel, repeated setup, and avoidable rebuilds. Record a measured result after each change and confirm the same required checks and test coverage ran.

The backend suite and Chromium browser suite each run in two shards with separate PostgreSQL, Redis and object storage services. Each job starts its pinned Moto container alongside dependency installation and applies migrations to its own database before testing. The [CI workflow](../.github/workflows/ci.yml) assigns browser files by measured test time. One shard selects a set of files and the other selects its complement, including newly added files. Each shard runs individual tests in parallel with two workers. Each browser test uses its own browser context, synthetic accounts and project data. The browser jobs build the production bundle alongside Chromium provisioning and wait for both before serving it. They still type-check the browser tests, and the required frontend job type-checks the application. Local `pytest` and `npm run test:browser` still run the full suites by default. The release receipt requires success from all four shards.

Backend sharding assigns whole test modules using measured runtimes for the slowest modules and case counts for the rest. If shard timings diverge across comparable runs, sum JUnit case times by module from both backend reports before adjusting the estimates in [the pytest configuration](../backend/tests/conftest.py).

For browser rebalancing, sum case times by file across both reports from comparable runs. After editing the workflow filter, use Playwright's `--list` with each filter and verify that the combined list matches the unfiltered suite exactly.

The pre-rebalance baseline is CI run `43504480104` on `c50de62e4fbb2c57426d208e38e787421ac96f90`: 209 seconds wall time; browser shard 1 took 148 seconds and shard 2 took 204 seconds. Their browser-test steps took 74 and 104 seconds. JUnit case-time sums were 127.23 and 180.53 seconds; `project-setup.e2e.ts` contributed 24.89 seconds on shard 2. The first rebalance on `00b38884c450ac699cbc8039b522044e05fff1ca` passed all checks but did not improve measured CI wall time: it took 214 seconds, with browser jobs at 210 and 159 seconds and test steps at 120 and 64 seconds. Its JUnit sums were 205.96 and 106.06 seconds. The second rebalance on `9f7a543c5b637109f735709cbe27a59910b2f6c7` passed all required checks in 195 seconds wall time; browser jobs took 150 and 193 seconds, with test steps at 72 and 114 seconds and JUnit case-time sums of 126.98 and 202.26 seconds. The third rebalance on `d79f4f47534e5d726fa258befa3c6b496d506cca` passed all checks in 178 seconds; browser jobs took 142 and 175 seconds, with test steps at 74 and 93 seconds and JUnit case-time sums of 132.11 and 155.90 seconds. The fourth rebalance on `f81e369bce759aef93e172f60bde1552d0d53f9f` passed all checks in 170 seconds; browser jobs took 166 and 152 seconds, with test steps at 90 and 77 seconds and JUnit case-time sums of 161.70 and 125.54 seconds. This run was 39 seconds shorter than the baseline, but measurements vary substantially between runners and the single-run difference is not proof of a repeatable speedup.

Run `43532349807` on `3a14193c417759f2dfba82ada81c07be6e4c1daa` passed all CI jobs in 206 seconds wall time. Browser jobs took 202 and 130 seconds; JUnit case-time sums were 201.91 and 100.30 seconds. `media-documents.e2e.ts` contributed 57.01 seconds on shard 1. Moving it to shard 2 produced run `43533754801` on `824bf5ade60b0104b6dd1b0c12d2cf2b0cda834c`: all CI jobs passed in 170 seconds wall time, browser jobs took 151 and 157 seconds, and JUnit case-time sums were 122.44 and 147.09 seconds across 20 and 14 tests, with zero failures or skips. The slowest browser job fell by 45 seconds and overall wall time by 36 seconds; total JUnit case time also fell by 32.68 seconds, so runner and test-time variation mean that one run does not establish a repeatable 36-second saving. The same split passed again on `074705cac8f2ba987f00314e7c851a6a4de94d0d` in run `43534240845` (188 seconds wall time), with browser jobs at 142 and 185 seconds and JUnit sums of 129.55 and 159.11 seconds; all 34 tests passed without failures or skips. Across these two comparable runs, shard means were 126.00 and 153.10 seconds. Moving `approval-delegation.e2e.ts` (16.59-second mean) to shard 1 projected 142.59 and 136.51 seconds. Exact-main run `43534831860` on `ab85afbf29857de2b038f8296daeef7816fd7043` passed in 181 seconds; browser jobs took 179 and 141 seconds, with JUnit sums of 161.25 and 114.96 seconds across 21 and 13 tests, zero failures and zero skips. The measured split moved the skew to shard 1, opposite the projection. Given the run-to-run changes in individual file durations, keep required coverage and collect another comparable run before tuning again or claiming a repeatable speedup. CI caches and same-ref cancellation remain enabled; no checks or browser platforms were removed.

The next exact-main run, `43535437953` on `8d23dbe949696e7cd4e9ad0ad925f9d99c8ce256`, passed in 186 seconds wall time. Browser jobs took 129 and 182 seconds; their test steps took 60 and 95 seconds. JUnit sums were 106.16 and 162.54 seconds across 21 and 13 tests, with zero failures or skips. Moving `finance-workflows.e2e.ts` (23.41 seconds) and `import-workflow.e2e.ts` (9.29 seconds) to shard 1 projected 138.86 and 129.84 seconds. Run `43536923181` on `fc6b204d1b87d225d08a762c815e1c42d175f7e3` passed in 213 seconds wall time with browser jobs at 209 and 166 seconds. Its JUnit sums were 208.76 and 128.11 seconds across 24 and 10 tests, zero failures and zero skips. Applying that run's per-file times to the prior assignment projects 173.26 and 163.60 seconds; this reverses the apparent balance. The prior assignment was restored and run `43537489987` on `d63d24e029fb16c3b24e7eb9ce688807d51870e9` passed in 202 seconds wall time. Its browser jobs took 190 and 200 seconds, with JUnit sums of 178.43 and 196.69 seconds across 21 and 13 tests, zero failures and zero skips. The closer job durations support keeping this split for now, but test-time variation across runs means there is still no proven repeatable wall-time saving.

Exact-main run `43542078874` on `af456c4e5ea618a197768fc2b0c3a9829ea7f794` passed in 171 seconds wall time (about 2 seconds queued); summed job elapsed time was 699 seconds. Browser jobs were longest at 168 and 141 seconds, including 75/72-second browser-test steps and 47/44-second dependency-and-service setup. Backend test jobs took 152/140 seconds, including 95/84-second pytest steps and 34 seconds of setup each. Backend lint/types took 45 seconds, frontend checks 25 seconds, and Compose validation 28 seconds. The run logs confirm pip/npm cache hits. Independent jobs and shards are already parallelized and measured splits are close; this run does not support reducing parallelism or removing a required check for a wall-time gain. The associated production workflow `43542354832` was skipped because the trusted predeployment gate was not ready.

The next exact-main run, `43547184830` on `5e28db89665bcbc7575ce118a9abf5d96224640d`, passed in 174 seconds wall time; summed job elapsed time was 740 seconds. Browser jobs took 161/171 seconds, with 79/89-second test steps and 53/55-second setup. Backend test jobs took 158/137 seconds, with 105/75-second pytest steps and 32/35-second setup. Backend lint/types took 45 seconds, frontend checks 49 seconds, and Compose validation 19 seconds. This is 3 seconds slower than the preceding run, while the browser and backend job ordering changed; the single-run variation does not show a pipeline regression or justify a speculative shard change. Preserve the current checks and parallel layout, then compare more runs before claiming a repeatable saving. The corresponding production workflow `43547450409` was skipped by the same trusted predeployment gate.

The latest exact-main CI timing sample, run `43547650068` on `3a1c168516052a8adcdcde348f90e730ad0faa11`, passed all required CI jobs in 183 seconds wall time; summed job elapsed time was 728 seconds. Browser jobs took 155/180 seconds, with browser test steps at 67/91 seconds and dependency/storage preparation at 48/56 seconds. Backend test jobs took 167/139 seconds, with pytest at 105/79 seconds and preparation at 37/36 seconds. Backend lint/types took 44 seconds, frontend checks took 26 seconds, and Compose validation took 17 seconds. Compared with the prior sample, wall time was 9 seconds slower while summed job time was 12 seconds lower; the frontend job was 23 seconds shorter, but this single run does not establish why or prove a repeatable saving. Keep the current shard assignment, caches and parallel checks until comparable runs show a stable opportunity. The production workflow remained gated and did not deploy.

The first CI run after adding the stricter runtime-configuration check, `43552941649` on `362163bfb9a2b439de3b88d22b91adae752dd0ca`, took 185 seconds wall time and 698 summed job seconds. Six jobs passed; backend mypy found seven typing errors in one new test fixture. Browser jobs took 167/182 seconds, backend test jobs 121/139 seconds, frontend checks 27 seconds, and Compose validation 18 seconds. The failure was test-fixture typing, not a runtime or shard regression; the fixture annotation and `None` return assertion have been corrected for the next exact-SHA run. No CI checks were removed or weakened.

The corrected exact-main run, `43553321898` on `f296c7364d2537de8002a7bbfbc37e1a68b79610`, passed all required jobs in 181 seconds wall time; summed job elapsed time was 712 seconds. Browser jobs took 167/177 seconds, with browser-test steps at 83/87 seconds and dependency/storage preparation at 57/55 seconds. Backend test jobs took 162/107 seconds, with pytest at 90/53 seconds and preparation at 37/23 seconds. Backend lint/types took 32 seconds, frontend checks 44 seconds, and Compose validation 23 seconds. Compared with the preceding successful sample, wall time was 2 seconds faster and summed job time 16 seconds lower; this does not establish a repeatable saving. CI preserved its existing bundled-Chromium test coverage. The production workflow remained skipped by the unset trusted predeployment readiness gate.

The exact-main run `43555987614` on `0a3ac92a4b2b58ee7eb8c900e4f8843db02178c1` passed in 170 seconds wall time; summed job elapsed time was 666 seconds. Browser jobs took 167/148 seconds, including 86/72-second test steps and 55/48 seconds of dependency/storage preparation. Backend test jobs took 142/120 seconds, backend lint/types 43 seconds, frontend checks 30 seconds, and Compose validation 16 seconds. Compared with the preceding exact-main run `43553776518` (190 seconds wall, 708 summed job seconds), this sample was 20 seconds faster wall-clock and 42 seconds lower summed time. The workflow itself did not change, so this single run does not establish a repeatable optimization. The browser shard remains the critical path; test and setup work already run in parallel with required checks. Keep the current coverage and shard split until repeated per-test timings show a stable, evidence-backed improvement. Production deployment was skipped because `GARRISON_PREDEPLOY_GATE_READY` remains unset.

The docs-only run `43556574836` on `b45aed6fb8e8c5efbe1edb33eac564a728173946` passed after retrying one failed backend shard. Its first attempt took 182 seconds and failed the `schema-change` entrypoint case; the failed-shard retry passed 332 tests in a 171-second job. The test double returned before reading the Compose JSON piped to it, creating a race that could close the producer pipe early and surface the wrong guard. The fixture now drains stdin like the real validator. The focused file passes 50 tests and the affected scenario passed 10 repeated runs locally; CI on the corrected fixture is pending. The queue delay plus retry made this iteration longer than a normal run, so do not use its full elapsed time as a pipeline performance baseline. No CI checks or workflow steps were changed.

For release candidate `0a3ac92`, local Playwright browser regressions passed on macOS 27.2.1 build 26B131: Google Chrome 157.0.8103.79 and Microsoft Edge 157.0.4341.57 each reported 34 passed, 0 failed, 0 errored, and 0 skipped. The JUnit receipts and their hashes are held in the restricted local evidence directory; they are not yet in the approved release evidence bundle. These automated results do not substitute for named QA approval, business workflow UAT, degraded-network evidence, or production readback.

For deployment, measure runner queue time separately from the host phase timings. The host builds the tested archive using Docker's layer cache and reuses the running backend image when only tests, backend documentation or frontend files change. The release script reads the frontend hashes in one container and checks the served bytes after activation.

### Host bootstrap and runner maintenance

Provision the existing stack and an initial active release before registering the production runner. The script expects the project `garrison-portal`, an active release under `/opt/garrison-portal/releases/`, and the `garrison-portal_frontend_dist` volume. Under `/opt/garrison-portal/deploy/`, keep the following root-controlled.

| Host item | Purpose |
| --- | --- |
| `production.env` | Private configuration copied into each candidate release. |
| `compose.vps.yml` | Existing stateful resource names, TLS and key mounts, and host-specific overrides. |
| `current` | Link to the last verified release containing `.env`, `.images.env`, `SOURCE_COMMIT`, and its deployment receipt. |
| `deploy.lock` | Host-side serialization across release attempts. |

Before using the new workflow, the host operator installs the reviewed `deploy/hostinger-release.sh` as root-owned `/usr/local/sbin/garrison-deploy` with mode `0755`. The runner needs noninteractive `sudo` for this entrypoint. The workflow and host must both support the `rollback-v2 technical-checks-v1` arguments. Set `LOG_PURGE_ENABLED=false` in the protected environment and keep the encryption password and application secrets there. The entrypoint checks effective Compose settings and stops if audit deletion is enabled.

The current entrypoint also requires the standalone trusted validator at `/usr/local/libexec/garrison-release-contract.py`. This file is a separately reviewed, root-owned copy of `backend/scripts/release_contract.py`; it must not be copied from an unreviewed candidate archive by the deployment runner. Before a release whose host entrypoint invokes this gate, the authorized host operator must:

1. Confirm no production deployment is queued or running, acquire `/opt/garrison-portal/deploy/deploy.lock`, preserve the existing entrypoint and validator with their recorded hashes, and compare the reviewed candidate source with the proposed installs.
2. Install the validator from the separately transferred reviewed source to a temporary file inside `/usr/local/libexec`. Verify its SHA-256 against the independently reviewed install record, then atomically rename it to `/usr/local/libexec/garrison-release-contract.py`. Set owner `root:root`, mode `0644`, and keep `/usr/local/libexec` root-owned and not group/world writable. Verify `python3 /usr/local/libexec/garrison-release-contract.py --help` succeeds and record the installed digest.
3. Install `deploy/hostinger-release.sh` as `/usr/local/sbin/garrison-deploy`, owner `root:root`, mode `0755`, using the same lock and an atomic replacement. Verify the installed digest, Bash syntax and existing runner `sudo` rule. Preserve both prior executables until the new release is accepted.
4. Keep `/opt/garrison-portal/deploy/authorized-configuration.json`, `approval-trust.json`, and `authorizations/<full-source-sha>/` root-owned and protected from group/other writes; the release runner must not be able to modify them. Store only the exact approved release files under each authorization directory. Release the lock only after verifying both installed digests and the protected authorization paths.

The validator is a release authorization boundary, not a convenience check. Do not bypass it or temporarily copy a candidate-controlled validator into the trusted path. If the trusted validator is absent, mismatched, or cannot read valid root-controlled evidence, deployment must stop before source activation. A subsequent change to the validator requires its own review, digest verification and controlled installation before the matching candidate is allowed to trigger production CD.

For a release that changes the entrypoint, compare the exact candidate script with the installed copy and record both SHA-256 digests. After release authorization and before the main update can trigger automatic CD, confirm no deployment job is queued or running. Take the production deployment lock, preserve the previous executable in the root-controlled deployment directory, and verify the candidate's digest and Bash syntax. Install it with owner `root:root` and mode `0755` using an atomic rename from the same directory. Confirm the installed digest and runner's existing sudo permission. Release the lock before triggering CD. Keep the deployment protocol and generation compatible with the active release during this step.

After activation, collect the original `DEPLOYED` file and confirm its CI run and attempt, deployment run and attempt, and candidate SHA. A retry of the active SHA only checks readiness. It does not recreate a missing receipt field. Preserve the prior release receipt as recorded. [Formal acceptance receipt instructions](templates/release-closure/README.md)

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

Pending Alembic revisions and changes to PostgreSQL, Redis, the S3 service, its initializer, the Grafana database initializer, Compose volumes, or networks require a reviewed maintenance window. Production CD blocks those changes before activation. A change in rollback generation also requires a maintenance window. The entrypoint stops before activation while Nginx, the backend, worker or scheduler is running. During the authorized window, block ingress and drain writes, stop those four services while leaving PostgreSQL and object storage available for the backup, then dispatch the tested candidate. Have a recovery-forward procedure ready before this switch.

1. Identify the candidate SHA, successful CI run, deployed SHA, current database revision, and affected volumes. Review the migration, data repair prerequisites, and compatibility with the running application. Rehearse the exact change against an isolated restore.
2. Record the backup object names and tested recovery plan. The pre-activation database backup uses `--skip-retention` to preserve existing backups. It protects the databases. Independent database and object recovery remains in the post-release backlog. Coordinate with the deployment operator so routine CD and maintenance cannot overlap. Quiesce affected writers when the change requires a consistent database or object snapshot.
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

[restore_dry_run.py](../backend/scripts/restore_dry_run.py) inspects a decrypted plain SQL or gzip SQL dump, records its hash, and can execute the restore using `psql` with fatal SQL errors. The client skips startup files and fails on missing credentials instead of waiting for a password prompt. From a prepared backend environment with the disposable database URL in `RESTORE_DATABASE_URL` and a securely stored decrypted dump:

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

For a new set that can count toward acceptance, use the approved D-29 policy and authenticated format 2. Captures without `--policy` use the legacy checksum-only format 1 and are retained only for historical recovery. In the authorized backend environment, provide `BACKUP_ENCRYPTION_PASSWORD`, `BACKUP_AUTH_KEY_FILE`, and `BACKUP_AUTH_KEY_ID` through restricted inputs. Keep the approved policy at `$RECOVERY_POLICY` and the allowlisted nonsecret runtime files at `$RECOVERY_CONFIGURATION_ROOT`.

```bash
python -m scripts.backup_set capture \
  --source-sha "$RELEASE_SHA" \
  --consistency-note "$WRITE_PAUSE_EVIDENCE" \
  --destination "$LOCAL_SET" \
  --policy "$RECOVERY_POLICY" \
  --capture-receipt "$CAPTURE_RECEIPT" \
  --configuration-root "$RECOVERY_CONFIGURATION_ROOT"
python -m scripts.backup_set verify "$LOCAL_SET" \
  --policy "$RECOVERY_POLICY" --require-authenticated
```

The authenticated `verify` command checks the exact manifest signature, artifact presence, size, and hashes before restore. For a recovery exercise, mount the set in a disposable environment with its own empty PostgreSQL databases and new object bucket. Configure `RESTORE_DATABASE_URL`, optional `RESTORE_GRAFANA_DATABASE_URL`, `RESTORE_OBJECT_ENDPOINT`, `RESTORE_OBJECT_BUCKET`, `RESTORE_OBJECT_ACCESS_KEY`, and `RESTORE_OBJECT_SECRET_KEY` privately. The tool accepts only loopback PostgreSQL databases named `garrison_restore_test_*` and a new loopback bucket named `garrison-restore-test-*`. Disable outbound mail and scheduled business jobs in the restored application.

Use that same approved policy for publication, fetch and restore. Publication also requires the separate prefix-scoped `DR_BACKUP_*` publisher credentials; it verifies remote encrypted bytes before writing the authenticated completion record. For example, publish with `python -m scripts.backup_set publish "$LOCAL_SET" --policy "$RECOVERY_POLICY" --receipt "$PUBLICATION_RECEIPT"`. A substitute operator can fetch a complete set with `fetch "$BACKUP_SET_ID" --policy "$RECOVERY_POLICY" --destination "$ISOLATED_SET"` and restore it with `--require-authenticated`. Retain the existing format 1 sets for historical recovery and record their checksum-only assurance.

The [scheduled capture service](../deploy/backup-set.service) invokes the [capture wrapper](../deploy/capture-recovery-set.sh) under the same host lock as deployment. Set `RECOVERY_POLICY`, `RECOVERY_CAPTURE_TEMPLATE`, `RECOVERY_CAPTURE_ENV`, `RECOVERY_PUBLISH_ENV`, and the two authentication key variables in the root-owned scheduler environment. Set `RECOVERY_CONFIGURATION_ROOT` to a dedicated root-owned directory containing only the approved nonsecret recovery configuration. Keep the policy, capture inventory, credentials and authentication key outside that directory. Install the service and wrapper only after exercising the write pause and recovery against the approved destination.

Generate the systemd timer from the authenticated approved policy; do not hand-edit an interval or use an unexpanded environment variable in `OnCalendar`. The generator uses `backup_interval_minutes` and accepts only intervals that divide 1,440 minutes exactly, so the daily calendar entries preserve the cadence across midnight. Longer intervals and intervals that do not divide a day require a separately approved external scheduler. Installing or enabling this timer in production requires the approved recovery decision, a successful rehearsal, and the separate operational authorization for that change.

```bash
TIMER_DIR=$(mktemp -d)
TIMER_TMP="$TIMER_DIR/backup-set.timer"
python -m scripts.backup_set schedule \
  --policy "$RECOVERY_POLICY" \
  --output "$TIMER_TMP"
sudo systemd-analyze verify "$TIMER_TMP" /etc/systemd/system/backup-set.service
sudo install -o root -g root -m 0644 "$TIMER_TMP" /etc/systemd/system/backup-set.timer
sudo systemctl daemon-reload
sudo systemctl enable --now backup-set.timer
sudo systemctl list-timers backup-set.timer
rm -f "$TIMER_TMP"
rmdir "$TIMER_DIR"
```

The wrapper uses one private `.scheduled-capture` workspace under `/opt/garrison-portal/recovery/scheduled/`. It removes that workspace after verified publication and writer recovery. When publication fails after writers resume, the next run retries the same signed set before creating another capture. If its publication deadline has passed, the active release changed, or writer recovery is unverified, review `last-attempt.json` and resolve the pending set with the recovery operator. Review historical `capture-*` directories separately before reclaiming their disk space.

In `RECOVERY_CAPTURE_ENV`, use dedicated database logins with connect, schema usage, and read access to the required application and Grafana tables and sequences. Review grants after migrations and verify that capture can read every required row and object. Supply a source object credential limited to reading the required bucket objects. The `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` field names in the capture environment accept that restricted credential. Use separate prefix-scoped publisher and recovery-reader credentials, with deletion reserved for the retention principal.

Use explicit `NAME=value` assignments in both scheduler credential files. Required values must be nonempty. The wrapper rejects duplicate names, names that inherit values from the host, and source database or storage settings in the publisher file. Keep independent destination settings in the publisher file.

New complete sets omit source database owners and grants so recovery can proceed without source-only roles. Include the reviewed runtime role and grant provisioning in the recovery inventory, apply it to the restored databases before application startup, and verify the resulting permissions. Existing dumps retain the SQL they were captured with. If a historical dump references a missing source role, review its required role definitions with the recovery operator and provision the required roles in the isolated target before retrying. The ordinary database backup schedule retains its existing dump behavior.

The scheduler signs and publishes `last-scheduled-attempt.json` to the approved recovery prefix after writer recovery. The publisher needs write and readback access to this status object, and the independent monitor needs read access. Verify the first scheduled attempt record before switching the monitor. A failed policy preflight after the scheduler acquires the lock and validates the active release and receipt directory records a `preflight` failure without pausing writers. If the policy cannot be authenticated for publication, the local `last-attempt.json` and scheduler exit status remain available for investigation. An overlapping run leaves the lock holder's receipt in place. Only a verified complete set advances backup freshness.

When rotating the authentication key or changing the policy revision, use a new approved destination prefix. Keep the previous prefix and escrow the exact policy bytes, key ID, authentication key and decryption material until the retained sets expire. Verify a complete set under the new policy before changing the monitor. Preview expired sets with the separate retention command; apply only the reviewed plan using authorized retention credentials.

Retention removes the completion marker first and checks that each deleted object is absent from the current S3 view. If the receipt names an `incomplete_set_id`, retain the plan and receipt and have the authorized operator reconcile that prefix before further cleanup. A set without its marker will be absent from later retention previews. The identity reservation remains so the set ID cannot be reassigned. On a versioned destination, historical object versions remain subject to the approved storage lifecycle policy.

```bash
python -m scripts.backup_set restore /private/independent-storage/backup-set
```

Set `TMPDIR` to a private recovery volume with room for all decrypted artifacts. Allow additional space for the largest uncompressed SQL dump or largest object readback, whichever is larger. The tool checks available space before decryption and rechecks it after staging the artifacts, before writing to the target databases or bucket. Size the volume against a representative maximum backup and include a low-space rejection in the recovery drill.

The restore checks decrypted bytes before writing and checks the resulting schema, database references, and restored object checksums. Start the isolated application and open the required protected files under authorized and forbidden accounts. Include the backup set identity, source SHA, schema head, UTC timings, missing or corrupt artifact tests, key access, and actual recovery results in the release evidence. Local fixtures establish tool behavior. The release still requires a drill with the approved destination, retained data scope, operator, and measured targets.

If a restore is interrupted, record the phase and keep the targets isolated. PostgreSQL rolls back the interrupted database transaction. A database restored in an earlier phase or objects copied before a later failure can still remain. Treat the attempt as incomplete and retry the same verified backup set into new empty databases, a new bucket, and a new configuration directory. Record the interrupted attempt and the retry separately. Keep the last verified recovery point available throughout the drill.

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

Use sample data only in an approved non-production environment. Follow the [seed setup](../README.md#getting-started) and the [roles and permissions reference](ROLES_AND_PERMISSIONS.md). Run browser acceptance in desktop Chrome and Edge, including offline retries, file selection and downloads, and degraded-network checks. For UAT-21, use representative JPEG, PNG and HEIC files to verify format and size boundaries and original-only HEIC behavior. Record the browser version, role, scenario, result, and any accepted issue.

## Formal acceptance still pending

The current portal scope limits Delivery to Launch readiness and excludes G-01. The selected audit mode for this release is retain-only, and destructive audit deletion stays disabled. The user's approved browser scope is desktop Chrome and Edge with no physical mobile targets. Each item below remains open for formal acceptance (see [POST_RELEASE_ACTIONS.md](POST_RELEASE_ACTIONS.md) for full details).

| Decision | Responsible role | Work and evidence | Risk until verified |
| --- | --- | --- | --- |
| D-27-SCOPE | Business sponsor | Approve the scope inventory digest and exclusion in a signed decision. | The deployed scope still needs formal business acknowledgement. |
| D-28-POLICY | Records owner | Sign the retain-only policy, classes/deadlines, unknown-record handling, and hold decision. Review the complete preview, archived access and storage capacity. | Purge remains disabled; records continue to accumulate and capacity still needs review. |
| D-29-RECOVERY | System owner | Approve independent storage, key custody, RPO/RTO and operator access. Restore an authenticated database and object backup and record measured results. | Recovery after loss of the primary and recovery of file objects remain unproven. |
| D-30-OPERATIONS | Operations owner | Approve and exercise the independent monitor, recipients and responders. Record alert delivery, acknowledgement and recovery. | An outage affecting the primary host may delay detection. |
| D-32-SUPPORT | QA lead | Local automation on `0a3ac92a4b2b58ee7eb8c900e4f8843db02178c1` passed 34 Chrome 157.0.8103.79 tests and 34 Edge 157.0.4341.57 tests on macOS 27.2.1 build 26B131, with zero failures, errors, or skips. JUnit hashes are recorded in the restricted local receipt, not the approved release bundle. Current main CI uses bundled Chromium. Approve the tested versions, assign QA, finish the role/scenario matrix, numeric budgets, business/degraded-network checks, production readback, and QA sign-off. Physical mobile targets are excluded by the user's scope instruction. | The automated browser runs are recorded; human QA/business acceptance remains pending. |
| D-33-BUSINESS | Finance/data owner | Approve assignments, sample outputs, financial conventions and import controls. Reconcile the data and obtain final sign-off after observation. | Business inputs and acceptance remain pending. |

<a id="5-launch-evidence-capture--sign-off"></a>

## 5. Formal Acceptance Evidence

Freeze the source SHA and approved configuration. Collect the signed scope, retention, recovery, operations, device/support and business decisions together with executed control receipts. Use the [unsigned release templates](templates/release-closure/README.md) and keep sensitive evidence private. Record the operator and approvers as separate roles and have the trusted reviewer verify the actual approvals before populating the approval registry.

For formal acceptance, use the standalone validator to check the predeployment evidence bundle. A predeployment pass establishes deployment readiness only; it is not final acceptance.

```bash
cd backend
python scripts/launch_evidence.py --target production --commit "$RELEASE_SHA" \
  --manifest "$RELEASE_MANIFEST" --evidence-root "$PRIVATE_EVIDENCE_ROOT" \
  --trust-registry "$APPROVAL_TRUST_REGISTRY" --phase predeploy --validate-only \
  --output "$PREDEPLOY_REPORT" --json-output "$PREDEPLOY_VERDICT"
```

After deployed readback, live checks, the approved observation cycle, and final owner sign-off, run the same command with `--phase final` and separate verdict paths. Its evidence requirements apply to formal acceptance. The production workflow runs its technical checks independently. Only the final successful verdict can certify the frozen scope. The existing collection command below remains useful for a draft evidence summary.

[launch_evidence.py](../backend/scripts/launch_evidence.py) checks the supplied URLs and records hashes for attached evidence files. Run it from a trusted checkout using private output paths and the actual release values:

```bash
cd backend
python scripts/launch_evidence.py --target production \
  --output /path/to/private/production-launch.md \
  --health-url https://portal.garrisons.lk/health \
  --readiness-url https://portal.garrisons.lk/health/readiness \
  --commit "$RELEASE_SHA" --run-url "$DEPLOY_RUN_URL" \
  --operator "$PRODUCTION_OPERATOR" --approver "$APPROVER" \
  --backup-object "$APPLICATION_BACKUP_OBJECT" \
  --restore-log /path/to/private/restore-evidence.md \
  --uat-signoff /path/to/private/uat.md
```

The script records the supplied backup object name. Attach the Grafana backup reference and the actual restore results to the sign-off record.
