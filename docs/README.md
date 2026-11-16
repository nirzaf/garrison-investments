# Documentation map

Start with the [project README](../README.md) for implemented features, roles, runtime diagrams, setup, and verification. Use this page to find the detailed guide and the code that defines each behavior.

## Find the right guide

| Question | Guide | Source to verify |
| --- | --- | --- |
| What does the portal implement? | [Features and roles](../README.md#implemented-features) | [Frontend routes](../frontend/src/App.tsx) and [API routers](../backend/app/api/v1/) |
| Which features are in the release scope? | [Scope inventory (`launch_readiness_only`, `G-01` excluded)](ACCEPTED_SCOPE.md) | [Launch readiness route](../frontend/src/pages/delivery/DeliveryPlanPage.tsx) and [post-release backlog](POST_RELEASE_ACTIONS.md) |
| What post-release governance items remain open? | [Post-release actions (`D-27` through `D-33`)](POST_RELEASE_ACTIONS.md) | [Operations runbook](OPERATIONS_AND_DEPLOYMENT.md#5-launch-evidence-capture--sign-off) and [release templates](templates/release-closure/README.md) |
| How do a request, a background task, and a protected file move through the system? | [System architecture](ARCHITECTURE.md) and [backend guide](../backend/ARCHITECTURE.md) | [FastAPI entry point](../backend/app/main.py), [Celery configuration](../backend/app/tasks/celery_app.py), [production Compose](../docker-compose.prod.yml), and [Nginx](../nginx/) |
| Who can read, submit, or approve a record? | [Roles and permissions](ROLES_AND_PERMISSIONS.md) | [Permission definitions](../backend/app/utils/permissions.py), route dependencies, and [domain services](../backend/app/services/) |
| What source matrix and non-source role decisions are being applied? | [Business role decisions](BUSINESS-ROLE-DECISIONS.md) | [Independent source fixture](../backend/tests/business_role_matrix.json) and the policy tests |
| Where are the historical role cutover and current role rules described? | [Historical cutover](ROLE_CATALOGUE_CUTOVER.md) and [current roles](ROLES_AND_PERMISSIONS.md) | [Read-only-by-default migration command](../backend/scripts/migrate_role_catalogue.py) and [current role keys](../backend/app/utils/permissions.py) |
| Which endpoint, payload, or response does the UI use? | [OpenAPI contract](openapi.json) and [regeneration steps](../README.md#api-contract-changes) | [API routers and schemas](../backend/app/api/v1/) and the [generated frontend types](../frontend/src/api/schema.d.ts) |
| What stores the data and enforces its constraints? | [Database schema index](schema/README.md) | [SQLAlchemy models](../backend/app/models/) and [Alembic migrations](../backend/alembic/versions/) |
| How do I manage employee records and workforce operations? | [HR and workforce](HR_WORKFORCE.md) | [HR routes](../backend/app/api/v1/hr.py) and [workspace](../frontend/src/pages/hr/HRWorkspacePage.tsx) |
| What remains to complete HR? | [HR completion ledger](HR_COMPLETION_LEDGER.md) | Capability reconciliation and executed evidence |
| How do I import existing records? | [Import templates and validation](import_templates/README.md) | [Import routes](../backend/app/api/v1/imports.py) and [import service](../backend/app/services/import_service.py) |
| How do I administer the portal from a terminal? | [Garrisons CLI administration](CLI_ADMINISTRATION.md) | [garrisonctl entry point](../backend/scripts/garrisonctl.py) and [API routers](../backend/app/api/v1/) |
| How do I validate a change locally or in CI? | [Verification commands](../README.md#verification) | [CI workflow](../.github/workflows/ci.yml), [Pytest suite](../backend/tests/), and [Chrome regressions](../frontend/e2e/) |
| How does production deploy, and how do I recover it? | [Operations and deployment runbook](OPERATIONS_AND_DEPLOYMENT.md) | [Deployment workflow](../.github/workflows/deploy.yml), [host release script](../deploy/hostinger-release.sh), and [production Compose](../docker-compose.prod.yml) |
| Is staging part of the release process? | [Staging retirement notice](../STAGING_DEPLOYMENT.md) | [Production deployment workflow](../.github/workflows/deploy.yml) |
| Where do I find audit events, service logs, or alerts? | [Logging and remote CLI](LOGGING_AND_REMOTE_CLI.md) | [Log routes](../backend/app/api/v1/logs.py), [CLI](../backend/scripts/log_cli.py), and [observability configuration](../observability/) |
| What was known during the July 2026 review? | [Historical production readiness review](PRODUCTION_READINESS_REVIEW.md) | Use the [current operations runbook](OPERATIONS_AND_DEPLOYMENT.md) for present-day release evidence and acceptance. |

## Working with these docs

1. Read [repository agent instructions](../AGENTS.md), then follow the guide for the task. Use [the feature map](../README.md#implemented-features) to identify the module, and start with its entry point before tracing into services and storage.
2. Check the executable sources in the table before relying on a behavioral, permission, schema, or deployment claim. API types describe the wire contract. Service checks describe which user can perform an action. Migrations describe what a deployed database enforces.
3. Update the guide that owns the topic when behavior changes. Link to it from other pages. Keep setup and test commands in the root README, and keep deployment and recovery procedures in the operations runbook.
4. Check paths, heading links, and diagrams after moving content. Record real deployment and UAT evidence through the runbook. The historical review and generated [knowledge graph report](../graphify-out/GRAPH_REPORT.md) are reference snapshots.
