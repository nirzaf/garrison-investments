# Backend architecture

The [portal architecture](../docs/ARCHITECTURE.md) covers runtime dependencies, API contracts, workflow invariants, and domain entry points. Use this page when making a backend change.

## Trace an API request

1. Find the operation in the [OpenAPI contract](../docs/openapi.json) and the corresponding [versioned router](app/api/v1/).
2. Read its [Pydantic request and response schemas](app/schemas/) and [authentication or permission dependencies](app/api/dependencies.py). The [access guide](../docs/ROLES_AND_PERMISSIONS.md) explains where services apply further checks.
3. Trace the [domain service](app/services/) to the [repository](app/repositories/) or direct SQLAlchemy query. Services own workflow validation and transaction boundaries. [Session setup](app/database.py) rolls back an unhandled request error.
4. Check the [SQLAlchemy models](app/models/) and [Alembic revisions](alembic/versions/) for constraints, indexes, and existing data rules. The [schema reference](../docs/schema/README.md) links each table to its sources.
5. Follow side effects into the [Celery tasks](app/tasks/) or [operator scripts](scripts/) where applicable. The [Celery setup](app/tasks/celery_app.py) defines the queues and beat schedule, and the [outbox dispatcher](app/tasks/outbox.py) publishes committed report export tasks.

## Cross-cutting entry points

| Concern | Source |
| --- | --- |
| Application startup, request context, and health checks | [App factory](app/main.py), [settings](app/config.py) |
| Error contract | [Exception models](app/utils/exceptions.py), [handlers](app/main.py) |
| Project and record scope | [Shared authorization](app/services/authorization.py), [access guide](../docs/ROLES_AND_PERMISSIONS.md) |
| Signed storage links and uploads | [Storage client](app/services/storage_service.py), [photo service](app/services/photo_service.py), [document service](app/services/document_service.py) |
| Logging, audit, and request attribution | [Observability](app/observability/), [audit middleware](app/middleware/audit.py), [client IP resolution](app/utils/request.py), [log guide](../docs/LOGGING_AND_REMOTE_CLI.md) |

Feedback submissions use the business actor from the standard bearer-token
dependency. The service projects only reporter-owned failed API requests from
the existing audit log and writes the feedback and its audit event together.
The inbox lives on the restricted support router and uses technical sessions
with `operator.manage`. See [feedback and triage](../docs/LOGGING_AND_REMOTE_CLI.md#user-feedback-and-triage).

## Verify a change

Run the relevant [backend checks](../README.md#verification) against the disposable test services. The [Pytest suite](tests/) contains endpoint regressions and the [browser fixture module](tests/browser_fixtures.py) seeds isolated data for the Google Chrome suite.

- For authorization, see the [permission matrix tests](tests/test_authorization_matrix.py), [scope tests](tests/test_scope_authorization.py), and [delegation guards](tests/test_delegation_guards.py).
- For transactional changes, start with [report and payment concurrency](tests/test_report_payment_concurrency.py), [inventory accounting](tests/test_inventory_accounting.py), [import execution](tests/test_imports.py), or [idempotency](tests/test_idempotency.py).
- For endpoint or schema changes, follow the [OpenAPI regeneration commands](../README.md#api-contract-changes) and run the [contract test](tests/test_openapi_contract.py).
- For migrations, consult the [schema reference](../docs/schema/README.md), the [Alembic environment](alembic/env.py), and the [operations runbook](../docs/OPERATIONS_AND_DEPLOYMENT.md).
