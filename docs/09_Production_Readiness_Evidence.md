# Production Readiness Evidence

Date: 2026-05-16

This file records the repo-controlled evidence required by the strict user-story review. Environment-specific sign-off still has to be completed by the deployment owner during the launch run.

## Implemented Evidence

| Area | Repository evidence |
| --- | --- |
| CI | `.github/workflows/ci.yml` runs backend Ruff, mypy, Alembic validation, pytest, frontend lint, format check, tests, build, and Docker Compose validation/build. |
| Deployment | `.github/workflows/deploy.yml` separates staging and production deployment and uses the GitHub `production` environment for production approval. |
| Runtime stack | `docker-compose.prod.yml` defines Nginx, backend, PostgreSQL, Redis, MinIO, Celery worker, and Celery beat. |
| Downtime message | `nginx/nginx.conf` routes 500/502/503/504 failures to `frontend/public/50x.html`. |
| Monitoring | `backend/scripts/health_monitor.py` checks `/health` and `/health/readiness`, exits non-zero on failure, and emails Admin/technical support plus Operation Manager recipients. |
| Backups | `backend/app/tasks/celery_app.py`, `backend/app/tasks/backup.py`, and `backend/scripts/backup.py` implement daily and monthly backup scheduling. |
| Restore procedure | `docs/06_Operations_Runbook.md` documents restore and rollback steps. |
| UAT scenarios | `docs/07_UAT_Launch_Readiness.md` and the current route/backend tests cover the launch scenario baseline. |

## Launch Sign-Off Checklist

| Sign-off item | Required owner | Evidence to attach during launch |
| --- | --- | --- |
| Production GitHub environment approver is the Operation Manager or delegated release approver | Admin / Operation Manager | Screenshot or GitHub environment settings export. |
| Staging deployment completed from the current commit | Technical support | `backend/scripts/launch_evidence.py --target staging` output with GitHub Actions run URL. |
| Production deployment approval completed | Operation Manager | `backend/scripts/launch_evidence.py --target production --approver ...` output with production approval URL. |
| `/health` and `/health/readiness` return healthy responses on production | Technical support | `backend/scripts/launch_evidence.py` runtime check output. |
| Daily backup completed successfully | Technical support | Backup task log or object-storage path recorded in `backend/scripts/launch_evidence.py` output. |
| Restore dry run completed | Technical support | `backend/scripts/restore_dry_run.py` output. |
| Uptime/error monitor sends alert to technical support and Operation Manager | Technical support | Monitor test alert screenshot or incident URL. |
| Browser/device UAT completed | QA / Operation Manager | Signed UAT checklist covering Chrome, Edge, iOS Safari, Android Chrome, and weak network. |

## Stakeholder Template Register

| Template | Repository baseline | Launch requirement |
| --- | --- | --- |
| Daily report PDF | `backend/app/services/report_export_service.py` generated PDF | Stakeholder-approved company/client layout. |
| Project progress export | `backend/app/services/analytics_service.py` Excel export | Stakeholder-approved columns and naming. |
| Material usage export | `backend/app/services/analytics_service.py` Excel export | Stakeholder-approved columns and naming. |
| Import templates | `docs/import_templates/*.csv`; CI runs `backend/scripts/validate_import_sources.py --check` | Production source spreadsheets validated with `backend/scripts/validate_import_sources.py --source ... --output ... --check` before import. |

## Executable Evidence Tools

| Evidence gap | Tool |
| --- | --- |
| Deployment run, approver, health/readiness, backup object, sign-off hashes | `backend/scripts/launch_evidence.py` |
| Backup readability and optional isolated restore execution | `backend/scripts/restore_dry_run.py` |
| Production source spreadsheet/header/value validation | `backend/scripts/validate_import_sources.py` |
| Provider-neutral health/readiness alerting | `backend/scripts/health_monitor.py` |

## Remaining Stakeholder Inputs (Prototype-Tracked)

The following inputs are surfaced in the requirements prototype as outstanding prerequisites:

| # | Input | Owner | Repository reference |
| --- | --- | --- | --- |
| 1 | Company logo, colors, typography, and paper forms | MD / Operation Manager | Prototype brand theme; `docs/08_Brand_Color_Theme.md` |
| 2 | Final first-release module sign-off | Operation Manager | Prototype launch acceptance scenarios; UAT checklist in `docs/07_UAT_Launch_Readiness.md` |
| 3 | General Manager approval/read-only authority scope | General Manager / Operation Manager | Prototype auth screen role matrix |
| 4 | BOQ, report, and document numbering templates | Operation Manager / Accounts | Import templates in `docs/import_templates/` |
| 5 | Hosting provider, backup location, and server owner | Technical support / Admin | `docs/06_Operations_Runbook.md` |
| 6 | Source spreadsheets for users, projects, suppliers, inventory items, storage locations, BOQ, and opening stock | Operation Manager / Accounts | `backend/scripts/validate_import_sources.py` |
