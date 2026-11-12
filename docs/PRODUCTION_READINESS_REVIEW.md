# Production Readiness Review

**Historical review dated July 27, 2026.** This page records the scope and staging findings of that review. Current release evidence belongs in the [deployment and sign-off runbook](OPERATIONS_AND_DEPLOYMENT.md#5-launch-evidence-capture--sign-off).

[Documentation index](README.md) · [Current architecture](ARCHITECTURE.md) · [Production deployments](OPERATIONS_AND_DEPLOYMENT.md#production-deployments-from-github-actions)

## Review scope

The review covered the portal's browser and API architecture, role and project access, authentication, asynchronous jobs, PostgreSQL recovery, and audit and operational logging. It also identified launch checks for DNS and TLS, browser and device acceptance, mail and alert delivery, backup restoration, and staged preview access.

## Staging findings recorded in the review

- Signed preview links previously targeted an inaccessible storage port. The reviewed deployment exposed the same-origin `/portal-files/` route at `erp.garrisons.lk` for newly generated preview links.
- The seed script was updated to use larger JPEG assets when available and to replace tiny seed placeholders in object storage. This concerned seeded preview data.

## Current references

| Topic | Where to look |
| --- | --- |
| Release gates, host activation, migrations, and recovery | [Operations and deployment guide](OPERATIONS_AND_DEPLOYMENT.md) |
| Environment-specific configuration and staging acceptance | [Staging deployment](../STAGING_DEPLOYMENT.md) |
| API and UI access rules | [Roles and permissions](ROLES_AND_PERMISSIONS.md) |
| Audit search, container diagnostics, and alerts | [Logging and remote CLI](LOGGING_AND_REMOTE_CLI.md) |
| Automated checks and development setup | [Project README](../README.md#verification) |
