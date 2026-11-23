# Repository documentation

Use the [documentation map](docs/README.md) to find the guide and code for the task.
The [root README](README.md) covers features, architecture diagrams, local setup, and verification.
Garrisons is an internal beta; apply the [beta release policy](docs/BETA_RELEASE_POLICY.md)
when classifying acceptance work. Optional formal-acceptance artifacts do not
block unrelated beta iterations.
Read [system architecture](docs/ARCHITECTURE.md) and [backend architecture](backend/ARCHITECTURE.md) before changing cross-cutting flows.
Check the linked code, migrations, or workflows before updating a behavior claim. Keep changes in
the guide that owns the topic, link to it from related pages, and verify relative Markdown links and anchors after editing docs.

On every release iteration, review the [CI and deployment timings](docs/OPERATIONS_AND_DEPLOYMENT.md#review-pipeline-time-on-every-release) for the exact candidate. Look for ways to shorten the slowest path while preserving required checks.

## Key entry points

| Topic | Owning guide | Primary source paths |
| --- | --- | --- |
| Features and UI routes | [Features and roles](README.md#implemented-features) | [Frontend routes](frontend/src/App.tsx), [API routers](backend/app/api/v1/) |
| Permissions and scoping | [Roles and permissions](docs/ROLES_AND_PERMISSIONS.md) | [Permission checks](backend/app/utils/permissions.py), [route deps](backend/app/api/dependencies.py), [services](backend/app/services/) |
| API contract | [OpenAPI contract](docs/openapi.json), [regeneration steps](README.md#api-contract-changes) | [API schemas](backend/app/schemas/), [generated UI types](frontend/src/api/schema.d.ts) |
| Database and migrations | [Schema index](docs/schema/README.md) | [SQLAlchemy models](backend/app/models/), [Alembic revisions](backend/alembic/versions/) |
| CLI administration | [CLI administration](docs/CLI_ADMINISTRATION.md) | [garrisonctl](backend/scripts/garrisonctl.py) |
| Feedback and triage | [Feedback and triage](docs/LOGGING_AND_REMOTE_CLI.md#user-feedback-and-triage) | [Feedback service](backend/app/services/feedback_service.py), [feedback inbox](frontend/src/pages/support/SupportFeedbackInbox.tsx) |
| Logging and monitoring | [Logging and remote CLI](docs/LOGGING_AND_REMOTE_CLI.md) | [Log routes](backend/app/api/v1/logs.py), [observability config](observability/) |
| Production CD and rollback | [Operations and deployment](docs/OPERATIONS_AND_DEPLOYMENT.md) | [Deploy workflow](.github/workflows/deploy.yml), [host release script](deploy/hostinger-release.sh), [Prod Compose](docker-compose.prod.yml) |
| Optional post-release acceptance | [Post-release actions](docs/POST_RELEASE_ACTIONS.md) | [Beta release policy](docs/BETA_RELEASE_POLICY.md), [launch evidence](backend/scripts/launch_evidence.py), [templates](docs/templates/release-closure/) |

## Engineering and safety guardrails

- **Authorization and transaction boundaries:** Route dependencies enforce baseline permissions; domain services under [backend/app/services/](backend/app/services/) enforce project scoping, record ownership, state transitions, and transactional consistency.
- **API contract synchronization:** Whenever FastAPI routes ([backend/app/api/v1/](backend/app/api/v1/)) or Pydantic schemas ([backend/app/schemas/](backend/app/schemas/)) change, regenerate both [docs/openapi.json](docs/openapi.json) (`cd backend && .venv/bin/python scripts/export_openapi.py`) and [frontend/src/api/schema.d.ts](frontend/src/api/schema.d.ts) (`cd frontend && npm run api:types`).
- **Database migrations and stateful changes:** Keep models, Alembic revisions, and [schema docs](docs/schema/README.md) in sync. Use the installed launcher's [fast beta path](docs/OPERATIONS_AND_DEPLOYMENT.md#fast-beta-release-path) for supported forward migrations. PostgreSQL major upgrades, rollback-generation changes, and other stateful changes to PostgreSQL, Redis, S3/MinIO, networks, or volumes still require the [production maintenance procedure](docs/OPERATIONS_AND_DEPLOYMENT.md#production-maintenance).
- **Security and audit retention:** Keep `LOG_PURGE_ENABLED=false` (retain-only audit mode). Never commit secrets, signing keys, TLS certificates, or non-sanitized evidence; commit only unsigned templates under [docs/templates/release-closure/](docs/templates/release-closure/).
- **Release authorization:** An explicit owner request to release starts the routine beta pipeline without a separate codeword. Follow the approved maintenance procedure for destructive or out-of-band host operations.
- **Production CD vs. formal acceptance:** [.github/workflows/deploy.yml](.github/workflows/deploy.yml) and [deploy/hostinger-release.sh](deploy/hostinger-release.sh) execute technical-only safety checks after passing CI on `main` and record `Status: Deployed — Formal Acceptance Pending`. The six governance workstreams (`D-27` through `D-33`) and strict closure scripts ([release_contract.py](backend/scripts/release_contract.py), [launch_evidence.py](backend/scripts/launch_evidence.py)) are optional post-release acceptance tooling, not deployment prerequisites. Staging is retired ([STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md)).

## Verification commands

Run targeted checks matching your changes (see [Verification](README.md#verification) and [CI workflow](.github/workflows/ci.yml) for full prerequisites):

- **Backend lint, typing, OpenAPI, and tests:**
  - `cd backend && .venv/bin/ruff check . && .venv/bin/mypy .`
  - `cd backend && .venv/bin/python scripts/export_openapi.py --check`
  - `cd backend && .venv/bin/pytest -q -rs` (or targeted test modules)
- **Frontend lint, API types, unit tests, and build:**
  - `cd frontend && npm run lint && npm run api:types:check && npm test && npm run build`
- **Production Compose and deployment scripts:**
  - `docker compose --env-file .env.example -f docker-compose.prod.yml config --no-env-resolution --quiet`
  - `bash -n deploy/hostinger-release.sh`
  - `cd backend && .venv/bin/pytest -q tests/test_release_rollback.py tests/test_release_contract.py tests/test_launch_evidence.py tests/test_observability_config.py`

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, invoke the `skill` tool with `skill: "graphify"` before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
