# Operations and Deployment Guide

[Documentation index](README.md) · [Architecture](ARCHITECTURE.md) · [Logging and alerts](LOGGING_AND_REMOTE_CLI.md)

Use [production CD](#production-deployments-from-github-actions) for routine releases, the [maintenance procedure](#production-maintenance) for database or stateful changes, and [post-deploy verification](#post-deploy-verification) for live checks and first-Managing-Director setup. [Backup and restore](#3-operations-backup--restore), [release closure](POST_RELEASE_ACTIONS.md), and [formal acceptance evidence](#5-launch-evidence-capture--sign-off) cover recovery and the evidence required for final acceptance.

## Environment and configuration

| Environment | Source of truth | Entry point |
| --- | --- | --- |
| Development | [Local Compose](../docker-compose.yml) and [.env.example](../.env.example) | [Getting started](../README.md#getting-started) |
| Production | [Production Compose](../docker-compose.prod.yml), host override, and private environment file | [portal.garrisons.lk](https://portal.garrisons.lk) |

The former staging deployment is retired and is not a deployment target or part of production acceptance. Its checked-in Compose and application compatibility settings are legacy references; CI retains a focused compatibility test for some of them.

Use Docker with Compose v2. Keep production configuration and secrets on the host with restricted permissions. See [backend settings](../backend/app/config.py) and the matching Compose file for variable names, defaults, and service overrides.

During routine deployments, [hostinger-release.sh](../deploy/hostinger-release.sh) checks `production.env` (`0600`), `compose.vps.yml`, required candidate configuration files, non-symlink bind mounts, TLS certificates (`/etc/nginx/ssl/fullchain.pem` and `privkey.pem`), JWT signing key mounts, and `LOG_PURGE_ENABLED=false`. The release gate confirms that each application writer receives every value from the pinned candidate environment. Docker Compose's normalized JSON flattens `env_file` paths into each service's effective environment, so the gate validates the resulting key/value contract rather than expecting a source path in normalized output.

The production proxy image is pinned to the official `nginx:1.30.7-alpine` multi-architecture manifest digest in `docker-compose.prod.yml`. Treat the live Nginx version as verified only from the running container after deployment; keep the business TLS virtual host and Super Admin source allowlist checks in the release smoke test.

For optional post-release formal acceptance, you may bind the production configuration to exact bytes without copying secrets into the evidence bundle using `/opt/garrison-portal/deploy/authorized-configuration.json`. That profile has a `files` map keyed by namespace: `host/` files resolve beneath the deployment state directory, `release/` files resolve beneath the exact candidate archive, and `external/` files resolve beneath `/opt/garrison-portal`. `configuration_sha256` is the SHA-256 of the canonical `files` map (sorted keys, compact separators, UTF-8, `ensure_ascii=False`). This release's required versioned runtime file set is shown in the [authorization profile template](templates/release-closure/authorized-configuration.json).

If running optional formal acceptance, generate a proposed profile from a restricted candidate directory on the production host using `backend/scripts/release_contract.py` (do not use the active release as the candidate). The command below emits file names and hashes only, and `docker compose config` output is piped directly to stdin without saving secrets:

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
  python3 backend/scripts/release_contract.py \
    --host-state "$state" --configuration-profile-root "$candidate"
```

When using that optional formal profile, verify the paths against actual service mounts and recompute the digest whenever any configuration, TLS, or signing-key file changes.

| Concern | Configuration to check |
| --- | --- |
| Environment and URLs | `APP_ENV=production`, `DEBUG=false`, `FRONTEND_BASE_URL`, and the allowed origins in `BACKEND_CORS_ORIGINS`. |
| Database and queue | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`, and `REDIS_URL` must identify the environment's private services. URL-encode credentials embedded in URLs. |
| Signing keys | Mount the matching RSA private/public files at `JWT_PRIVATE_KEY_PATH` and `JWT_PUBLIC_KEY_PATH`. Production startup validates the configured signing keys. |
| Public ingress | Configure DNS and TLS for the portal and `GRAFANA_DOMAIN`. The host override supplies the production certificate mount. For a standalone Compose setup, the base file mounts `nginx/ssl/`. |
| Object storage | Use the internal `MINIO_ENDPOINT` for the backend and the public portal authority in `MINIO_PUBLIC_ENDPOINT` with `MINIO_PUBLIC_SECURE=true` for browser URLs. Route `/portal-files/` through Nginx and preserve the original `Host`, including any non-default port. Both checked-in Nginx configs use `$http_host` on this route. |
| Proxy trust | Base production Compose trusts loopback and the Nginx address from `NGINX_BACKEND_PROXY_IP`. When resolving Docker subnet overlap, adjust `NGINX_BACKEND_PROXY_SUBNET`, `NGINX_BACKEND_PROXY_DYNAMIC_RANGE`, and `NGINX_BACKEND_PROXY_IP` together. Review the ingress trust configuration when adding a proxy hop. |
| Application email | Set `SMTP_FROM_EMAIL` to the authorized sender. For SMTP, `SMTP_FROM_NAME` controls the message display name. The useSend API payload supplies the sender address, so verify the display name at the provider. [EmailService](../backend/app/services/email_service.py) selects useSend when either `USESEND_API_URL` or `USESEND_API_KEY` is present, so configure the pair together. Confirm receipt of a real OTP after changing mail settings. |
| Cloudflare mail fallback | In the protected application environment, configure `CLOUDFLARE_EMAIL_ACCOUNT_ID` and an account-scoped `CLOUDFLARE_EMAIL_API_TOKEN` with **Email Sending: Edit**. Use `CLOUDFLARE_EMAIL_FROM=mailservice@cf-mail.garrisons.lk` for the dedicated Garrisons fallback domain. The application tries useSend or SMTP first. For partial SMTP delivery it sends only refused addresses to Cloudflare. A primary timeout can leave delivery uncertain and produce a duplicate when the fallback succeeds. Verify Cloudflare acceptance and actual receipt with a controlled address. [Cloudflare sending API](https://developers.cloudflare.com/api/resources/email_sending/methods/send/) |
| Recovery and alerting | Store the backup-encryption value in a root-owned mode-0600 file under `/opt/garrison-portal`; set only its path as `BACKUP_ENCRYPTION_KEY_HOST_FILE` in `production.env`. Production Compose mounts it read-only and supplies `BACKUP_ENCRYPTION_KEY_FILE` inside the containers. Do not put the value in `production.env`. Also set `DOCKER_SOCKET_GID` (`stat -Lc '%g' /var/run/docker.sock`), Grafana credentials, and Loki object-store credentials. See [Grafana, Loki, and Alloy](LOGGING_AND_REMOTE_CLI.md#grafana-loki-and-alloy) and [alert delivery](LOGGING_AND_REMOTE_CLI.md#alert-delivery). |

Compose defaults to digest-pinned Silo and its S3 client for new installations. Existing hosts may set `OBJECT_STORAGE_IMAGE` and `OBJECT_STORAGE_CLIENT_IMAGE`. Treat a provider or image change as stateful maintenance. Verify application objects, backup retrieval, and Loki reads on an isolated copy, and retain the original volume and image for rollback.

## Production deployments from GitHub Actions

[CI](../.github/workflows/ci.yml) uses isolated self-hosted Linux x64 runners tagged `garrison-ci` for pull requests and pushes to `main`. Test databases, Redis and object storage run in disposable Docker-in-Docker environments; CI receives no production credentials, production Docker socket or production volumes. The two-job integration cap matches the available isolated runner pool, and persistent pip/npm caches avoid repeated dependency downloads. [Deploy production](../.github/workflows/deploy.yml) remains a separate workflow in the `Production` environment. It runs only on the dedicated self-hosted Hostinger runner labeled `garrison-production`; CI never uses that runner. GitHub concurrency (`garrison-portal-production`) and a host file lock (`deploy.lock`) serialize releases. Formal business approvals (`D-27` through `D-33`) do not block automated deployment and remain tracked separately under [post-release actions](POST_RELEASE_ACTIONS.md).

The automatic job passes the triggering CI run's tested SHA to the host. For a manual retry, dispatch `deploy.yml` from `main` with `ci_run_id` set to a successful CI run for the current tip. The host checks both invocations against GitHub's CI metadata, all seven required CI jobs, and the current `main` branch tip before fetching the tested archive.

The installed [host release script](../deploy/hostinger-release.sh) checks root ownership and safe permissions on host directories and secrets, verifies the CI run/attempt, required CI jobs, deployment workflow run, and current `main` tip, extracts the tested tarball, and runs self-contained validation against `docker compose config --format json` (requiring `production.env` mode `0600`, byte equality with candidate `.env`, `LOG_PURGE_ENABLED=false`, all pinned candidate environment values in the effective `backend`/`celery_worker`/`celery_beat` environments, non-symlink safe bind mounts inside the portal root, mounted TLS `fullchain.pem`/`privkey.pem`, and mounted JWT signing keys). It then checks stateful Compose resources and Alembic heads, builds from the tested source, and takes encrypted application and Grafana database backups before activation. Finally, it swaps the frontend index atomically and checks running images, public readiness, and served HTML, JavaScript, and service worker hashes. Success advances `current` and writes `DEPLOYED` with `Status: Deployed — Formal Acceptance Pending` (recording the commit, CI/deploy runs and attempts, UTC timestamp, frontend asset/service-worker hashes, image IDs, and schema heads, without `PREDEPLOY.json` or `PREDEPLOY_MANIFEST.json`). Failed activations follow the [rollback procedure](#rollback). Optional post-release formal acceptance follows [POST_RELEASE_ACTIONS.md](POST_RELEASE_ACTIONS.md#operational-and-final-acceptance-gates).

### Forward097 incident reconciliation (read-only review, 2026-11-21)

The initial incident review was read-only. On 2026-11-21, the deployment workflow was temporarily enabled for one exact incident-replacement dispatch, then disabled after the host guard failed before activation. Production containers, database, and original incident evidence remain unchanged. The reconciliation code leaves the original `forward097.*` files untouched and, only after a verified replacement, records their SHA-256 values and filesystem metadata in a root-only receipt.

| UTC observation | Evidence and interpretation |
| --- | --- |
| 2026-11-19 11:19:32.201885723 | `forward097.used` records the one-use `093`→`097` permit bound to `9da0010`, CI run `44506276841`, and deploy run `44513571888`. |
| 2026-11-19 11:21:48–11:21:51 | Deploy run `44513571888` reached schema `097`, then failed its readiness check (HTTP 503) at 11:21:48; the failed run and durable `forward097.attempt` are timestamped at 11:21:51. |
| 2026-11-19 11:59:04.914351773–11:59:06.772364748 | `forward097.reopen-commit` and `forward097.recovery-attempt` record a serving commit and recovery phases. Those records do not establish that the image now running is the same image, and there is no final `DEPLOYED` receipt for the current `60be439` release. |
| 2026-11-20 11:14:54–11:18:58 | The current `60be439` release files were staged, backend/worker/beat containers started at 11:18:42, and Nginx at 11:18:58. Available host logs show direct root SSH sessions during this interval but do not identify a named operator; sudo/audit records do not provide an attributable deployment trail. |
| 2026-11-20 11:37:51 | CI run `44726033272` for `60be439` completed failed; its two backend test shards failed. GitHub has no Production deployment record for that SHA. |
| 2026-11-21 09:43:46–09:43:51 | One-time replacement run `44890936085` failed before activation. The host entrypoint looked for `merge_base` in GitHub's compare response; the API field is `merge_base_commit`. A read-only recheck confirmed the old `60be439` runtime, schema `097`, original marker hashes, and passing replacement preflight. No backup, migration, container switch, or reconciliation receipt was created by this run. The workflow was disabled again. |

Accordingly, `60be439` is classified **UNATTESTED**. Its image is present and was observed running against schema `202605310097`, but the required deployment authorization/receipt chain is absent. Preserve that release directory, image, and all incident records; do not add a retroactive receipt or label the historical deployment authorized. The earlier `9da0010` recovery records are preserved as historical evidence, not treated as proof of the running `60be439` image.

The earlier same-schema recovery candidate `65308a2af263cd59e90276b3a771d4ed6ecbf842` passed CI run `44734573582`, but its archive predates the patched proxy image and still selects Nginx `1.25`; it is not an activation-ready release. Current `main` is `5f032409bf997914dfa8f288a551cb4d7b11efe5`. It contains the compare-response correction, the file-based backup-key contract, migration `202605310098`, PostgreSQL 19, and the patched Nginx `1.30.7` image. Production remains on PostgreSQL 18.6/schema `097`, Nginx `1.25.5`, and has the old `BACKUP_ENCRYPTION_PASSWORD` variable set in its protected environment file. Exact-main CI run `44905570008` was queued at the 12:50 UTC inspection, then completed successfully at 14:14:15 UTC; the run timing and retry details are recorded below. A read-only host comparison at 12:50 UTC found that `/usr/local/lib/garrison-release/forward097_reconcile.py` matches reviewed source hash `3ac4db8f436b77f4b1208af24b714e05f0c2b0350f0d63e07447e65069b3c98c`, while `/usr/local/sbin/garrison-deploy` is still hash `2878a1f485f5bcdf70bd175b8806dc8a987ec3ad7883e5563b2a357289ab7f62` and differs from main's `8219aedee28fe9f1193a07b2e0a725958745a323f4811416077d2b0d3210008a`. The original `forward097.attempt` remains present; there is no `DEPLOYED` file for the active release and no `forward097.reconciled.json`. No root-owned backup-key file under `/opt/garrison-portal` or Garrison backup/recovery systemd timer was found. The newest `*.sql.gz.enc` file located under `/opt/garrison-portal/recovery` is dated 2026-11-12; it does not prove a current independent database-and-object recovery set. Off-host publication and restore evidence remain unverified. Do not use current `main` as a same-schema incident replacement: it also changes the PostgreSQL major version and schema. Treat incident replacement and the PostgreSQL 19/migration `098` release as distinct operations, with data recovery and rollback verified before stateful migration.

The one-time `incident-replacement` mode is root-controlled and serialized by `deploy.lock`. The installed `/usr/local/sbin/garrison-deploy` and reconciliation helper must be compared to the reviewed source before use; retain their prior copies and hashes. The deployed workflow previously failed closed on the compare-response field mismatch above. The correction reading `merge_base_commit` is now on `main`, and focused tests passed on the merged branch, but the exact current-main CI run is still queued and the updated root entrypoint has not yet been verified as installed. Ordinary candidate releases require the root-owned backup-key file; the old environment-password contract is accepted only by the bounded incident-replacement mode. The replacement also generates an incident-only Nginx Compose override pinned to the reviewed `1.30.7` digest, runs `nginx -t`, checks the activated version, and confirms the old vulnerable container is gone. Before any one-time dispatch, recheck original record hashes and exact predecessor image/schema, failed predecessor CI and absence of a GitHub Production deployment record, take the normal pre-activation backups, force a new backend image build, forbid migration, and use the existing same-schema rollback path. After `current` points to the verified replacement, the root helper checks the `DEPLOYED` receipt, exact image IDs, backend/worker/beat identities, Celery ping and beat startup, schema `097`, public readiness, and served asset hashes. It then exclusively creates `forward097.reconciled.json`; it never removes `forward097.attempt`, edits historical receipts, or closes the incident unless all checks pass. A later normal release may proceed only while both the original marker and a valid reconciliation receipt remain present. If any check fails, keep CD disabled and the original evidence intact.

The current release workflow is manually disabled. Keep it disabled until the corrected reconciliation guard is on `main`, that exact SHA's CI passes, and the updated root entrypoint is installed under the deployment lock. For recovery, enable the workflow only for the fixed incident-mode dispatch from current `main`; do not rely on a delayed automatic deployment. Leave normal CD enabled only after replacement health and incident receipt verification. The replacement is a routine same-schema image release; it is not a migration or a restoration of the database.

### CI runner isolation and availability

CI runs on isolated self-hosted Linux x64 runners tagged `garrison-ci`, with separate Docker-in-Docker fixtures and persistent pip/npm caches. Browser shards use Google Chrome only. CI receives no production secrets, production Docker socket or production volumes. The Hostinger `garrison-production` runner remains dedicated to deployment and must never be used as a general CI fallback.

### CI runner availability — 2026-11-21

At 12:50 UTC, the GitHub runner API showed all four `garrison-ci` runners offline while the separate `garrison-production` runner was online; all seven jobs in exact-main run `44905570008` for `5f032409bf997914dfa8f288a551cb4d7b11efe5` were queued. The existing local registrations for `garrison-ci-desktop` (ID 22) and `garrison-ci-linux-3` (ID 25) were restarted with their isolated Docker-in-Docker daemons. Registration `garrison-ci-linux-2` (ID 24) was then restored from its existing credential state and isolated daemon. As of 14:24 UTC, IDs 22, 24 and 25 were online; ID 23 remained offline because its separate Docker-in-Docker container repeatedly exits on a stale daemon PID file. Its Docker data volume was preserved. Do not route jobs to the production runner.

A hosted-runner fallback was tested on PR #39 (`283713cab3f892b2f5ffe77aa58d3ddd28efadca`, run `44907543620`) but GitHub rejected job startup because of account payment/spending-limit restrictions. No steps ran, so this is not a test result. The repair commit `f47d1941df72d30b3d0ca34f75da56f37e2eece2` keeps isolated self-hosted CI and passed all seven required jobs in run `44912557531` at 14:30:07 UTC. That run took 19m34s from dispatch to completion; the first job started three seconds after dispatch. Hosted CI remains unavailable until the account restriction is resolved.

### Review pipeline time on every release

Compare the exact candidate's Actions run with recent runs that cover the same tests. Record queue time, elapsed CI time, the slowest job and steps, cache hits, and total runner time. Pytest reports its ten longest tests and the browser jobs log individual test durations. Look for independent work to run in parallel, repeated setup, and avoidable rebuilds. Record a measured result after each change and confirm the same required checks and test coverage ran.

### Prior self-hosted CI measurements

The following runs provide comparable baseline timings for the active self-hosted
`garrison-ci` workflow. The hosted fallback attempt was stopped before job startup
by an account billing restriction, so it produced no timing or test evidence.

Incident candidate `65308a2` passed all seven required jobs in self-hosted CI run
`44734573582` in 30m23s; its first job started 25 seconds after creation. The exact
current-main run `44748642997` on `573de5d` also passed all seven jobs in 31m33s
(13:55:46–14:27:19 UTC). Its first job started three seconds after creation; the
backend shards took 5m42s and 6m26s, and the Chrome shards 8m06s and 8m47s. Summed
job elapsed time was about 31m15s, close to wall time. The runner API then showed one
of four `garrison-ci` runners online, with the Production runner online. Restoring
the three offline CI runners is the clearest evidence-based speed opportunity; do
not raise the tested integration concurrency cap or remove required jobs to hide
runner scarcity. This run verifies current `main` CI, not the fixed `65308a2` recovery
artifact or any uncommitted reconciliation changes.

The next exact-main run, `44829172951` on `d7022e9`, passed all seven jobs in 17m49s
(22:28:00–22:45:49 UTC). The first job started after three seconds; summed job
elapsed time was 30m28s. Backend tests took 5m05s and 6m22s, while Chrome took
7m49s and 9m05s. The browser JUnit reports contain 83 tests with 407.4s and 479.8s
of case time across the current shards. Based on those measured case durations,
five existing `business-roles` tests totaling 37.6s in this run were moved from the
complement shard into the checked-in shard list; projected case time is 445.0s vs
442.2s. This is a balancing estimate, not a measured wall-clock saving. The next
CI run must confirm both complementary selections still execute all tests exactly
once and measure the result before claiming a speedup. Setup remained short in this
run (pip install 4s, npm install 8s); persistent self-hosted caches, same-ref
cancellation, and the two-job integration cap are already in place, so no cache or
parallelism change is justified by this run alone. The exact-main run does not
verify the current uncommitted application changes.

A runner inventory at 12:50 UTC on 2026-11-21 showed zero of four `garrison-ci`
runners online. Three isolated registrations were restored. Exact-main run
`44905570008` on `5f032409bf997914dfa8f288a551cb4d7b11efe5` completed successfully
at 14:14:15 UTC with all seven required job conclusions successful. It required
three attempts: previously successful jobs were retained while failed jobs were
rerun. The workflow was created at 12:46:34 UTC; the first job did not start until
13:23:39 UTC (37m05s queued), and the run completed after 1h27m41s. Summing the
successful job intervals gives 31m34s, with the slowest job taking 8m49s. This
elapsed time includes the initial runner outage and retries and is not a steady
state benchmark or a measured speedup.

The isolated self-hosted repair commit `f47d1941df72d30b3d0ca34f75da56f37e2eece2`
passed all seven required jobs in PR run `44912557531` in 19m34s (14:10:33–14:30:07
UTC); its first job started three seconds after dispatch. Backend shards took
5m36s and 7m52s, Chrome shards 9m59s and 10m10s, frontend checks 1m21s, backend
lint/types 56s, and Compose validation 27s. Three isolated registrations were
available. The two Chrome shards ran concurrently with one Playwright worker each;
at the observed peak the runner containers used about 2.2 GiB and 3.5 GiB and about
two CPU cores each. Keep the integration concurrency cap at two until comparable
measurements show that raising it improves wall time without memory or test
stability regressions. These runs verify CI only; they do not clear the production
incident or recovery gates. No workflow speedup is claimed from these runs because
the exact-main comparison includes runner outage/retries and the prior run used a
different runner-availability state.

The backend suite and Google Chrome browser suite each run in two complementary shards with separate PostgreSQL, Redis and object-storage services. Integration concurrency remains capped at two while the recovered runner pool's capacity is measured; all four shards remain required. Each job starts its pinned Moto container alongside dependency installation and applies migrations to its own database before testing. The [CI workflow](../.github/workflows/ci.yml) assigns browser tests by measured duration. One shard uses the checked-in test selection and the other runs its complement, including newly added tests. Each browser shard uses one worker to avoid oversubscribing a runner; each browser test uses its own context, synthetic accounts and project data. Runners reuse Google Chrome when available and install Chrome only when necessary while building the production bundle. They still type-check the browser tests, and the required frontend job type-checks the application. Persistent pip/npm caches reduce repeated dependency downloads. Local `pytest` and `npm run test:browser` still run the full suites by default. The release receipt requires success from all four shards.

Backend sharding assigns whole test modules using measured runtimes for the slowest modules and case counts for the rest. If shard timings diverge across comparable runs, sum JUnit case times by module from both backend reports before adjusting the estimates in [the pytest configuration](../backend/tests/conftest.py).

The backend reports from HR checkpoint CI run `43902036278` recorded
168.53 and 252.95 seconds of test time. The refreshed module weights
project 211.15 and 210.34 seconds using those same case timings. Local
collection verified that the new assignments cover all 916 cases once.
Compare runner wall time on the next CI run before recording a speedup.

On `21750a2`, self-hosted CI run `44029735679` passed in 13m 02s.
Chrome test steps took 425s and 409s across 34 and 36 cases. Backend test
steps took 204s and 209s. The Chrome shards are close in elapsed time, and
`business-roles.e2e.ts` accounts for 518s of their combined JUnit case
time. Measure fixture startup and repeated sign-in within that suite before
adjusting the shard split again. The deployment step took 100s in run
`44031348063`.

Fourteen Chrome scenarios now seed their shared-project accounts in one
command per scenario, avoiding 27 Python launches. In five local runs per
mode, the median time to seed four accounts was 1.526s with separate
commands and 0.391s with one command. Compare the Chrome job wall time on
the next self-hosted run to measure the pipeline impact.

For browser rebalancing, sum JUnit case times across both reports. The first
Chrome shard uses [a Playwright test list](../frontend/e2e/ci-shard-1.txt).
The second runs its complement. After editing the list, verify with
`playwright test --list` and the two selectors `--test-list` and
`--test-list-invert` that every test appears exactly once.

The HR checkpoint ran all 62 Chrome scenarios without skips. The existing
shards totaled 179.56 and 525.22 seconds of test time. Moving seven HR
scenarios to the first shard projects 353.01 and 351.77 seconds using the
same timings. Local collection verified the new 30/32 split. These are
projected test-time totals. The next self-hosted run will measure elapsed
time with the new assignments.

The subsequent 67-case local Chrome run took 2.7 minutes with two workers.
Applying the existing selectors to its case durations gave 134.0 and
170.6 seconds. Moving the payroll browser workflow to the first selector
projects 149.6 and 155.0 seconds from the same measurements. Collection
verified a disjoint 31/36 split covering all 67 cases. Measure the next
self-hosted run before drawing conclusions about wall time.

The 68-case payroll-policy candidate ran locally in 3.0 minutes with two
Chrome workers. The previous selectors account for 163.51 and 178.73 seconds
of JUnit case time. Moving the manager recommendation scenario, measured
at 7.89 seconds, projects 171.40 and 170.84 seconds. The final lists cover
33 and 35 cases. The latest measured self-hosted CI on published
`c4a61cd` was 737 seconds elapsed, with the longest browser job at
326 seconds and longest backend job at 298 seconds. Compare the new
selectors on the next self-hosted run before claiming a wall-time gain.

The pre-rebalance baseline is CI run `43504480104` on `c50de62e4fbb2c57426d208e38e787421ac96f90`: 209 seconds wall time; browser shard 1 took 148 seconds and shard 2 took 204 seconds. Their browser-test steps took 74 and 104 seconds. JUnit case-time sums were 127.23 and 180.53 seconds; `project-setup.e2e.ts` contributed 24.89 seconds on shard 2. The first rebalance on `00b38884c450ac699cbc8039b522044e05fff1ca` passed all checks but did not improve measured CI wall time: it took 214 seconds, with browser jobs at 210 and 159 seconds and test steps at 120 and 64 seconds. Its JUnit sums were 205.96 and 106.06 seconds. The second rebalance on `9f7a543c5b637109f735709cbe27a59910b2f6c7` passed all required checks in 195 seconds wall time; browser jobs took 150 and 193 seconds, with test steps at 72 and 114 seconds and JUnit case-time sums of 126.98 and 202.26 seconds. The third rebalance on `d79f4f47534e5d726fa258befa3c6b496d506cca` passed all checks in 178 seconds; browser jobs took 142 and 175 seconds, with test steps at 74 and 93 seconds and JUnit case-time sums of 132.11 and 155.90 seconds. The fourth rebalance on `f81e369bce759aef93e172f60bde1552d0d53f9f` passed all checks in 170 seconds; browser jobs took 166 and 152 seconds, with test steps at 90 and 77 seconds and JUnit case-time sums of 161.70 and 125.54 seconds. This run was 39 seconds shorter than the baseline, but measurements vary substantially between runners and the single-run difference is not proof of a repeatable speedup.

Run `43532349807` on `3a14193c417759f2dfba82ada81c07be6e4c1daa` passed all CI jobs in 206 seconds wall time. Browser jobs took 202 and 130 seconds; JUnit case-time sums were 201.91 and 100.30 seconds. `media-documents.e2e.ts` contributed 57.01 seconds on shard 1. Moving it to shard 2 produced run `43533754801` on `824bf5ade60b0104b6dd1b0c12d2cf2b0cda834c`: all CI jobs passed in 170 seconds wall time, browser jobs took 151 and 157 seconds, and JUnit case-time sums were 122.44 and 147.09 seconds across 20 and 14 tests, with zero failures or skips. The slowest browser job fell by 45 seconds and overall wall time by 36 seconds; total JUnit case time also fell by 32.68 seconds, so runner and test-time variation mean that one run does not establish a repeatable 36-second saving. The same split passed again on `074705cac8f2ba987f00314e7c851a6a4de94d0d` in run `43534240845` (188 seconds wall time), with browser jobs at 142 and 185 seconds and JUnit sums of 129.55 and 159.11 seconds; all 34 tests passed without failures or skips. Across these two comparable runs, shard means were 126.00 and 153.10 seconds. Moving `approval-delegation.e2e.ts` (16.59-second mean) to shard 1 projected 142.59 and 136.51 seconds. Exact-main run `43534831860` on `ab85afbf29857de2b038f8296daeef7816fd7043` passed in 181 seconds; browser jobs took 179 and 141 seconds, with JUnit sums of 161.25 and 114.96 seconds across 21 and 13 tests, zero failures and zero skips. The measured split moved the skew to shard 1, opposite the projection. Given the run-to-run changes in individual file durations, keep required coverage and collect another comparable run before tuning again or claiming a repeatable speedup. CI caches and same-ref cancellation remain enabled; no checks or browser platforms were removed.

The next exact-main run, `43535437953` on `8d23dbe949696e7cd4e9ad0ad925f9d99c8ce256`, passed in 186 seconds wall time. Browser jobs took 129 and 182 seconds; their test steps took 60 and 95 seconds. JUnit sums were 106.16 and 162.54 seconds across 21 and 13 tests, with zero failures or skips. Moving `finance-workflows.e2e.ts` (23.41 seconds) and `import-workflow.e2e.ts` (9.29 seconds) to shard 1 projected 138.86 and 129.84 seconds. Run `43536923181` on `fc6b204d1b87d225d08a762c815e1c42d175f7e3` passed in 213 seconds wall time with browser jobs at 209 and 166 seconds. Its JUnit sums were 208.76 and 128.11 seconds across 24 and 10 tests, zero failures and zero skips. Applying that run's per-file times to the prior assignment projects 173.26 and 163.60 seconds; this reverses the apparent balance. The prior assignment was restored and run `43537489987` on `d63d24e029fb16c3b24e7eb9ce688807d51870e9` passed in 202 seconds wall time. Its browser jobs took 190 and 200 seconds, with JUnit sums of 178.43 and 196.69 seconds across 21 and 13 tests, zero failures and zero skips. The closer job durations support keeping this split for now, but test-time variation across runs means there is still no proven repeatable wall-time saving.

Exact-main run `43542078874` on `af456c4e5ea618a197768fc2b0c3a9829ea7f794` passed in 171 seconds wall time (about 2 seconds queued); summed job elapsed time was 699 seconds. Browser jobs were longest at 168 and 141 seconds, including 75/72-second browser-test steps and 47/44-second dependency-and-service setup. Backend test jobs took 152/140 seconds, including 95/84-second pytest steps and 34 seconds of setup each. Backend lint/types took 45 seconds, frontend checks 25 seconds, and Compose validation 28 seconds. The run logs confirm pip/npm cache hits. Independent jobs and shards are already parallelized and measured splits are close; this run does not support reducing parallelism or removing a required check for a wall-time gain. The associated production workflow `43542354832` was skipped because the trusted predeployment gate was not ready.

The next exact-main run, `43547184830` on `5e28db89665bcbc7575ce118a9abf5d96224640d`, passed in 174 seconds wall time; summed job elapsed time was 740 seconds. Browser jobs took 161/171 seconds, with 79/89-second test steps and 53/55-second setup. Backend test jobs took 158/137 seconds, with 105/75-second pytest steps and 32/35-second setup. Backend lint/types took 45 seconds, frontend checks 49 seconds, and Compose validation 19 seconds. This is 3 seconds slower than the preceding run, while the browser and backend job ordering changed; the single-run variation does not show a pipeline regression or justify a speculative shard change. Preserve the current checks and parallel layout, then compare more runs before claiming a repeatable saving. The corresponding production workflow `43547450409` was skipped by the same trusted predeployment gate.

The latest exact-main CI timing sample, run `43547650068` on `3a1c168516052a8adcdcde348f90e730ad0faa11`, passed all required CI jobs in 183 seconds wall time; summed job elapsed time was 728 seconds. Browser jobs took 155/180 seconds, with browser test steps at 67/91 seconds and dependency/storage preparation at 48/56 seconds. Backend test jobs took 167/139 seconds, with pytest at 105/79 seconds and preparation at 37/36 seconds. Backend lint/types took 44 seconds, frontend checks took 26 seconds, and Compose validation took 17 seconds. Compared with the prior sample, wall time was 9 seconds slower while summed job time was 12 seconds lower; the frontend job was 23 seconds shorter, but this single run does not establish why or prove a repeatable saving. Keep the current shard assignment, caches and parallel checks until comparable runs show a stable opportunity. The production workflow remained gated and did not deploy.

The first CI run after adding the stricter runtime-configuration check, `43552941649` on `362163bfb9a2b439de3b88d22b91adae752dd0ca`, took 185 seconds wall time and 698 summed job seconds. Six jobs passed; backend mypy found seven typing errors in one new test fixture. Browser jobs took 167/182 seconds, backend test jobs 121/139 seconds, frontend checks 27 seconds, and Compose validation 18 seconds. The failure was test-fixture typing, not a runtime or shard regression; the fixture annotation and `None` return assertion have been corrected for the next exact-SHA run. No CI checks were removed or weakened.

The corrected exact-main run, `43553321898` on `f296c7364d2537de8002a7bbfbc37e1a68b79610`, passed all required jobs in 181 seconds wall time; summed job elapsed time was 712 seconds. Browser jobs took 167/177 seconds, with browser-test steps at 83/87 seconds and dependency/storage preparation at 57/55 seconds. Backend test jobs took 162/107 seconds, with pytest at 90/53 seconds and preparation at 37/23 seconds. Backend lint/types took 32 seconds, frontend checks 44 seconds, and Compose validation 23 seconds. Compared with the preceding successful sample, wall time was 2 seconds faster and summed job time 16 seconds lower; this does not establish a repeatable saving. CI preserved its existing bundled-Chromium test coverage. The production workflow remained skipped by the unset trusted predeployment readiness gate.

The exact-main run `43555987614` on `0a3ac92a4b2b58ee7eb8c900e4f8843db02178c1` passed in 170 seconds wall time; summed job elapsed time was 666 seconds. Browser jobs took 167/148 seconds, including 86/72-second test steps and 55/48 seconds of dependency/storage preparation. Backend test jobs took 142/120 seconds, backend lint/types 43 seconds, frontend checks 30 seconds, and Compose validation 16 seconds. Compared with the preceding exact-main run `43553776518` (190 seconds wall, 708 summed job seconds), this sample was 20 seconds faster wall-clock and 42 seconds lower summed time. The workflow itself did not change, so this single run does not establish a repeatable optimization. The browser shard remains the critical path; test and setup work already run in parallel with required checks. Keep the current coverage and shard split until repeated per-test timings show a stable, evidence-backed improvement. Production deployment was skipped because `GARRISON_PREDEPLOY_GATE_READY` remains unset.

The docs-only run `43556574836` on `b45aed6fb8e8c5efbe1edb33eac564a728173946` passed after retrying one failed backend shard. Its first attempt took 182 seconds and failed the `schema-change` entrypoint case; the failed-shard retry passed 332 tests in a 171-second job. The test double returned before reading the Compose JSON piped to it, creating a race that could close the producer pipe early and surface the wrong guard. The fixture now drains stdin like the real validator. The focused file passes 50 tests and the affected scenario passed 10 repeated runs locally. The queue delay plus retry made that iteration longer than a normal run, so do not use its full elapsed time as a pipeline performance baseline. No CI checks or workflow steps were changed.

The corrected exact-main run `43557559326` on `9291c65d82cb051b5f39f5dd7f40e2a3bac37666` passed all seven required jobs in 183 seconds wall time; summed job elapsed time was 733 seconds. Browser jobs took 180/159 seconds, with test steps at 93/77 seconds and dependency/storage preparation at 57/43 seconds. Backend test jobs took 161/143 seconds, backend lint/types 38 seconds, frontend checks 36 seconds, and Compose validation 16 seconds. The wall time was 13 seconds higher than `43555987614`; this changed test fixture and graph/docs metadata, not CI workflow behavior, so the difference is not a demonstrated regression or improvement. Browser and setup phases remain the longest path and already run in parallel. Keep all required checks and compare more runs before proposing a workflow change. The production workflow remained skipped by the unset predeployment readiness gate.

Exact-main Chrome evidence is available from CI run `43612280234`, SHA `b2a2411fbffcbc3faccbbac52a33a11d38b8c79c`, attempt 2: all 34 browser cases passed on Google Chrome 157.0.8103.78 (21 and 13 across the shards, zero failures/errors/skips). The browser-test steps took 96 seconds per shard. Attempt 1 failed five browser cases and killed one worker under concurrent load; attempt 2 reran the failed browser jobs successfully. The successful attempt took 299 seconds, but it reused successful jobs from attempt 1, so that is not a full-run wall-time comparison. Attempt 1 ran 563 seconds before failing. The Chrome package is installed separately in each browser job; dependency/storage preparation took 42 and 158 seconds on attempt 2. A runner image with Google Chrome and its system dependencies preinstalled is the next measured optimization candidate. Keep the first-attempt flake visible; exact-source Chrome evidence is green, while named QA approval, business workflow UAT, degraded-network evidence, and formal production acceptance remain outstanding.

For deployment, measure runner queue time separately from the host phase timings. The host builds the tested archive using Docker's layer cache and reuses the running backend image when only tests, backend documentation or frontend files change. The release script reads the frontend hashes in one container and checks the served bytes after activation.

CI run `43586029198` on `2a0cf6e5d82654f32c1831ac2c8ee48ab87321a8` is a failed, partial measurement, not a release baseline: backend Mypy exited with `INTERNAL ERROR`, while browser shard 1 passed. Its self-hosted `setup-python` step spent 10m02s timing out during GitHub pip-cache restoration; `setup-node` restored an 82 MiB npm cache in 90 seconds. The Python and Node tool runtimes were already present locally. CI now uses persistent runner-local caches at `/runner/state/pip-cache` and `/runner/state/npm-cache` instead of remote package-cache actions.

The next exact-main run, `43587573918` on `95e0f64e1edd578722a064027e76053f7e3933d8`, passed all seven required jobs in 394 seconds wall time, with about 13 seconds before the first jobs started. Browser shard jobs took 166 and 336 seconds; the slower shard spent 182 seconds preparing dependencies/storage and 103 seconds in browser tests. The other shard's preparation took 22 seconds and its browser tests 106 seconds. Backend tests took 288 and 153 seconds, frontend checks 57 seconds, backend lint/types 49 seconds, and Compose validation 25 seconds. The remote cache restoration timeout did not recur, though this single run does not establish a stable wall-time improvement; the third runner was cold and its dependency setup was the main remaining variable. Keep the three self-hosted runners and local caches, then compare the next warmed exact-main run before changing shard assignments or required coverage.

The next exact-main run, `43599068234` on deployed SHA `3b225fb0aa96929d7a6e339f1e969b32f94d0436`, passed all seven CI jobs in 349 seconds from workflow start to completion; the first runner job started 24 seconds after the run began, and summed job elapsed time was 831 seconds. All jobs used the self-hosted `garrison-ci` runner group. Backend test jobs took 267/149 seconds, with pytest steps at 225/106 seconds; browser jobs took 147/142 seconds, with browser-test steps at 93/90 seconds and dependency/storage preparation at 16/14 seconds. Frontend checks took 55 seconds, backend lint/types 37 seconds, and Compose validation 34 seconds. Compared with run `43587573918`, wall time fell 45 seconds and summed job time fell 243 seconds; most of the browser setup difference was the prior cold-runner 182-second preparation falling to 14 seconds, so this is not a measured workflow-code speedup. Cache hit/miss counts were not present in the Actions job logs. The backend JUnit reports show `test_capture_recovery_wrapper.py` consumed 168.58 seconds across 21 cases on shard 1, versus 185.75 seconds in the prior run, while `conftest.py` still assigned it 21.5 seconds. The local estimate is now 177.2 seconds, the rounded two-run median. On the clean release source with that estimate, collect-only verification selected all 769 tests exactly once (21 capture-wrapper cases on shard 1; 748 other cases on shard 2), with no overlap or omission after normalizing one timestamp-dependent test ID. The current JUnit case-time partition projects the slowest shard falling from 219.28 to 168.58 seconds, roughly 51 seconds, but that gain remains unverified until the next self-hosted CI run executes the changed assignment. Required coverage and browser platforms remain unchanged.

The latest exact-main sample, CI run `43616779674` on `9aa8f2316de9682af5b6d046eeb8f884f4f0c532`, passed all seven required jobs. It took 898 seconds from workflow start to completion; summed job time was 850 seconds. Backend test jobs took 215/197 seconds, browser jobs 166/157 seconds, frontend checks 54 seconds, backend lint/types 36 seconds, and Compose validation 25 seconds. Both Chrome shards passed (21 and 13 cases) on Google Chrome `157.0.8103.78`. The Compose job has no `needs` dependency, but it did not start until 16:53:50 UTC, 14 minutes 33 seconds after the workflow began; this is a runner scheduling delay, not serial workflow design. At the 17:35 UTC runner API check, only `garrison-ci-linux` and `garrison-ci-linux-3` were online; `garrison-ci-linux-2` and `garrison-ci-desktop` were offline. The next measurable speed action is restoring reliable runner availability; changing YAML or reducing checks is not supported by this run. Production deploy run `43618140992` succeeded. Readback confirmed release `9aa8f2316de9682af5b6d046eeb8f884f4f0c532`, readiness `ready`, database `connected`, Alembic `202605310006 (head)`, and `garrisonctl health check` outcome `success`.

The HR release candidate `be61f5b74ce9701ba83f70261b03fe6219bd2d72` passed all required self-hosted CI jobs on attempt 2 of run `43708858463`; production deployment run `43717032813` succeeded. The first attempt took 465 seconds wall time; the successful retry completed 618 seconds after workflow creation. Summed runner job time was 941 seconds on attempt 1 plus 138 seconds for the retry (1,079 seconds total). Attempt 1's backend shards took 194/220 seconds and browser shards took 172/212 seconds; successful browser shard durations were 138/212 seconds. One Chrome browser shard failed during an upload-receipt/stale-revision poll and passed on retry. The logs did not expose cache hit/miss telemetry. Compared with prior exact-main run `43616779674` (898 seconds wall time, 850 seconds summed job time), this run finished 280 seconds sooner by wall clock but consumed 229 more runner seconds across both attempts. The earlier run had a 14-minute-33-second scheduling delay before Compose validation; the latest run's first jobs started three seconds after workflow creation. That points to recovered runner scheduling rather than a measured workflow-code speedup, and the retry further limits comparison. The integration matrix stays capped at two concurrent jobs because a third concurrent test job has exceeded shared-host capacity; this single run does not justify raising that cap or changing the shard split. Investigate and compare the upload-receipt polling failure across future exact-SHA runs before changing browser sharding or concurrency. Keep all required checks and the Chrome-only UAT scope unchanged.

The next HR recruitment candidate, `f322d81059a679b982e72527e212e735b4ccc5de`, passed all seven required self-hosted CI jobs in run [43735043858](https://github.com/nirzaf/garrison-investments/actions/runs/43735043858). Workflow wall time was 787 seconds (13m07s), with the first job starting six seconds after workflow start; summed job elapsed time was 1,472 seconds. The backend shards ran 875 tests total with zero failures or skips; pytest took 265 and 392 seconds, with JUnit case-time sums of 253.18 and 380.80 seconds. The 21 `test_capture_recovery_wrapper` cases made up the first shard and consumed 253.18 seconds, versus the configured estimate of 177.2 seconds. Browser shards passed 29 and 23 Chrome cases with zero failures or skips; test steps took 104 and 143 seconds. Frontend checks took 87 seconds and ran 50 Vitest tests; backend lint/types took 46 seconds. The Compose job took 136 seconds, including a 108-second shallow Git fetch in `actions/checkout`; that fetch is the clearest measured speed investigation, but one run does not establish whether the delay is repeatable or repository-transfer related. Check the runner/network and checkout logs on the next comparable release before changing checkout safety or caching. The backend shard timings also diverged; compare another JUnit report before adjusting module weights. No required checks were removed or weakened. Deployment run [43736276674](https://github.com/nirzaf/garrison-investments/actions/runs/43736276674) stopped at the pre-activation migration guard for pending revision `202605310014`; production was not activated by that run.

### Host bootstrap and runner maintenance

Provision the existing stack and an initial active release before registering the production runner. The script expects the project `garrison-portal`, an active release under `/opt/garrison-portal/releases/`, and the `garrison-portal_frontend_dist` volume. Under `/opt/garrison-portal/deploy/`, keep the following root-controlled.

| Host item | Purpose |
| --- | --- |
| `production.env` | Private configuration (`0600`, root-owned) copied into each candidate release; must set `LOG_PURGE_ENABLED=false`. |
| `compose.vps.yml` | Existing stateful resource names, TLS and JWT key mounts, and host-specific Compose overrides. |
| `current` | Symlink to the last verified release containing `.env`, `.images.env`, `SOURCE_COMMIT`, `READINESS.json`, and `DEPLOYED`. |
| `deploy.lock` | Host-side serialization lock across release attempts and operator entrypoint updates. |

Ensure TLS certificates (`fullchain.pem` and `privkey.pem`) and JWT signing keys (`jwt_private_key` and `jwt_public_key`) are stored in root-controlled paths under `/opt/garrison-portal` (without symlinks or group/world write permissions) and mounted by `compose.vps.yml`. Optional formal-acceptance files (`authorized-configuration.json`, `approval-trust.json`, or private closure bundles) are not read or required by `/usr/local/sbin/garrison-deploy`.

The host operator installs the reviewed [host release script](../deploy/hostinger-release.sh) as root-owned `/usr/local/sbin/garrison-deploy` with mode `0755`. The runner needs noninteractive `sudo` only for `/usr/local/sbin/garrison-deploy`. Both workflow and host must use the `rollback-v2 technical-checks-v1` protocol arguments. Because `/usr/local/sbin/garrison-deploy` runs as `root`, never copy an unreviewed script directly into place during a workflow run; use the explicit operator procedure below whenever updating the host entrypoint:

1. **Quiesce and lock:** Confirm no GitHub Actions deployment job is queued or running, verify your checked-out commit SHA (`git rev-parse HEAD`), and acquire `/opt/garrison-portal/deploy/deploy.lock` (`exec 9>/opt/garrison-portal/deploy/deploy.lock && flock -w 60 9`).
2. **Validate the reviewed candidate script:** Confirm `bash -n deploy/hostinger-release.sh` succeeds and record its exact source digest (`sha256sum deploy/hostinger-release.sh`). Compare `sha256sum /usr/local/sbin/garrison-deploy` with the existing installed copy.
3. **Preserve a rollback backup:** Copy the existing host binary to a timestamped backup inside a root-owned recovery directory with its recorded SHA-256 digest before replacing it:

```bash
install -d -o root -g root -m 0755 /opt/garrison-portal/recovery
backup="/opt/garrison-portal/recovery/garrison-deploy.bak.$(date -u +%Y%m%dT%H%M%SZ)"
install -o root -g root -m 0755 /usr/local/sbin/garrison-deploy "$backup"
sha256sum "$backup"
```

4. **Atomically install the updated entrypoint:** Stage with `install -o root -g root -m 0755` into `/usr/local/sbin/` and atomically rename into place:

```bash
bash -n deploy/hostinger-release.sh
sha256sum deploy/hostinger-release.sh
install -o root -g root -m 0755 deploy/hostinger-release.sh /usr/local/sbin/.garrison-deploy.next
mv -Tf /usr/local/sbin/.garrison-deploy.next /usr/local/sbin/garrison-deploy
```

5. **Verify installation and release the lock:** Confirm root ownership, permissions (`0755`), SHA-256 digest equality with `deploy/hostinger-release.sh`, and runner `sudo` policy, then release lock descriptor `9`:

```bash
stat -c '%u:%g %a %n' /usr/local/sbin/garrison-deploy
sha256sum /usr/local/sbin/garrison-deploy deploy/hostinger-release.sh
sudo -l -U garrison-actions
exec 9>&-
```

If `/usr/local/libexec/garrison-release-contract.py` was previously staged on the host solely for predeployment gating, it is no longer invoked by `/usr/local/sbin/garrison-deploy` and may be removed or kept offline for optional manual formal acceptance verification. Keep the repository variable `GARRISON_PREDEPLOY_GATE_READY` removed or unused; `deploy.yml` no longer checks it.

After activation, collect the original `DEPLOYED` file from `/opt/garrison-portal/deploy/current/DEPLOYED` and confirm its `Status`, `Commit`, `CI run`, `CI attempt`, `Deploy run`, `Deploy attempt`, image IDs, schema heads, and asset/service-worker hashes. A retry of the active SHA only checks readiness and leaves `DEPLOYED` untouched. [Optional formal acceptance receipt instructions](templates/release-closure/README.md)

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

### Emergency NGINX-only maintenance while the forward-097 hold is open

This procedure changes only the NGINX container. It does not switch the application `current` symlink, start or stop backend/worker/beat/PostgreSQL, run Alembic, edit `forward097.*`, close the incident, or enable normal CD. Run it only after the designated production confirmation codeword and under the existing deployment lock. Record actual UTC start/end times and retain the host command output.

Before activation, verify the portal VM, active release, schema `202605310097`, NGINX container ID/image/version, the exact source paths mounted at `/etc/nginx/conf.d/default.conf`, `/etc/nginx/templates/grafana.conf.template`, and `/etc/nginx/conf.d/support.conf`, the TLS mount, and the support allowlist. Hash the incident records and allowlist. Confirm `forward097.attempt` remains present. If the marker, active release, source mounts, schema, or allowlist differs from the reviewed state, stop; do not adapt the procedure by clearing the hold.

If the patched image cannot be activated immediately, `deploy/nginx_http2_mitigation.py` creates new read-only bind-mount copies of the portal, Grafana, and Super Admin configs with HTTP/2 disabled. It supports both the legacy `listen 443 ssl http2;` form and `http2 on;`; the Super Admin allowlist include and `deny all` must remain in its copied config. It never edits source files or activates containers. With the host deployment lock held and all source paths taken from the running NGINX container's actual mounts:

```bash
state=/opt/garrison-portal/deploy
current=$(readlink -f "$state/current")
nginx_id=$(docker ps --filter label=com.docker.compose.project=garrison-portal \
  --filter label=com.docker.compose.service=nginx --format '{{.ID}}')
docker inspect --format '{{range .Mounts}}{{printf "%s\t%s\n" .Source .Destination}}{{end}}' "$nginx_id"
```

Set `portal_config`, `grafana_config`, and `support_config` to the three exact source paths shown by that inspection. Use a new private output directory for every attempt; never reuse prior evidence:

```bash
umask 077
overlay="$state/nginx-emergency/http2-off-$(date -u +%Y%m%dT%H%M%SZ)"
python3 deploy/nginx_http2_mitigation.py --require-root \
  --portal-config "$portal_config" \
  --grafana-config "$grafana_config" \
  --support-config "$support_config" \
  --output-dir "$overlay"
```

Define the Compose command against the active release and host-only override. Do not print its fully rendered environment, which includes production secrets:

```bash
prod() {
  docker compose --project-name garrison-portal \
    --project-directory "$current" \
    --env-file "$current/.env" --env-file "$current/.images.env" \
    -f "$current/docker-compose.prod.yml" \
    -f "$state/compose.vps.yml" "$@"
}
```

For the HTTP/2-off fallback, validate the NGINX config with the currently running image and recreate only the proxy:

```bash
prod -f "$overlay/compose.no-http2.yml" config --quiet
prod -f "$overlay/compose.no-http2.yml" run --rm --no-deps --pull never \
  --entrypoint nginx nginx -t
prod -f "$overlay/compose.no-http2.yml" up --detach --no-deps --pull never \
  --force-recreate --wait --wait-timeout 90 nginx
```

Verify TLS without `-k`, readiness, Grafana `/api/health`, HTTP/1.1 fallback, and a denied Super Admin request. Confirm backend, worker, beat, database container IDs, schema, current symlink, marker hashes, and allowlist hash are unchanged. Keep HTTP/2 disabled until a patched NGINX version is observed running.

For the upgrade, pull only `nginx:1.30.7-alpine@sha256:caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3`. Validate the image's `nginx -v`, `nginx -t`, and image digest before activation. First start that image with the HTTP/2-off overlay. After proving NGINX 1.30.7 is active and all previous vulnerable NGINX containers/workers have exited, recreate only NGINX again using the pinned image and original HTTP/2-enabled configs. Verify HTTP/2 negotiation on the portal and Grafana, HTTPS and health, Super Admin denial from a non-allowlisted source, and unchanged allowlist bytes. The approved office/VPN source must use its own real network to verify allowed access; a synthetic local test does not prove that source reaches production.

The helper also writes `compose.patched-image.yml`. Use the two overlays together for the first activation, while HTTP/2 stays off:

```bash
docker pull nginx:1.30.7-alpine@sha256:caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3
prod -f "$overlay/compose.no-http2.yml" -f "$overlay/compose.patched-image.yml" config --quiet
prod -f "$overlay/compose.no-http2.yml" -f "$overlay/compose.patched-image.yml" \
  run --rm --no-deps --pull never --entrypoint nginx nginx -t
prod -f "$overlay/compose.no-http2.yml" -f "$overlay/compose.patched-image.yml" \
  up --detach --no-deps --pull never --force-recreate --wait --wait-timeout 90 nginx
```

After verifying the patched version, image ID, TLS and HTTP/1.1 health, enable HTTP/2 by omitting only the no-HTTP/2 overlay. Keep the pinned-image overlay:

```bash
prod -f "$overlay/compose.patched-image.yml" run --rm --no-deps --pull never \
  --entrypoint nginx nginx -t
prod -f "$overlay/compose.patched-image.yml" up --detach --no-deps --pull never \
  --force-recreate --wait --wait-timeout 90 nginx
```

If the patched image fails before activation, leave the existing proxy running and activate the tested HTTP/2-off overlay with `--pull never`. If the first replacement fails after stopping the old proxy, restore the recorded old image **with the HTTP/2-off overlay**. Never restore HTTP/2 on a vulnerable image. If re-enabling HTTP/2 fails after the patched image is verified, keep the patched image with HTTP/2 off and report that partial result. Preserve the overlay, image IDs, hashes, command output, health results, actual UTC timestamps, and the untouched incident markers. This proxy-only procedure does not reconcile the forward-097 hold.

For the first owner-aware offline rollout, stop the previous Celery beat and worker and drain active application writes before migration. Keep an ingress write block in place through activation and the read-only smoke checks. The deployment probe needs GET access to the sign-in page, frontend entry asset, service worker, and readiness endpoint. Remove the block after verifying the new application and worker and confirming no legacy writers are running.

### Upgrade PostgreSQL 18 to 19.0

The runtime and CI use the official [`postgres:19.0-alpine3.24` image](https://hub.docker.com/_/postgres)
pinned to multi-platform manifest digest
`sha256:8b0ff4cdf221f0c53d7fcda681d3b461be725c492cd881c5ec9c0ad25023f188`.
The official Alpine image is available for the existing runtime; no Debian switch
is needed. [PostgreSQL 19.0 GA](https://www.postgresql.org/about/news/postgresql-19-released-3449/)
was released on 19 November 2026. A major upgrade
uses logical dump/restore into the new `pgdata19` volume. Never mount the PostgreSQL
18 data directory into PostgreSQL 19, and do not run this change while a production
incident hold is open. In particular, this procedure does not clear or bypass any
`forward097.*` marker.

The regular release entrypoint intentionally blocks PostgreSQL image or volume
changes. Treat this as an approved production maintenance operation, not a normal
CD deployment. Current host, source-volume, database-size, role-inventory, and
recovery-policy facts must be read from the actual production host before the
window; source review and a healthy API do not establish them. Do not proceed if
the host, source image/volume, exact Alembic revision, recovery evidence, or incident
state cannot be verified.

Before approving the source-to-target restore, perform a PostgreSQL 19
compatibility inventory against the live PostgreSQL 18 configuration and
catalogs. Use the pinned PostgreSQL 19 `pg_dump` client with
`--quote-all-identifiers`; do not reuse an older client's dump. Confirm the
application and database role settings are safe with PostgreSQL 19's enforced
`standard_conforming_strings=on`. Stop for any database encoded as
`MULE_INTERNAL`, any database/role/tablespace name containing CR or LF, or
RADIUS authentication in `pg_hba.conf`; each needs a reviewed disposition.
Inspect custom server configuration for removed settings such as `io_workers`
and validate the target configuration before cutover. Inventory `btree_gist`
indexes whose indexed type is `inet` or `cidr`; PostgreSQL 19 changes the
network-type GiST operator classes because the old behavior could omit
matching rows. Do not restore those indexes unchanged. Also identify indexes
and stored values using full-text search, `pg_trgm`, or `fuzzystrmatch`.
PostgreSQL 19 changes locale-sensitive behavior for these functions; plan and
verify any required index rebuilds and stored `tsvector` recomputation on the
isolated PostgreSQL 19 copy before production use. Record each check and its
result; an unknown source setting or unresolved compatibility finding is a
stop condition.

#### Preparation and write pause

1. Record the exact candidate SHA and successful CI run, active release and
   application version, PostgreSQL 18 server/image digest, Compose project and
   source volume, both database names, role/owner/grant inventory, installed
   extensions, locale/collation metadata, and Alembic revision. Confirm the
   candidate's application schema is compatible with that revision. Do not apply
   an unrelated Alembic revision as part of this database-engine change.
2. Require a current authenticated database-and-object recovery set in the
   approved independent destination and a successful isolated restore of that
   set. A database dump in the portal's own object store is not independent
   recovery evidence. Preserve the backup set and the original PostgreSQL 18
   volume; no cleanup is part of this procedure.
3. Rehearse the candidate's PostgreSQL 19 image, logical restore, catalog checks,
   and rollback using a disposable copy with matching data volume and extensions.
   Capture dump checksums, exact catalog/count comparison output, restore duration,
   candidate/image digests, and the observed collation versions. The local
   PostgreSQL 18.6-to-19.0 rehearsal recorded for this change is synthetic and is
   not production recovery evidence.
4. Acquire the existing deployment lock and confirm the incident hold is closed
   through its reviewed reconciliation procedure. Block ingress, then stop
   `backend`, `celery_worker`, `celery_beat`, and `grafana` so they cannot write.
   Drain all client sessions and scheduled/one-shot database jobs. Leave the
   PostgreSQL 18 database and its old volume intact until final verification.
5. Create a root-only, encrypted maintenance artifact directory. Use the pinned
   PostgreSQL 19 client image for the final `pg_dump --format=custom` captures of
   both the application database and `grafana`. Record checksums and use
   `pg_restore --list` to confirm both archives are readable. Do not put database
   passwords or raw role password hashes in logs or repository evidence.

#### Fresh-volume restore and comparison

6. Start the candidate's PostgreSQL 19 service using the `pgdata19` Compose volume.
   This creates a new volume; it does not rename, reformat, mount, or delete the
   PostgreSQL 18 volume. Initialize the application role/database from the
   protected production configuration, then run the checked-in
   `grafana_db_init` service to create/update the Grafana role and database before
   restoring.
7. Before restore, compare the source's non-system roles and ownership against the
   deployment contract (`POSTGRES_USER` plus `grafana`), including role attributes,
   database/schema/table grants, and tablespaces. If there are additional roles,
   owners, extensions, or tablespaces, stop and prepare a reviewed mapping rather
   than silently omitting them. Restore each custom archive with SQL errors fatal,
   `--no-owner`, and `--role` set to its established database owner; retain ACLs.
   Restore into the fresh databases only. Do not use `--clean` against a source or
   shared database.
8. Compare source and target before reopening writes: exact row counts by table;
   primary/foreign/unique/check constraint names and definitions; index names,
   key columns, uniqueness, predicates, and validity; sequence values and
   `is_called`; role attributes and grants; database owners; extension names and
   versions; and Alembic revision rows. Confirm every index is valid and every
   extension is installed. PostgreSQL versions can render equivalent expressions
   differently in `pg_get_indexdef`/`pg_get_constraintdef`; compare catalog
   structure and expression semantics rather than requiring byte-identical
   display text.
9. Compare each database's locale, collation provider, recorded collation version,
   and actual version. A mismatch is a stop condition; obtain a reviewed
   `REINDEX`/collation-refresh plan before use. Do not automatically refresh a
   version marker without rebuilding affected indexes.
10. Keep ingress blocked. Start the application, worker, beat, and Grafana against
    PostgreSQL 19; verify readiness, queue connectivity, worker/beat health,
    Grafana health, protected report/document reads, and the approved read-only
    business checks. Confirm the exact served PostgreSQL 19 image digest and
    migration head. Do not create or delete customer business records as a smoke
    test.

#### Rollback boundary

Before reopening writers, rollback is to stop PostgreSQL 19 and restore the
previous application release and PostgreSQL 18 Compose configuration with the
original PostgreSQL 18 volume. Do not delete either volume. Recheck schema and
readiness before removing the ingress block. Once writes have resumed on
PostgreSQL 19, the old PostgreSQL 18 volume is stale: switching back to it would
discard newer writes. At that point, stop writes and use an approved forward
reconciliation or tested recovery plan; do not describe a volume switch as a
no-loss rollback.

Record actual UTC start/end, downtime, source/target volume names, release and
image IDs/digests, dump and recovery-set identities, catalog comparison results,
Alembic heads, health checks, and the operator/reviewer. Keep the old volume and
encrypted artifacts under the approved retention policy until a separate
recovery/cleanup approval. No production migration or release is authorized by
this runbook text alone.

### Post-Deploy Verification

On the production host, with the [active Compose helper](#host-bootstrap-and-runner-maintenance) defined:

```bash
cat "$release/DEPLOYED"
prod ps --all
curl --fail --silent --show-error https://portal.garrisons.lk/health
curl --fail --silent --show-error https://portal.garrisons.lk/health/readiness
```

Compare the receipt with the GitHub run and the intended SHA. The API readiness endpoint checks PostgreSQL connectivity. Check the queue, storage, and background jobs separately when the release affects them. Confirm the one-shot `grafana_db_init` and `loki_minio_init` jobs completed successfully when the stack was initialized or those jobs were rerun. If one fails, inspect its logs before starting dependent services. Verify Grafana `/api/health` through its configured HTTPS hostname. Test a fresh authenticated object preview and download if the release affects ingress or storage. For app changes, exercise the affected business workflow in the permitted environment and record the result.

On an empty production database after the schema is ready, create the approved first Managing Director in an interactive host terminal:

```bash
prod exec backend python scripts/bootstrap_admin.py \
  --email director@example.com --full-name "Managing Director"
```

The command prompts for a temporary password. Use the approved director address and confirm that it receives and can use a login OTP from the configured sender.

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
| Daily | Database backups at 01:00, notification cleanup at 03:00, audit maintenance at 03:30, and supplier TDS expiry checks at 04:00. Production audit maintenance runs in retain-only mode with `LOG_PURGE_ENABLED=false`. |
| Daily, opt-in on supporting releases | HR credential checks at 04:15 when `HR_REMINDER_WINDOW_DAYS` is set, HR service request checks at 04:30 when `HR_SERVICE_REQUEST_SLA_DAYS` is set, and probation reviews at 04:45 when `HR_PROBATION_REVIEW_REMINDER_DAYS` is set. See [HR reminders](HR_WORKFORCE.md#reporting-and-reminders). |
| First day of the month at 02:00 | Monthly database backups. |

### Backup and restore

[backup.py](../backend/scripts/backup.py) creates encrypted PostgreSQL dumps for the application and Grafana and writes them to the configured S3 bucket. Daily application backups use `backups/daily/` and monthly backups use `backups/monthly/`. Grafana backups use `backups/grafana/daily/` and `backups/grafana/monthly/`. The default retention is 30 days for daily backups and 12 months for monthly backups. The application upload bucket and Loki operational log data require their own recovery decisions.

Run a backup on demand through the active Compose helper:

```bash
prod exec -T backend python -m scripts.backup --target all
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

### Same-host local backups

For a separate private RustFS service on the Garrisons VPS, prepare an approved
policy with `decision_id: SAME-HOST-LOCAL-BACKUP` and the same real failure-domain
name for source and destination. The local destination still needs its own bucket,
TLS endpoint, restricted identities, capacity and retention rules. Run manual
backup-set operations with `python -m scripts.backup_set --local-only <operation>`
and that policy. Capture still requires verified writer quiescence and the capture
receipt. Use the same policy and option when verifying, fetching or restoring.
Authenticated local manifests, publication receipts and restore receipts carry a
signed `same-host-local` scope. Independent readers reject that scope.

The host scheduler remains for the independent policy. Same-host backups cover
local recovery scenarios and share the VPS failure domain. They do not satisfy
D-29 independent recovery evidence.

### Independent database and file recovery drill

Agree on the backup destination, key custodian, retained evidence, recovery point and recovery time targets before accepting a release. Use a destination that remains accessible if the portal host and its object storage are unavailable. Keep the manifest private because it includes object identifiers. Store deployment configuration and keys through the approved recovery procedure.

[The backup-set tool](../backend/scripts/backup_set.py) captures the application database and required files. It reads database references from the same PostgreSQL snapshot as the dump. It includes retained document versions, HR document versions when their table is present, ready report PDFs, current invoice and supplier attachments, and photo originals and variants for active records or records within the soft-delete window. The backup includes that media even though the portal's recovery endpoint is disabled. If policy retains replaced attachment objects, supply their keys from the approved inventory with `--extra-objects`. Supply `BACKUP_GRAFANA_DATABASE_URL` in the private environment to include the Grafana database. Capture during a recorded write pause that also covers the object store and any Grafana database included in the set.

For a new set that can count toward acceptance, use the approved D-29 policy and authenticated format 2. Captures without `--policy` use the legacy checksum-only format 1 and are retained only for historical recovery. In the authorized backend environment, mount the root-owned backup-encryption file read-only at `/run/secrets/backup_encryption_key` and set `BACKUP_ENCRYPTION_KEY_FILE` to that path in the dedicated capture environment. Keep `BACKUP_AUTH_KEY_FILE` and `BACKUP_AUTH_KEY_ID` in their separate restricted inputs. Keep the approved policy at `$RECOVERY_POLICY` and the allowlisted nonsecret runtime files at `$RECOVERY_CONFIGURATION_ROOT`.

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

The authenticated `verify` command checks the exact manifest signature, artifact presence, size, and hashes before restore. For a recovery exercise, mount the set in a disposable environment with its own empty PostgreSQL databases and new object bucket. Configure `RESTORE_DATABASE_URL`, optional `RESTORE_GRAFANA_DATABASE_URL`, `RESTORE_OBJECT_ENDPOINT`, `RESTORE_OBJECT_BUCKET`, `RESTORE_OBJECT_ACCESS_KEY`, and `RESTORE_OBJECT_SECRET_KEY` privately. The tool accepts only loopback PostgreSQL databases named `garrison_restore_test_*` (querying `pg_catalog` to reject databases that already contain user schemas, relations, functions, types, or large objects) and a new loopback bucket named `garrison-restore-test-*`. Disable outbound mail and scheduled business jobs in the restored application.

Use that same approved policy for publication, fetch and restore. Publication also requires the separate prefix-scoped `DR_BACKUP_*` publisher credentials; it verifies remote encrypted bytes before writing the authenticated completion record. For example, publish with `python -m scripts.backup_set publish "$LOCAL_SET" --policy "$RECOVERY_POLICY" --receipt "$PUBLICATION_RECEIPT"`. A substitute operator can fetch a complete set with `fetch "$BACKUP_SET_ID" --policy "$RECOVERY_POLICY" --destination "$ISOLATED_SET"` and restore it with `--require-authenticated`. Retain the existing format 1 sets for historical recovery and record their checksum-only assurance.

The [scheduled capture service](../deploy/backup-set.service) invokes the [capture wrapper](../deploy/capture-recovery-set.sh) under the same host lock as deployment. Set `BACKUP_ENCRYPTION_KEY_HOST_FILE` to the root-owned mode-0600 host file in the root-owned scheduler environment. The wrapper mounts it read-only only into the capture container; the capture environment contains only the in-container `BACKUP_ENCRYPTION_KEY_FILE=/run/secrets/backup_encryption_key` path. Set `RECOVERY_POLICY`, `RECOVERY_CAPTURE_TEMPLATE`, `RECOVERY_CAPTURE_ENV`, `RECOVERY_PUBLISH_ENV`, and the two authentication key variables in that scheduler environment. Set `RECOVERY_CONFIGURATION_ROOT` to a dedicated root-owned directory containing only the approved nonsecret recovery configuration. Keep the policy, capture inventory, credentials and authentication key outside that directory. Install the service and wrapper only after exercising the write pause and recovery against the approved destination.

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

For a synthetic HR recovery drill, run the readback checker from `backend/`
with the restored application and its object store on explicit loopback
origins. Supply short-lived tokens for a restored HR Manager, the employee
whose policy receipts are being checked, and a different linked employee without
access to the selected evidence. Provide them securely as
`HR_RECOVERY_HR_TOKEN`, `HR_RECOVERY_EMPLOYEE_TOKEN`, and
`HR_RECOVERY_OUTSIDER_TOKEN`. Keep the expected plan outside the repository in
an owner-only file. The plan contains the synthetic employee and personnel
document UUIDs, the identifier SHA-256, at least two personnel version numbers
and hashes, current and previous policy UUIDs with their edition labels,
current flags, pinned version numbers and file hashes, and the application
and correspondence UUIDs with the approved correspondence digest. See
[`RecoveryPlan`](../backend/scripts/verify_hr_recovery.py) for the JSON fields.
The checker prints counts. Protected API reads can record ordinary access
audit events on the restored database.

```bash
python -m scripts.verify_hr_recovery \
  --api http://127.0.0.1:8000 --objects http://127.0.0.1:9000 \
  --plan "$HR_READBACK_PLAN"
```

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

Use sample data only in an approved non-production environment. Follow the [seed setup](../README.md#getting-started) and the [roles and permissions reference](ROLES_AND_PERMISSIONS.md). Run browser acceptance in desktop Chrome only, including offline retries, file selection and downloads, and degraded-network checks. For UAT-21, use representative JPEG, PNG and HEIC files to verify format and size boundaries and original-only HEIC behavior. Record the browser version, role, scenario, result, and any accepted issue.

## Formal acceptance still pending

The current portal scope limits Delivery to Launch readiness and excludes G-01. The selected audit mode for this release is retain-only, and destructive audit deletion stays disabled. The user's approved browser scope is desktop Chrome only; other browser and physical mobile targets are out of scope. Production is deployed at SHA `be61f5b74ce9701ba83f70261b03fe6219bd2d72`, schema `202605310013`; [self-hosted CI](https://github.com/nirzaf/garrison-investments/actions/runs/43708858463) and [production deployment](https://github.com/nirzaf/garrison-investments/actions/runs/43717032813) succeeded. The deployment receipt states Formal Acceptance Pending. Each item below remains open for formal acceptance (see [POST_RELEASE_ACTIONS.md](POST_RELEASE_ACTIONS.md) for full details).

| Decision | Responsible role | Work and evidence | Risk until verified |
| --- | --- | --- | --- |
| D-27-SCOPE | Business sponsor | Approve the scope inventory digest and exclusion in a signed decision. | Scope direction is `launch_readiness_only` with `G-01` excluded. The prior inventory at production SHA `1399710589f8f2d82bac2e79326bc9b88bbb888d` had byte SHA-256 `10d98679c75856ae9884790a0c4128b4e5040afaa1cedcd4184209a4a507a593`. The current edited inventory must be frozen and rehashed before authenticated approval; no signature is recorded. |
| D-28-POLICY | Records owner | Sign the retain-only policy, classes/deadlines, unknown-record handling, and hold decision. Review the complete preview, archived access and storage capacity. | The latest recorded preview is pre-cutover: release `9aa8f2316de9682af5b6d046eeb8f884f4f0c532` at `2026-11-14T17:21:38Z`, 222 records; 222 unclassified, 114 without deadlines, 108 with future deadlines, 0 purge-eligible. `LOG_PURGE_ENABLED=false`; the policy itself was `unconfigured` with no revision or digest. No deletion is enabled. Refresh the preview on the current release before sign-off; the signed policy and legacy classifications remain outstanding. |
| D-29-RECOVERY | System owner | Approve independent storage, key custody, RPO/RTO and operator access. Restore an authenticated database and object backup and record measured results. | For candidate `be61f5b74ce9701ba83f70261b03fe6219bd2d72`, production maintenance verified encrypted application and Grafana backup objects before migration `202605310013`. The application backup restored to revision `202605310012` in disposable PostgreSQL and accepted an isolated upgrade to `202605310013`; a separate synthetic authenticated format-2 rehearsal restored HR objects and rejected wrong-key/tampered inputs. The production backup destination remains in the Hostinger failure domain; independent publication/timer, approved RPO/RTO, production key custody and timed off-host database/object restore remain outstanding. See [post-release recovery evidence](POST_RELEASE_ACTIONS.md#six-owner-decisions). |
| D-30-OPERATIONS | Operations owner | Approve and exercise the independent monitor, recipients and responders. Record alert delivery, acknowledgement and recovery. | An outage affecting the primary host may delay detection. |
| D-32-SUPPORT | QA lead | Approve the exact desktop OS/Chrome version, role/scenario matrix, network profiles, numeric performance/data budgets, and named testers. | The live candidate passed automated Chrome checks. The [acceptance register](POST_RELEASE_ACTIONS.md#six-owner-decisions) records the tested SHA and outstanding human QA evidence. |
| D-33-BUSINESS | Finance/data owner | Approve assignments, sample outputs, financial conventions and import controls. Reconcile the data and obtain final sign-off after observation. | The latest recorded configuration inspection (before the current release) showed USD, Asia/Qatar, and material-approval threshold `1000.00`; independently confirm those values against the frozen acceptance candidate. Assignment reconciliation, five accepted samples, independent import/control-total checks, and final acceptance signatures remain outstanding. |

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

[launch_evidence.py](../backend/scripts/launch_evidence.py) checks the supplied URLs and records hashes for attached evidence files (`--target` accepts `production` or `test`, and `production` requires an explicit `--operator` identity independent of `GITHUB_ACTOR` or `--approver`). Run it from a trusted checkout using private output paths and the actual release values:

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
### Super Admin activation

Keep the Super Admin entry points disabled until the operator enrollment
and dedicated ingress are approved. The support portal uses separate
passkey-backed operators, opaque host-only sessions and case-scoped request
evidence. The legacy `/api/v1/super-admin` email-only API is a test fixture.
Production uses `/api/v1/support` with passkey verification followed by email
OTP. The business user, HR and role-cutover tools do not provision operators.

The default catch-all rejects the reserved hostname and both technical API
prefixes. The approved host overlay mounts the tested
[technical virtual host](../nginx/support.prod.conf) at
`/etc/nginx/conf.d/support.conf` read-only. Provide a TLS pair for
`superadmin.garrisons.lk` as `support-fullchain.pem` and
`support-privkey.pem`, and `support-allowlist.conf`, under the mounted
`/etc/nginx/ssl/` directory. Restrict the key to mode `0600`. The allowlist
contains one `allow <IP-or-CIDR>;` directive per approved direct source
address or VPN egress network. Nginx checks the socket source address and
applies `deny all` after the allowlist. A proxy that obscures the approved
source needs a separately authenticated ingress design.

The host preflight uses OpenSSL to check that the certificate is currently
valid, lists the technical hostname in a DNS subject alternative name
(a matching wildcard is accepted), and loads with the mounted private key.
The allowlist check rejects IPv4 or IPv6 rules that collectively cover
every address. Verify the served certificate chain from an authorized
browser or operator network during activation.

#### Certificate renewal monitoring

Monitor the staged certificate on the host and, after activation, the served
certificate from an approved network. Use a daily check with an initial
30-day warning and a 7-day urgent alert. Record the owner, contact point and
test receipt in the restricted activation record. Failure to read the file,
validate the served hostname or query from the approved network is also an
alert condition.

On the host, run `openssl x509 -in <mounted-support-fullchain.pem> -noout -checkend 2592000`
for the warning. After activation, check the certificate
served with SNI `superadmin.garrisons.lk`, verify its trust chain and hostname,
then apply the same expiry check to the leaf. Test alert delivery with a
synthetic expiry before signing off monitoring. Manual DNS-01 renewal requires
a new challenge. Verify the new certificate and matching private key, replace
the mounted pair under the approved change procedure and confirm the served
expiry after Nginx reload.

#### Dedicated ingress

Set `SUPPORT_PORTAL_ENABLED=true` and `SUPPORT_INGRESS_PEER` to the exact
Nginx address on the private `backend_proxy` network when activating that
overlay. The release preflight checks that the flag and virtual host match,
the peer matches the effective Compose address, and the TLS and allowlist
files are mounted. The backend pins the actual connection peer and verifies
the technical hostname and request origin. The dedicated virtual host
allows the support page, built assets and support API. Business API, file,
service worker and legacy technical routes return 404 there. Prove both
hostnames and the allowed and denied paths before enrolling operators.

The isolated Nginx 1.25 HTTPS rehearsal passed with two separate source IPs.
It checked default-deny routing, mismatched TLS SNI and host, removal of
caller-supplied forwarding and bearer headers, and `no-store` responses.
143 support and related backend tests, 80 release and observability tests,
and six synthetic Chrome scenarios passed. The Chrome scenarios used the
isolated application fixture. Production DNS, certificates, source access,
and operator sign-in still require their own verification.

Revision `202605310062` adds business session persistence and refresh-token
ownership. Revisions `063` through `074` add empty support identity, evidence
and custody tables. None of these migrations enrolls operators or issues grants.
The production maintenance procedure applies even when changes are additive.
Before applying it, rehearse the exact candidate on a populated isolated
restore, verify legacy session expiry and revocation, and record the backup
and rollback procedure. Roll back application code with the additional
schema retained. Review session compatibility and revocation before restoring
traffic to any earlier application version.

Prepare enrollment proposals in the restricted operations record. Each
proposal names the verified identity, the separate custodian, the approved
capabilities, case and expiry limits, registered devices, and reviewer. A
proposed address already used by a director requires an explicit disposition
before enrollment. Preserve the director account and existing role. Obtain
explicit owner confirmation immediately before applying either operator's
concrete grant. Prove independent recovery and protected-custodian checks
before exposing the sign-in screen. Disable the dedicated ingress and revoke
technical sessions before an application rollback. Preserve evidence and audit
history.

Technical sign-in on the dedicated host requires an enrolled passkey followed
by a six-digit code sent to the operator's verified technical mailbox. Browser
and CLI sign-in both use this check. Configure `SUPPORT_EMAIL_OTP_KEY` with an
independent random secret of at least 32 bytes and
`SUPPORT_EMAIL_OTP_RECIPIENTS` with a JSON object mapping approved support
operator UUIDs to their dedicated mailboxes. Keep both values in protected
runtime configuration. A missing binding or failed transport closes the sign-in
attempt. The host release preflight checks key independence and valid,
distinct mailbox bindings for at least two operator references when ingress
is enabled. Apply the exact candidate's Alembic head using the [production
maintenance procedure](#production-maintenance) before enabling ingress.
Revision `202605310089` introduces email OTP. Disable ingress before reverting
to an earlier version.

#### Draft verification

An isolated PostgreSQL rehearsal upgraded a populated schema from
`202605310061` to `202605310062`. It preserved the existing identity and the
legacy refresh expiry. The subsequent refresh created its owned session.
The draft passed 85 focused backend tests and three desktop Chrome
regressions for password change, denial on the business host, and the released
HR Executive role. An isolated Nginx container accepted the syntax and
returned 404 for both support prefixes on the business host and for
business API and file routes on the reserved host.

### Support identity and case evidence

The [support schema reference](schema/support_identity.md) describes the
separate operator and audit tables. The isolated browser fixture uses a
synthetic resident credential and Chrome's virtual WebAuthn authenticator.
It covers passkey sign-in, session reload, denied out-of-case evidence,
redacted authorized evidence and sign-out. Local PostgreSQL verifies
concurrent login replay, session expiry, grant and case membership checks,
and append-only audit records.

The email-verification draft passed 177 focused backend tests and six
existing Chrome scenarios. A separate isolated Chrome run used real
WebAuthn verification with a synthetic email transport. It exercised a
wrong-code retry and verified that browser and CLI sessions open only after
the code succeeds. Migration `089` passed the populated upgrade and
disposable restore checks. Production mail delivery remains unverified.

The updated draft passed 100 focused backend tests with no skips and five
Chrome scenarios against disposable services. The populated upgrade from
`061` through `074` retained the fixture business identity and legacy
refresh expiry. The custody workflow was exercised through the API with
synthetic credentials, including concurrent suspensions, stale authorization,
proof replay and cross-session rejection, revocation and append-only audit.
The production host has received none of these revisions.

The test-only custody API supports operator suspension. One eligible custodian
proposes and executes the suspension, and a different eligible custodian
reviews it. Both decisions require a fresh passkey proof bound to the
proposal, action and authenticated session. Both custodians must remain
eligible at execution. The transaction preserves at least two usable
custodians, revokes the target's credentials and sessions, advances the
grant epoch and records the decision. Keep the custody schema and audit
history through an application rollback.

The case API requires `cases.manage` to open cases and both live membership
and the relevant capability to read assigned records. The owner proposes
case scope changes against the current revision. An eligible independent
custodian reviews membership changes. An independent case member with the
matching capability applies evidence links, verification, account scope or
closure using a fresh passkey proof. Resolution verification requires an
already reviewed safe request-completion event after mitigation, and the
independent reviewer confirms the resolution against that evidence. Closure
requires an applied verification receipt. The timeline shows the latest 25
events and redacted request references, including on closed assigned cases.
The masked directory resolves the exact subject of an approved case scope
from the case ID and includes at most 25 authentication events in the
previous 24 hours. Operators may supply an account reference to require an
exact match. Both lookup paths record the same disclosure audit. Changes to
case scope advance the revision and invalidate stale proposals.

A disposable database restore preserved revision `074`, case and account decisions, audit disclosures and custody
events, and the append-only protections. Alembic rejected a downgrade to
`073`. Chrome exercised case creation, a duplicate reference, triage and
persistence after reload. The case workflow also exercised reviewed assignment,
masked account lookup, reviewed unlock, redacted case audit, evidence
linking, independent verification, closure and the retained timeline. Separate synthetic requester, reviewer and
target sessions exercised self-review denial, reviewed capability grant and
target sign-in after session revocation. Two virtual Chrome authenticators
registered distinct credentials through reviewed enrollment and the resulting
operator signed in. API tests exercised reviewed recovery, replay, duplicate
and backup-eligible credential denial, and rejection of replaced credentials.
Health tests checked unavailable dependencies and session revocation during a
probe. An isolated Nginx container rejected tested support routes on the
business host and returned 404 for the reserved host, its business API and
file routes. Application rollback keeps the expanded schema and audit history.

#### Technical capabilities

The technical portal is the operations console for platform oversight,
diagnosis and controlled intervention. Each named capability is a separate
grant. Case evidence is scoped by live membership, approved request links,
and the source and time filters. A grant change requires a distinct
reviewer and a fresh passkey for each review and execution. Operational
grants persist until revoked. Changing a grant revokes the target's current
sessions and advances the authorization epoch.

| Capability | Proposed production authority | Local implementation |
| --- | --- | --- |
| `operator.manage` | Propose and execute or independently review operator enrollment, recovery, suspension and grant changes. Use a separate reviewer with an active custody grant and two registered passkeys. | Reviewed actions and the last-two-custodians guard verified. Bootstrap of the first two custodians is a separate offline ceremony. |
| `cases.manage` | Open, inspect and triage cases with live membership. Independent review for evidence verification and closure. | Case creation and triage, reviewed membership and evidence links, independent verification and controlled closure implemented. |
| `logs.runtime` | Inspect redacted runtime summaries for explicitly linked requests on assigned open or investigating cases. | Linked request evidence, bounded case timeline, and separate reviewed live-stream and export paths are implemented. The explorer currently uses indexed request events. Additional sources require their own bounded projections. |
| `health.read` | Check fixed dependency health, with timestamp and bounded status. | PostgreSQL, Redis and object-bucket checks verified. No mail message or host command is issued. |
| `directory.read` | Inspect masked identity, access and authentication history for an approved subject in an assigned case. | Account reference, verified email, employee code, name and role match only the approved subject. The response includes masked identity, permission keys, bounded authentication history and membership IDs for approved case projects. The separate project-list projection requires its own approval. |
| `account.request` | Request reviewed recovery, unlock, session revocation, disable or reactivation through existing business safeguards. Protected subjects require two independent reviews and a verified offline owner-contact receipt. | Reviewed recovery issuance, queued delivery, status, reset confirmation, session revocation, unlock, disable and reactivation are implemented locally. The separately approved owner-notification channel and production delivery evidence remain open. |
| `simulation.start` | Start a short-lived, read-only, consented or independently approved support projection with explicit case, subject, adapter and project limits. | The five independently reviewed adapters are implemented locally: role permission, navigation, request summary, project list and project detail. |
| `logs.audit`, `logs.stream`, `logs.export` | Inspect approved audit evidence, follow bounded redacted streams, or export a reviewed immutable result. Export requires independent approval. | Assigned-case audit reads, request streaming and reviewed export are implemented locally. Streaming and export each require `logs.runtime` and their own grant. |
| `overview.company.read`, `overview.workforce.read`, `overview.suppliers.read`, `overview.documents.read`, `overview.finance.read`, `overview.approvals.read` | Inspect company-wide bounded operational status without PII, individual salaries/cases, invoice IDs/amounts, or write access. | Implemented locally as fixed read-only projections. `overview.workforce.read` enforces small-cell suppression (threshold 5 with single-complement total suppression) and omits compensation, medical, disciplinary and payroll tables; `overview.finance.read` returns workflow state counts and `finance_writes_policy` (`blocked`) only. |
| `overview.projects.read`, `overview.inventory.read` | Inspect bounded project and inventory health, constrained to explicitly reviewed case project scope when scoped by case or project. | Implemented locally. Intersects requested case/project boundaries with `support_case_projects`, returning progress bands, item/request counts and zero supplier/invoice figures. |
| `jobs.read`, `backups.read`, `config.read`, `incidents.read` | Inspect queued/Celery job status, attested backup receipts, non-secret runtime configuration posture, and redacted failure summaries. | Implemented locally with `GET /api/v1/support/monitor/jobs`, `/monitor/backups`, `/config/status`, and `/incidents/summary`. Excludes task payloads, storage paths, secret values, PII and request bodies. Oversight and monitor reads share a 30/min per-operator rate limit, 5-second query timeout degradation, live session/revocation re-checks, and append-only `support_oversight_events` disclosure audit. |

The portal's Follow live evidence control and `garrisonctl support cases
follow-logs` share the same redacted request projection. A session can
resume from the last event while the request remains in scope. The API
allows two concurrent streams per operator for up to 15 minutes each and
checks the session, capabilities, case and request link before every batch
and on the idle polling interval. Streams do not renew idle sessions or
hold a database connection while waiting. Pause closes the transport.
An isolated Chrome run followed a live HTTPS feed, paused and released its
server slot, resumed from the last event, and stopped after the grant was
revoked. The fixture used synthetic case evidence and a local HTTPS proxy.

Evidence export uses one approved request link, a window of at most seven
days, 10,000 rows and 10 MiB. The CSV includes a manifest row with the
normalized filters, row count and truncation status. An independent
operator with the same case scope approves the proposed SHA-256 with a
passkey. Only the original requester session can download it, with a
fresh passkey and a live authorization check. The API re-creates the
redacted projection and checks its SHA-256 before consuming the download.
The audit receipt records the filters, checksum, row count, timestamps
and correlation references. It retains no exported bytes.

Technical grants do not confer any business role. Invoice approval, payroll
release, access to private records, and changes to business roles continue
through their owning workflows. Host restarts, production restore, destructive
retention and irreversible deployment actions use the separate production
maintenance procedure. Audit and custody records remain append-only.

#### Business account interventions

The account must be linked to an assigned open or investigating case.
An `account.request` grant permits an unlock, session revocation, disable
or reactivation proposal referencing the current case revision and business access
revision. A separate eligible case member reviews the exact digest with
a fresh passkey. The requester executes with a new passkey proof. A
protected role requires two distinct eligible reviewers and an unexpired
offline owner-contact receipt. An assigned custody reviewer with two usable
passkeys can record their attestation during review. Enter the opaque
reference only after independently verifying owner contact offline. The
review proof binds the reference and the exact proposal digest. The portal
stores the attestation without contact details or message contents.

The transaction reuses the business access-management lock and existing
session, refresh-token and challenge revocation. Unlock clears failed
attempts and the lock timestamp, preserving active status, credentials
and role. Disable rejects a change that would leave the company without
another usable director. Reactivation preserves revoked sessions.
The technical audit remains separate from the business actor.
The offline contact channel and production notification routing still
require approval and verification.

Recovery destination verification requires a separate protected
`SUPPORT_RECOVERY_KEY` of at least 32 bytes. With the key configured, a
completed business sign-in can verify the existing mailbox when the
provider accepted delivery and the correct delivered OTP was supplied.
An address change or key rotation invalidates an earlier binding.
Developer-echoed OTPs and the staging bypass do not establish eligibility.
There is no backfill from login history. The case directory adds only
the verification status for operators with `account.request`.

The reviewed recovery action requires explicit opt-in outside test runs:
`SUPPORT_RECOVERY_DELIVERY_ENABLED` defaults to `false`. Enabling production or
staging assisted recovery also requires a matching normalized HTTPS origin in
`SUPPORT_RECOVERY_ALLOWED_ORIGINS` (validated against `FRONTEND_BASE_URL` by
[release config contract](../deploy/release_config_contract.py)), an independent
32+ byte `SUPPORT_RECOVERY_KEY`, and no overlap between the target's mailbox
binding and configured custodian OTP mailboxes (`SUPPORT_EMAIL_OTP_RECIPIENTS`).
Applies recheck the verified mailbox, increment the
business access revision, revoke old authentication, and commit the
new single-use challenge and delivery row together. Protected accounts
still require two independent reviews and an exact owner-contact
attestation. The reset code and mailbox are absent from the action
receipt. The reset endpoint requires an accepted delivery, an active
account, and the same mailbox and access revision.

When `SUPPORT_RECOVERY_DELIVERY_ENABLED=true`, the recovery worker claims one
delivery at a time. Before sending it rechecks the case, requester and
reviewer grants, the protected contact receipt when applicable, the
account revision, custodian OTP mailbox separation, and the current verified
destination and challenge. The message carries a portal reset link on the
allowlisted HTTPS origin and a code. The link fragment contains only the
opaque challenge reference. A transport timeout, exception, or interrupted claim
records an unknown outcome for review, writes non-secret in-app notifications,
and (for an `"unknown"` outcome) notifies `EXCEPTION_EMAIL_RECIPIENTS` without
codes, links, or email addresses. Recovery codes use one transport attempt per
reviewed action. Ordinary mail keeps its existing fallback behavior. Separate
out-of-band owner verification remains controlled offline.

Grafana provisioning under [alerts configuration](../observability/grafana/provisioning/alerting/alerts.yml)
includes the `Support security alerts` group (`garrison-support-auth-burst` for
repeated 401/403 responses on `/api/v1/support/*` and `garrison-support-recovery-unknown`
for failed `dispatch_support_recovery_deliveries` worker executions).

Use **Recovery status** with the case ID and the reviewed action
reference. The requester or another current case member needs
`account.request`. Delivery acceptance only means the provider
accepted the message. The reset result separately shows whether the
code is ready, unusable, expired, revoked or completed. The panel
shows timestamps and opaque references and audits each disclosure.
If delivery is unknown, inspect the provider evidence before a fresh
independently reviewed recovery. A new recovery invalidates the prior
challenge.

Revision `202605310093` and the oversight, monitor, policy-explain, config, and
incident surfaces passed 256 focused backend tests, 132 release/launch contract
checks, Chrome Playwright virtual-WebAuthn scenarios (`e2e/user-role.e2e.ts` and
`e2e/support-identity.e2e.ts`) against disposable PostgreSQL, Redis, and Moto
object storage, plus Alembic `upgrade head` and blocked `downgrade 202605310092`.
Live Hostinger maintenance upgrades (`202605310062` through `202605310093`),
production TLS/DNS/CIDR proxy checks, physical two-custodian passkey ceremony,
live email OTP/recovery delivery, off-host restore/alert drills, and formal
owner governance sign-offs (`D-27` through `D-33`) remain external to this repository.

The revision 081 suite passed 125 backend checks, six Chrome scenarios
and a disposable restore that retained the status-read audit events.
A focused follow-up passed ten backend checks and one Chrome scenario.
Chrome queued a reviewed synthetic recovery and showed its pending
status. The API tests separately covered acceptance, unknown and
cancelled outcomes, reset completion, and denial outside the case.

The revision 080 validation passed 125 backend checks and six Chrome
scenarios. The fake transport accepted one message under concurrent
dispatch, simulated an uncertain result without fallback, and received no
message after reviewer authority was revoked. Chrome opened the reset form
from the opaque link. The disposable restore retained a completed recovery
and an unknown outcome.

The local revision 079 suite passed 111 backend checks and five Chrome
regressions. The API tests covered ordinary and protected recovery,
changed destination denial, atomic authentication revocation, and
single-use confirmation after a simulated delivery acknowledgement.
The disposable restore retained the queue and completed recovery record.

The populated upgrade from revision 061 through 078 preserved the
existing business identity and legacy session expiry. The local suite
passed 109 backend checks and five Chrome scenarios. The restored
database retained an email verification binding and the protected
action audit records. The change has not been deployed.

Revision `202605310077` passed the local 104-check backend suite,
five Chrome scenarios and a disposable restore. The API tests recorded
the protected-action contact attestation through passkey review and
rejected omission of the bound reference and an ineligible operator.
A subsequent focused run passed seven backend checks and one Chrome
scenario, including the contact field's custody-grant visibility.

With `simulation.start`, a requester can propose an explanation of one
known role permission for the case subject. An independent assigned
operator reviews the exact proposal. The requester uses the original
technical session to open and read the view. The result shows whether
the role grants that permission. Each read rechecks live case membership,
reviewer eligibility and subject access revision. The view expires
after 20 minutes at most or 10 minutes idle, and operators can end it
earlier. Opening, reading and ending it are audited.

The navigation adapter uses the business sidebar visibility rules and returns
only stable route identifiers and visibility flags. Keep the
[backend policy](../backend/app/portal_navigation.json) and
[frontend copy](../frontend/src/components/layout/portalNavigation.json) in
sync. The permission suite checks their parity. API authorization still
runs on every protected business request.

An open or investigating case can carry up to ten exact project references.
The case owner proposes each addition or removal. Both operators need
`cases.manage` and `simulation.start`, and the reviewer must be a separate
assigned case member. Review uses the existing passkey proof. Each applied
change advances the case revision and invalidates earlier support views.
The review shows only the submitted project reference and keeps the decision
in the case audit history.
Revision 084 passed 139 focused backend checks and six Chrome scenarios.
Chrome approved both the scope addition and removal. The disposable
PostgreSQL restore retained both decisions and the append-only audit history.

Project projections intersect the reviewed case project scope with the
account's live Projects permission and membership. Company-wide project
access is still limited to projects in the case. The list binds the visible
set to the approved action. The detail view binds one exact project and shows
its case-local label, lifecycle status and capped milestone and task counts.
If the approved list changes or the detail project becomes inaccessible, the
request fails and closes that view. No project IDs, names, documents or
financial details are returned by either projection.
Revision 085 passed 142 focused backend tests and a disposable restore of
both applied project views. Six Chrome scenarios passed after updating
the case fixture to expect the selected project manager during review.
Chrome approved, displayed and ended both project projections.

Revision 083 passed 138 focused backend tests and six Chrome scenarios in
the isolated release rehearsal. Chrome confirmed independent review, the
visible and hidden route labels, and closure of the navigation view. The
disposable PostgreSQL restore retained the applied review and audit history.

The request-summary adapter requires an exact event already linked through
the case's evidence review and attributed to the approved business account.
The requester and independent reviewer see the event reference. The original
technical session can read the HTTP method, status, observed time and opaque
request reference. The view denies reads after the evidence is withdrawn
or no longer attributable to the case subject. It omits the endpoint,
request contents, session identifiers and client metadata.

The revision 082 validation passed 126 backend checks and a disposable
restore. After correcting the Chrome fixture to use a separate event
captured after mitigation, the focused run passed three backend checks
and the full Chrome case scenario. Chrome approved, displayed and ended
the request summary before closing the case.

The local overlay on `21750a2` passed 104 backend checks and five Chrome
scenarios through revision `202605310076`. The permission explanation test
verified review before opening, denial to a different session, a redacted
role-only response, and denial after ending. Chrome exercised the same
workflow with synthetic passkeys. A disposable restore retained permission
view audit records and the downgrade guard rejected dropping them.

The `logs.audit` capability reads redacted event labels, timestamps and
opaque technical references for an assigned case. It accepts up to 24
hours and 100 events. The disclosure itself is recorded before results are
returned. Audit output excludes business-account IDs, free-text reasons,
credentials and original request bodies.

#### Production operator record

Both proposed operators use separate technical identity records. Record the
verified person and mailbox ownership before the offline bootstrap ceremony.

| Proposed mailbox | Identity and authority |
| --- | --- |
| First custodian | Record the designated dedicated mailbox in the restricted activation record. Proposed bootstrap `operator.manage`, followed by individually reviewed `cases.manage`, `logs.runtime`, `health.read`, `directory.read`, `account.request`, and `logs.audit` grants as assigned. |
| Second custodian pending | Record a separately verified person and their dedicated technical mailbox in the restricted approval record. Preserve the existing Managing Director identity and business permissions. |

Record the approved office or VPN egress IPv4/IPv6 addresses or CIDRs in
the restricted activation record. Use addresses as seen by Nginx. The
host operator verifies the direct ingress target, DNS record and served
certificate, then tests both an approved and a denied source before
distributing invitations. If either source check fails, disable the host
and retain the pending operator records while correcting ingress.

#### Minimal owner-approved activation record

Use one private operational JSON record for activation; a separate signed
Google Drive document is not required. Keep the record and its SHA-256 sidecar
in an owner-controlled directory with mode `0700` and files with mode `0600`.
The digest identifies the exact bytes and detects later edits; it is not a
digital signature. Leave unknown fields empty and keep the record in `pending`
status until the evidence is verified.

The record must capture the owner approval reference and timestamp; exact
production candidate SHA and successful self-hosted CI run/attempt; current
deployed SHA and database revision; target Alembic head; verified encrypted
backup and isolated restore/migration rehearsal references; recovery-forward
and application rollback plan; and the approved maintenance start and end in
`Asia/Qatar`, including operator, writer-drain, reviewer and abort criteria.
It must also identify two separately verified custodians with dedicated,
distinct mailboxes and two distinct registered passkeys each, the distinct
preparer and independent reviewer, actual Nginx-observed office/VPN source
CIDRs with explicit owner approval, the certificate fingerprint/SAN/expiry
and chain/key checks, tested virtual-host and allowlist hashes, DNS-only A
target, and allowed/denied access plus business-portal health results. Mark a
check successful only after observing its result. Never put the confirmation
codeword, OTPs, passkey material, invitations or private keys in this record;
the owner still supplies the codeword immediately before irreversible
production actions.

Keep the existing bootstrap input strict and separate from the broader
activation record. Store its exact `version: 1`,
`purpose: "initial_support_custody"`, distinct UUIDs in `preparer_reference`
and `reviewer_reference`, and two ordered `custodians` entries with
`person_reference` and `mailbox` under the activation record's
`bootstrap_custody` object. A reviewer independently verifies the outer
owner-approved record, both identities and mailbox ownership, and that the
nested bootstrap roster matches. Project only that nested object into a new
private file before using the existing `bootstrap_support.py` command:

```bash
umask 077
jq -cS '.bootstrap_custody' "$ACTIVATION_RECORD" > "$BOOTSTRAP_APPROVAL"
chmod 0600 "$BOOTSTRAP_APPROVAL"
sha256sum "$ACTIVATION_RECORD" "$BOOTSTRAP_APPROVAL"
```

The bootstrap command continues to verify its own exact SHA-256, reject extra
fields, require two different custodians and distinct mailboxes, and require a
reviewer distinct from the preparer and both custodians. Do not broaden that
schema to accept the operational fields. Record the outer activation-record
digest separately from the projected bootstrap digest.

From the tested backend on the approved host, run
`python -m scripts.bootstrap_support --approval <private-file> --approval-sha256 <approved-sha256>`
to verify the record locally. For the separately authorized issuance, add
`--apply --output <new-file-in-private-directory>`. The command writes the
operator references and invitations to that protected file. Give each
custodian only their own invitations through the approved private channel.
Initial issuance can run with ingress disabled on the migrated backend.
After issuance, run the same command with the approval arguments and
`--write-otp-config <new-private-env-file>` in place of `--apply`. It
derives the two mailbox bindings from the matching issued registry and
writes only the recipient setting. Install that setting and an independent
generated OTP key in the protected runtime configuration. Run
`--verify-otp-config` with the same approval arguments in the configured
backend to confirm both bindings before operator sign-in. The check
reports success or failure without printing either mailbox or key.

For a reviewed single-owner deployment, use a version `2` private record with
purpose `initial_single_owner_custody`, an `owner_approval_reference`, and
exactly one `custodians` entry. This mode still requires two device-bound
passkeys. Set `SUPPORT_CUSTODY_MODE=single_owner` with the sole approved OTP
recipient. Runtime sign-in verifies the configured owner against the immutable
bootstrap registry. Paired deployments keep their existing OTP requirements.

Case actions and evidence export receipts record the authorization mode.
In single-owner mode, the owner confirms the action or export using a fresh,
action-bound passkey. The receipt leaves reviewer identity empty. Evidence
downloads still require their own proof and stay bound to the originating
session. A single owner cannot add a second case operator through case actions.
Eligible business-account commands require a fresh passkey in the session
that created the proposal. Protected-account session revocation, unlock,
disable and reactivation use the same owner confirmation, and disable still
protects the last usable director. Protected-account password recovery
requires independent offline verification of the target's identity and remains
unavailable in single-owner mode. For eligible accounts, recovery email dispatch
rechecks the originating session and verified business-account destination.

If the only operator loses both passkeys, keep technical access locked.
Bootstrap reissue is available only before initial activation. Email OTP
cannot recover the operator on its own. An authorized recovery ceremony
requires independent verification of the owner's identity and a separately
reviewed recovery procedure before any credentials can be re-enrolled.

Treat revisions `094`–`097` as one reviewed forward migration chain. Before
maintenance, verify the source head, independent database-and-object recovery,
and an isolated restore. Confirm that initial custody is uninitialized before
selecting single-owner mode. An existing paired bootstrap stays paired and needs
a separately designed transition. The business user removal API deactivates
the account and revokes its sessions while retaining its identity and audit
references. Review database maintenance and imports for hard deletes, truncation
or rewrites of audit history before applying `094`.

After upgrading, verify the schema head and business portal before enabling
technical ingress. If validation fails, keep technical ingress disabled and
preserve the migrated database and audit evidence. Roll back application images
only after checking compatibility against the actual schema and custody state.
Revision `094` blocks downgrade, and later revisions protect recorded custody
and authorization evidence. Use a forward fix or the separately authorized
isolated recovery procedure rather than dropping columns or bypassing triggers.

Use `--reissue` with the same approval before activation to replace unused
invitations if the ten-minute lifetime elapses while configuring ingress.
Reissue keeps the approved operator references. Both operators remain
pending until both have registered two
distinct passkeys, when only `operator.manage` is granted to each. Later
grants use the independent custody workflow. Activation and device
registration are retained in the bootstrap audit. See the
[CLI parity inventory](CLI_ADMINISTRATION.md#super-admin-command-parity).

Revision 086 passed 145 focused backend tests and six existing Chrome
scenarios. The API verified that the first custodian could sign in only
after both had enrolled two passkeys. A separate CLI rehearsal on a fresh
migrated database wrote four invitations to a mode `0600` file and rejected
approval and audit edits. Both operators stayed pending until the fourth
synthetic passkey was registered, when the initial custody grants took effect.

Enrollment and recovery issue two ten-minute one-use invitations after
independent review. Deliver each invitation only through the verified
private channel. The [CLI registration handoff](CLI_ADMINISTRATION.md#super-admin-command-parity)
can prepare a private file for one device at a time and confirm its state
via the existing invitation. Registration requires a resident passkey with user
verification at the pinned support origin. The application checks distinct
credential keys and rejects backup-eligible credentials during registration
and sign-in. The ceremony must verify two physical devices and their custody.
See the [WebAuthn backup state model](https://www.w3.org/TR/webauthn-3/#sctn-credential-backup). Record the reviewer,
separate approver, device custody and exact persistent grants before
requesting confirmation for the concrete activation. Suspension and
recovery revoke earlier credential and session authority.

Revision `067` retains prior custody evidence under the new table names.
Keep support ingress closed when rolling back to code from before that
revision. Production rollout still requires a committed candidate, passing
self-hosted CI for the candidate SHA, the approved maintenance procedure and
a verified restricted DNS/TLS and proxy configuration. Verify production
denials on both hostnames before opening an authenticated support session.


### One-time forward-only 093–097 preparation (not enrolled)

The owner-approved local preparation accepts permanent data loss for this exact
exception; it must not add backup, restore or independent-destination requirements
to this exception. Existing backups/audit remain retained. A fresh designated
owner codeword is required before commit/push, privileged installation, live permit,
migration or deployment. The modified candidate needs a NEW exact-main CI run:
CI44463432841 validates only d8e147c, not these local edits.

The manual workflow selector and host event check are prepared, but the host rejects
this mode before source staging/activation. Do not remove that refusal until the
operator-controlled maintenance ingress block, writer and database-session drain,
read-only smoke activation, failure containment and receipt sequence are implemented
and reviewed together. Current apply_runtime starts worker/beat with ingress, so
using it unchanged violates this exception's smoke-before-writes requirement.

forward_release_contract.py validates a root-controlled private permit bound to SHA,
CI run, deployment run/attempt, installed entrypoint digest,093/097 and a maximum
30-minute window. A separate atomic non-overwriting consumed marker prevents replay;
its parent directories must be operator-owned and non-writable by runner/others.
This helper does not issue permits or establish owner approval. It is not yet called
by the fail-closed execution path. No real permit has been created or consumed.

Next implementation: retain existing provenance/configuration guards; require the
independent maintenance write block; verify zero incompatible writers and client
sessions; recheck live093 and complete candidate097 chain/data constraints; consume
the exact permit under lock immediately before irreversible work; migrate forward;
on any error keep ingress/writers stopped and retain errors without old-image
rollback. Start only what is necessary for read-only smoke behind the write block,
verify actual schema/constraints/runtime/assets/business authorization, then resume
workers/beat and reopen writes. Record FORWARD-ONLY RELEASE — BACKUP/RECOVERY WAIVED
BY OWNER with exact identities and maintenance times. No Super Admin changes.
The original pinned061–093 and normal backup/migration guards remain unchanged.


#### Verified local maintenance mechanism (still unenrolled)

maintenance_ingress.py produces a business-vhost guard allowing only GET/HEAD for
static login/assets/service-worker and exact readiness paths. It denies ALL business,
authentication, object and support APIs, including their GET routes. This avoids
assuming every GET is read-only. A disposable network-disabled Nginx1.25 test verified
actual503 responses for those routes and POST/readiness, and successful static/readiness
GET probes. The production readiness handler is excluded from audit middleware and
checks database connectivity. The synthetic Nginx backend is not a production application.

forward_maintenance_sequence.py specifies and tests stop/drain → zero clients →
source/data checks → consume exact permit → migrate → verify097 → backend plus guarded
Nginx only → read-only smoke → workers verified → business ingress reopening → receipt.
Every failed phase preserves containment; no old-image rollback/backup requirement is
introduced for this exact exception. It is an unenrolled operator boundary, not shell
execution. The host refusal remains. No guard was installed/reloaded on production.

Before enrollment, prove the actual Compose/TLS topology applies the guard at every
business ingress with no direct backend reachability or surviving writer; verify drain
against actual client roles and one-off jobs; check backend startup does not run writes;
run exact-candidate full-stack smoke and failure containment. A generic callback test
cannot prove those properties. Login and business APIs intentionally stay blocked during
read-only smoke; their authenticated workflow tests require a separately controlled
post-reopen verification stage, not a false claim they ran under this block.

#### Disposable actual API/TLS/worker boundary verification

`RUN_FORWARD097_STACK=1` enables `test_forward097_stack.py`. This uses exact candidate
backend source mounted read-only, a locally built requirements-matched dependency image,
a new internal Docker network, synthetic PostgreSQL and Redis, and generated fixture-only
TLS/JWT keys. It migrates synthetic schema 093 to 097, starts the real production-mode
API, and verifies lifecycle audit appends remain enabled. Guarded TLS ingress permits
readiness but refuses business/auth/support/object requests; smoke requests do not append
audit records. No backend/database host port is published. A real Celery worker on an
empty fixture queue starts after smoke while ingress stays blocked. Only then is fixture
business ingress reopened, yielding the expected unauthenticated rejection. Worker/API
shutdown leaves zero other database clients. All owned containers/volumes/network are
removed. Beat, real queued work, object storage, monitoring, live TLS/proxy configuration,
production peer networks and actual production data are not qualified by this fixture.

This adds tests, not production runtime wiring. The host mode still intentionally refuses
before staging. Enrollment still requires a reviewed concrete operator adapter binding
protected permit validation/consumption, authoritative running-service inventory, ingress
configuration and reload, in-flight job drain (without forced task loss), actual database
session drain/data validation, exact candidate startup, guarded smoke, controlled worker/
beat reopening and durable failure containment. Expected system lifecycle audit writes are
not domain/scheduler traffic. The existing business nginx generator and abstract sequence
must not be treated as an installed write block or an executable host release protocol.

#### Durable adapter attempt journal (local-only)

`forward_adapter_journal.py` exercises statically supplied trusted operator boundaries
with an operator-owned, exclusive-create `forward097.attempt` marker. Each phase intent
and completion is fsynced; the marker is never automatically deleted, overwritten or
resumed, even after success. A process loss after intent therefore blocks retry pending
operator diagnosis. Every callback failure attempts containment; containment failure is
explicitly recorded as unknown, never as safe. Phase records contain no secrets or raw
exception output. This journal is NOT a qualification receipt or proof of stopped writers.
It does not issue or replace the separate byte-bound permit and does not authorize actions.

Production integration must live in the reviewed root-installed entrypoint, not a dynamic
module loaded from a candidate archive. Trusted functions must verify the effective Compose
services/networks/binds against the installed policy and discover unexpected containers,
external DB clients and host schedulers before stopping anything. A maintenance marker
must be honored on process restart by the operator-controlled ingress/runtime path, not
merely by this Python process. Tested local journaling alone cannot stop a Docker restart
policy from reviving a writer. The concrete host adapter, startup persistence mechanism,
beat/in-flight job draining and post-crash operator recovery remain unenrolled. The existing
host refusal is intentionally unchanged; no codeword is appropriate for this nonrunnable
candidate. No backup prerequisite is reintroduced for the specifically approved exception.

#### Concrete isolated Compose commands

`compose_maintenance.py` now executes real Docker inventory, Celery active/reserved/
scheduled inspection, TERM-only warm stops and guarded backend/nginx-before-worker
restart against a frozen, explicitly labeled fixture inventory. Unknown containers,
replaced IDs, published ports, automatic restart policy, absent/ambiguous worker replies
or busy work refuse progression. Warm-stop timeout never escalates to forced kill.
The actual API/TLS/PostgreSQL test exercises these commands and verifies zero sessions
after drain and worker-off state during smoke. Eight negative tests cover topology and
worker-state refusals. This adapter intentionally supports only the isolated three-service
application fixture; it refuses production ports and cannot serve as a production command.

Before host enrollment, extend the reviewed installed adapter to the actual complete
Compose inventory, stop beat before worker drain, account for queued/delayed/outbox work,
verify all producers cannot reconnect, apply the reviewed real ingress-port policy and
bind the existing exact-source/permit/journal functions. Independent review must assess
failure containment during partial stop/start and the restart-persistent operator path.
Do not remove the host refusal or run this fixture adapter against production.

**Latest scheduler qualification failure:** Adding real Celery beat to the disposable
stack allowed initial drain and guarded restart, but a subsequent warm-stop of the
just-restarted beat did not finish within30seconds. The adapter correctly raised
`Warm stop incomplete; never force-kill`. Result:1failed/8passed66.09seconds.
Therefore the optional beat extension is experimental/unqualified, not a passing release
path. Fixture cleanup removed only its own synthetic resources. The next precise test
work is to establish observable beat startup readiness and graceful shutdown behavior
across restart, without timing-only assumptions or production force termination. Earlier
168-test and worker-only results do not establish scheduler readiness.

**Bounded scheduler retry:** The fixture now records beat lifecycle output and waits for
the second actual `beat: Starting...` event before its post-restart shutdown. This retry
passed in40.82seconds, including warm stop and final zero DB-session check. This supports
a startup-readiness race as a cause, but does not prove all scheduler/job states are safe.
The production adapter is still unenrolled: observable readiness must be a concrete trusted
runtime prerequisite, not a test-only wait or stale log count. Keep the failed run as evidence.

**Adapter startup prerequisite:** The concrete isolated adapter now waits for structured
`celery.beat` startup output from Docker logs scoped to the exact current container
`StartedAt`, and rejects exit/restart during that wait. The fixture-only external wait
was removed. Missing startup invokes containment; if one warm stop fails, remaining
services are still attempted and incomplete containment is raised explicitly. Actual
synthetic stack plus negative checks:11passed40.31seconds. Startup announcement is a
bounded lifecycle prerequisite, not proof every scheduled business job is safe. Production
qualification/permit wiring and host enrollment remain absent; host refusal is unchanged.

**Unknown-producer integration evidence:** A real extra container carrying the same
Compose project label now causes the concrete drain operation to refuse before stopping
nginx/backend. After removing only that disposable producer, the isolated positive path
still passes. Actual stack plus negative tests:11passed41.85seconds.

**Software not yet written (not an installation-only gate):** The host-specific dispatcher
must replace the unconditional refusal with concrete reviewed code that validates the
installed module/permit file ownership and bytes, reuses exact main/CI/deploy identity,
creates its durable attempt under the host lock, freezes the complete existing Compose
inventory, applies and verifies guarded real TLS ingress, drains beat/worker/API and DB
sessions, consumes the exact permit, runs only093→097, starts guarded candidate backend,
verifies served frontend hashes/readiness and unchanged Super Admin denial, then reopens
writers/ingress and records the real deployed receipt. Failure containment must attach
before the first stop and must never select old-image rollback after migration. These
functions have not yet been assembled/tested as a single host-specific implementation.
Root installation alone would NOT fix this gap; do not request codeword for current patch.

#### Assembled executable isolated dispatcher

`python deploy/forward097_isolated_dispatch.py --fixture-policy PATH --fixture-state DIR`
now performs an actual cohesive synthetic release: private fixed-input policy, exact-image
and full application inventory checks, internal-network/no-published-port refusal, durable
attempt before stopping writers, real Celery drain and zero PostgreSQL clients, exact
single-use permit consumption, fixed Alembic093→097 command, target-schema check, guarded
TLS/API smoke, worker/beat startup, controlled ingress reload and truthful synthetic journal.
It accepts only the disposable fixture database credential and project naming convention;
it is NOT a production mode or a replacement for actual GitHub CI verification. The policy
contains synthetic run identity in tests, never a forged production approval/receipt.

The permit now binds CI run AND CI attempt independently from deployment run/attempt.
The local host script also refuses every entry mode when a durable `forward097.attempt`
exists, before ordinary schema-equality or already-deployed paths. No automatic marker
reset exists. Production forward-mode refusal remains; this marker change is not installed.

The remaining production-specific software work is to replace fixture-only settings with
the reviewed root-installed byte-bound policy and actual GitHub evidence, reuse the host's
validated effective Compose/TLS/secret/retention configuration, handle immutable exact
candidate image creation and real frontend hashes, and link completed/failure journal
state to the real deployment pointer. This is not merely an installation approval gap.
No additional backup/restore gate is imposed on the owner's exact093→097 exception.

#### Production-intended wiring now written locally (not installed or release-ready)

The latest local preparation supersedes earlier 'software not written' checkpoints:
`hostinger-release.sh` now connects manual forward mode to the fixed root-installed
`forward097-runtime.sh`, `consume-forward097.py` and `forward_release_contract.py`.
The entrypoint embeds helper hashes and validates root ownership, protected parent paths
and exact bytes before staging. The existing effective-Compose, TLS/JWT/secret/retention,
main and exact-CI validators remain in use. Forward mode prevalidates its permit before
stopping writers, consumes it only after source/data/session checks, migrates only093→097,
publishes/starts under the guarded overlay, verifies served frontend hashes and readiness,
then starts workers/beat and restores the existing ingress configuration. The normal
backup/compatible-rollback path is unchanged; only forward mode uses its specific exception.
Any durable attempt blocks every later entry mode pending operator reconciliation.

Evidence:133focused shell/config/normal-release regression tests passed4.41seconds.
These use stubbed host command boundaries for production shell sequencing. The separate
assembled synthetic dispatcher passed3real Docker/Postgres/TLS positive/failure cases.
These are complementary, NOT a full actual-production-Compose execution of this new shell
extension. Independent review, lint cleanup/hash resealing and shadow-topology qualification
remain outstanding. Do not install these files or request an execution codeword yet.

### Prepared forward097 durable serving commit (local review candidate)

The mode keeps ingress guarded through migration, exact catalog validation,
backend smoke, durable current-pointer checkpoint, and writer identity/running
verification. Immediately before unguarded ingress it exclusively creates and
fsyncs `forward097.reopen-commit`, bound to candidate/SHA, CI run/attempt and
manual deploy run/attempt. This is the serving authorization commit point, not
proof of observed deployment success. A process loss after this point may leave
verified serving active with `FORWARD_ACTIVATION_PENDING`; never label that a
completed release until independently observing current pointer, image IDs,
schema097, ingress state and readiness. Before this commit point, ingress remains
closed/guarded. Keep the all-mode `forward097.attempt` interlock in either case.

Reconciliation is deliberately operator-controlled: collect the attempt,
serving commit, candidate/pointer and live verification; contain writers/ingress
if those disagree. Never rerun the consumed migration permit or downgrade.
Retire/archive the marker only under separately reviewed host operations after
reconciling the exact attempt; no automatic marker deletion exists. `DEPLOYED`
is finalized only after post-reopen observation. The exception waives secured
backup/restore only for this exact mode; it is not backup evidence.

Local tests include a SIGKILL of the actual shell reopening function after a
stubbed ingress recreate: durable serving commit survived and completed receipt
remained absent. This proves shell sequencing and persistence only, not actual
Docker/TLS/host crash behavior. Production topology interruption validation and
independent review remain prerequisites to claiming the candidate qualified.
