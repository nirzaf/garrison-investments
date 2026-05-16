# CI/CD, Staging, Production, and Operations

## Title
CI/CD, Staging, Production, and Operations

## User Story
As an Operation Manager,
I want controlled staging and production deployment workflows,
so that releases can be validated before production changes go live.

## Description
Implement automated checks, staging deployment, production approval, backups, and basic operational monitoring. Production deployment must require Operation Manager approval.

## Acceptance Criteria
1. Given a pull request is opened,
   When CI runs,
   Then backend tests, frontend checks, and build validation are executed.

2. Given code is merged to the staging branch,
   When the deployment workflow runs,
   Then the staging environment is deployed automatically.

3. Given a production deployment is requested,
   When the workflow reaches the production step,
   Then Operation Manager approval is required before deployment continues.

4. Given backups are configured,
   When the scheduled backup job runs,
   Then encrypted database backups are stored according to the retention policy.

## Business Rules
- Staging and production environments are required.
- Production deployment requires manual approval by the Operation Manager.
- Daily backups must be retained for 30 days.
- Monthly backups must be retained for 12 months.
- Backup restore testing must be performed monthly.
- Business-critical outages must alert Admin or technical support and the Operation Manager.

## UI/UX Notes
- Deployment status does not require an in-app screen for MVP.
- Operational alerts should be readable and action-oriented.
- User-facing downtime messages must be clear and non-technical.

## Technical Notes
- Use GitHub Actions for lint, test, build, staging deploy, and production deploy.
- Target a Docker Compose based VPS deployment unless the final provider changes.
- Add basic uptime and error monitoring in Phase 1.
- Document restore procedures and production rollback steps.
- Align CI with `../../ARCHITECTURE.md`: backend `ruff`, `mypy`, `pytest`; frontend ESLint, Prettier, Vitest, React Testing Library, and Vite build.
- Production must run static frontend assets through Nginx, reverse proxy `/api/*` to FastAPI, and never serve private files directly.
- Backups should follow the architecture retention model: daily pg_dump, WAL archive, monthly archive, MinIO bucket sync, and monthly restore test.

## Priority
High

## Dependencies
- Final hosting provider or VPS details.
- Internal server owner or contact.
- Production approval process and approver identity.
- Backup storage provider or location.

## Definition of Done
- CI validates pull requests.
- Staging deployment is automated.
- Production deployment is approval-gated.
- Backup schedule and retention are implemented.
- Restore procedure is documented.
- Basic monitoring and alert routing are configured.
