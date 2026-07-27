# Construction Internal Portal — Documentation Index

## Project Overview

Internal portal for a construction company to manage daily site reporting, project monitoring, inventory and stores, approvals, and cross-department communication. Designed as a scalable, modular, mobile-responsive web application.

Inventory & Stores is a Phase 2 capability for consumable materials and trackable tools/items. It supports multiple physical storage locations such as warehouses and project site stores, current-location visibility for asset-tagged tools, approval-controlled issue/transfer workflows, low-stock alerts by location, supplier context, and full movement history.

## Document Index

This folder has been aggressively consolidated down to the core living artifacts representing the implemented codebase.

| # | Document | Description |
|---|----------|-------------|
| 1 | [Architecture](ARCHITECTURE.md) | Codebase-derived architecture, layering rules, runtime boundaries, component tree, and API design. |
| 2 | [User Roles And Permissions](ROLES_AND_PERMISSIONS.md) | Current code-derived RBAC roles, permissions, frontend visibility, and backend enforcement. |
| 3 | [Operations and Deployment](OPERATIONS_AND_DEPLOYMENT.md) | Unified runbook for staging/prod deployment, CI/CD, backup/restore, alerts, UAT, and launch evidence. |
| 4 | [Logging and Remote CLI](LOGGING_AND_REMOTE_CLI.md) | Centralized event logging, remote log search/streaming API, and `log_cli.py` usage. |
| 5 | [Production Readiness Review](PRODUCTION_READINESS_REVIEW.md) | Final PRR verdict, security/DR review, and pre-release operations checklist. |
| 6 | [PostgreSQL Schema Reference](schema/README.md) | Codebase-derived database schema with one file per table and linked relations. |
| 7 | [Import Templates](import_templates/) | CSV templates for importing initial data (Users, BOQ, Projects, etc.). |

## Quick Start (Development)

```bash
# Clone repo
git clone <repo-url> && cd garrison-investments

# Start all services
docker-compose up -d

# Run migrations
docker-compose exec backend alembic upgrade head

# Seed sample data
docker-compose exec backend python scripts/seed.py

# Frontend dev server (localhost:3000)
cd frontend && npm install && npm run dev

# API docs (localhost:8000/docs)
open http://localhost:8000/docs
```
