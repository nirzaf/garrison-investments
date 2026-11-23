# GitHub-hosted production deployment channel

**Status on 2026-11-23:** the restricted transport is installed on Hostinger and passed a direct live probe. GitHub's `Production` environment is limited to `main` and holds the deployment credentials. The published `Deploy production` workflow is active and still selects the Hostinger runner. The hosted workflow is local and awaits publication and a GitHub-hosted probe.

## Design

The `Deploy production` job runs on GitHub-hosted `ubuntu-24.04`. It connects to a dedicated non-root Hostinger account through a Cloudflare Tunnel SSH hostname protected by an Access Service Auth policy. The workflow pins the Cloudflare `cloudflared` 2026.10.7 Linux AMD64 release by its published SHA-256 digest, pins the SSH host key, and authenticates with a dedicated SSH key. It sends the short-lived GitHub Actions token to the host over standard input, never in a command argument or log.

The host account uses a system shell to launch the forced command. SSH blocks interactive shell access, TTY, forwarding, and password login for this account. `ForceCommand` accepts only a read-only `probe` or a structured release request. A root-owned sudo helper validates the request and invokes `/usr/local/sbin/garrison-deploy` with the existing release arguments. The host launcher still checks the deployment lock, CI, incident hold, maintenance permits, and schema and records the release receipt.

## Host and Cloudflare setup

The installed transport uses the dedicated `garrisons-github-production` tunnel and `deploy-ssh.garrisons.lk`. The connector runs under [garrison-cloudflared.service](../deploy/garrison-cloudflared.service) and loads its connector token as a systemd credential. Cloudflare reports the tunnel healthy and attaches only the dedicated service-token policy to the SSH hostname. The live probe accepted the dedicated SSH key within the tunnel and denied missing and invalid Access tokens, the wrong SSH key, direct public SSH with the correct key, arbitrary commands, and forwarding. The SSH configuration denies TTY allocation.

1. Identify or create a Cloudflare Tunnel that is verified to run on the Hostinger production VPS. The currently inventoried `ckc-portal` tunnel had no Garrisons hostnames, so do not assume it terminates on this VPS.
2. Create a Cloudflare Access self-hosted application for a dedicated hostname with a Service Auth policy containing only the deployment service token. Then publish the tunnel route to `ssh://127.0.0.1:22` for that hostname.
3. Create a local account named `garrison-gh-deploy` with a non-root public key. Install `deploy/garrison-gh-force-command.sh` as `/usr/local/lib/garrison-release/garrison-gh-force-command` and `deploy/garrison-gh-release-root.sh` as `/usr/local/sbin/garrison-gh-release-root`, both root-owned and non-writable by the deployment account.
4. Install `deploy/garrison-gh-deploy.sudoers` in `/etc/sudoers.d/` with mode `0440`; verify it with `visudo -cf`. It grants only the root helper and accepts no command-line arguments.
5. Install `deploy/garrison-gh-deploy-sshd.conf` under the active `sshd_config.d` include directory. Write the dedicated public key to `/etc/ssh/garrison-deploy/authorized_keys` with the options `restrict,from="127.0.0.1"` and root ownership for both directory and file. Give `sshd` read access for the account and only root write access. Check the effective directives with `sshd -T -C user=garrison-gh-deploy,host=localhost,addr=127.0.0.1` and run `sshd -t` before reload. Keep the existing administrator session open while validating access in a second session.
6. Independently verify the SSH host public-key fingerprint through the authorized Hostinger administration path. Do not use `ssh-keyscan` as the trust source.

The administrator SSH policy is separate. The loopback-only deployment key rule must deny authentication to the dedicated account through the public SSH listener, even with the valid key.

## GitHub Production environment configuration

Before adding credentials, restrict the `Production` environment to deployments from `main`. Manual reviewer approval is not required for the beta auto-deploy flow, but branch scope must be explicit.

Create these `Production` environment values without putting them in source control:

| Name | Type | Purpose |
| --- | --- | --- |
| `HOSTINGER_DEPLOY_SSH_HOST` | Variable | Exact Cloudflare Access hostname for the SSH route |
| `HOSTINGER_DEPLOY_SSH_KNOWN_HOSTS` | Secret | Independently verified known-hosts entry for that hostname |
| `HOSTINGER_DEPLOY_SSH_PRIVATE_KEY` | Secret | Dedicated, unencrypted automation key; the corresponding public key is restricted by host `ForceCommand` |
| `CLOUDFLARE_DEPLOY_SERVICE_TOKEN_ID` | Secret | Cloudflare Access service-token client ID |
| `CLOUDFLARE_DEPLOY_SERVICE_TOKEN_SECRET` | Secret | Cloudflare Access service-token client secret |

The deployment SSH key and Access service token are separate factors. Do not reuse the root administrator key. Set a service-token expiry and rotation owner in Cloudflare. Do not print, upload, or check in either private credential.

## Safe activation order

1. Review the candidate workflow and helper scripts on `main`; run all applicable CI checks on the exact SHA.
2. Complete and independently verify host, Access, SSH-key, and GitHub environment setup above. Keep releases disabled on the hosted workflow until its transport has been checked.
3. Leave the repository Actions variable `HOSTED_PRODUCTION_RELEASES_ENABLED` unset. Enable `Deploy production` for the authorized probe and dispatch it on `main` with `transport_check=true` and no CI run ID. The probe must report `restricted deployment transport ready`. With the variable unset, the workflow skips release jobs.
4. Verify that missing and wrong service tokens, a wrong SSH key, a direct public SSH connection with the correct key, arbitrary commands, and forwarding and TTY requests are denied. Confirm the deployment identity can invoke only the no-argument root helper via sudo.
5. After the transport checks and production activation authorization, set the repository variable `HOSTED_PRODUCTION_RELEASES_ENABLED` to `true`. Dispatch one release with an eligible exact-SHA CI run. Future successful push CI runs on `main` qualify automatically.
6. Verify the deployment run and the root-generated host receipt, running image IDs, readiness, and active SHA. Preserve the existing runner files until a successful cloud-hosted release and recovery procedure have both been verified.

## Rollback

If the hosted probe fails, leave hosted releases disabled and investigate the failing connection. For an application release failure, use the [production rollback procedure](OPERATIONS_AND_DEPLOYMENT.md#rollback). To suspend the hosted transport, disable hosted releases, stop `garrison-cloudflared.service`, and disable the dedicated Access service token. Preserve the production release receipts and the host's incident and PostgreSQL maintenance guards.

## CI timing note

The exact `main` CI run `45174272215` completed all five push jobs on GitHub-hosted `ubuntu-24.04` in 4m47s. Earlier comparable five-job self-hosted CI took 17m47s, but that sample included a long queue delay and is not enough to claim a repeatable speedup. Keep the full pull-request and manual regression checks intact and continue comparing same-scope runs.
