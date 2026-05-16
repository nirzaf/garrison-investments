# UAT And Launch Readiness

This checklist validates the Phase 1 release with seeded staging data. The seed script is
`backend/scripts/seed.py` and must only be used in local or staging environments.

## Seed Data

Run after migrations:

```bash
docker compose exec backend python scripts/seed.py
```

Seeded accounts use the temporary password `ChangeMe123!` and must be forced to change
passwords before production-like testing.

| Role | Email | Primary Scenario |
| --- | --- | --- |
| Admin | `admin@garrisons.qa` | Users, audit logs, system setup |
| General Manager | `gm@garrisons.qa` | Company dashboard review |
| Operation Manager | `operations@garrisons.qa` | Project and approval oversight |
| Project Manager | `pm@garrisons.qa` | Report approval and document approval |
| Civil Engineer | `engineer@garrisons.qa` | Daily reports and photo uploads |
| Civil Supervisor | `supervisor@garrisons.qa` | Site updates |
| Store Keeper | `store@garrisons.qa` | Phase 2 inventory checks |
| Accounts | `accounts@garrisons.qa` | Phase 2 invoice and budget checks |

Seeded projects:

- `GIP-001` Lusail Villa Fit-Out, active, with team members, BOQ, milestones, and one submitted daily report.
- `GIP-002` West Bay Office Renovation, planning, with team members, BOQ, and milestones.

## UAT Scenarios

1. Admin logs in, creates a user, updates the role, deactivates the test user, and verifies audit entries.
2. Operation Manager opens dashboard, confirms active projects, submitted reports, pending documents, and unread notifications.
3. Project Manager reviews the seeded submitted daily report, rejects it with a comment, and verifies engineer notification.
4. Civil Engineer updates the rejected report, submits it again, uploads at least one photo, and confirms validation errors are readable.
5. Project Manager approves the report and downloads the PDF export.
6. Civil Supervisor submits a site update for the active project.
7. Admin uploads a document, approves the active version, uploads a replacement version, and confirms old-version download warning.
8. Admin opens audit logs and filters for downloads, approvals, login success, and login failure.
9. Mobile validation repeats scenarios 2 through 6 on iOS Safari and Android Chrome.
10. Desktop validation repeats scenarios 1 through 8 on Chrome and Microsoft Edge.

## Blocker Classification

| Severity | Examples | Release Action |
| --- | --- | --- |
| Blocker | Login failure, data loss, broken report submit, wrong approval routing, broken upload, missing audit trail | Must be fixed before sign-off |
| High | Permission leakage, incorrect dashboard count, failed PDF export, unusable mobile workflow | Must be fixed or formally accepted by MD and Operation Manager |
| Medium | Copy issue, minor layout defect, non-critical notification delay | Can ship with tracked follow-up if accepted |
| Low | Cosmetic polish, optional filter, non-critical export improvement | Backlog candidate |

## Device And Network Coverage

- Desktop: Chrome latest and Microsoft Edge latest.
- Mobile: iOS Safari and Android Chrome.
- Network: test normal office network and throttled low-speed mode for report draft save, upload, and submit flows.

## Sign-Off

Phase 1 is ready when:

- All blocker and high-severity UAT issues are closed or formally accepted.
- MD and Operation Manager complete mobile and desktop scenarios.
- Seed data can be recreated in staging from a fresh database.
- Backend smoke tests, frontend build, and audit/download checks pass.
- Backup and restore procedure has a recorded dry run for the target environment.
