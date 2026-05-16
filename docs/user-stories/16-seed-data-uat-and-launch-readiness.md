# Seed Data, UAT, and Launch Readiness

## Title
Seed Data, UAT, and Launch Readiness

## User Story
As the MD and Operation Manager,
I want realistic launch test data and UAT scenarios,
so that I can approve the first release with confidence.

## Description
Prepare sample users, projects, documents, report data, approval scenarios, notifications, and launch acceptance workflows for mobile and desktop validation.

## Acceptance Criteria
1. Given a fresh staging environment,
   When the seed command runs,
   Then sample users, roles, projects, and launch data are available.

2. Given UAT starts,
   When testers follow the checklist,
   Then login, user creation, project creation, supervisor update, engineer report, approval, rejection, photo upload, document version upload, notification, and export are covered.

3. Given a launch blocker occurs,
   When it is reported,
   Then it is classified and resolved before release approval.

4. Given Phase 1 is complete,
   When mobile and desktop UAT pass with real seed data,
   Then the release is ready for stakeholder sign-off.

## Business Rules
- UAT is performed by the MD and Operation Manager.
- Phase 1 is done when all launch scenarios pass on mobile and desktop with real seed data.
- Launch blockers include login failure, data loss, wrong approval routing, broken upload, wrong permissions, missing audit trail, and failed report submission.
- Module sign-off is required before moving to the next phase.

## UI/UX Notes
- Seed data should use recognizable realistic names and project states.
- UAT flows should be written in plain operational language.
- Test accounts should clearly identify their roles.

## Technical Notes
- Build repeatable seed scripts for local and staging.
- Include role-specific users for every MVP role.
- Add smoke tests for login to report submission to approval.
- Document browser/device coverage for Chrome, Edge, iOS Safari, and Android Chrome.
- Include low-speed network testing guidance.
- Follow `../ARCHITECTURE.md` migration rule: seed data belongs in `scripts/seed.py`, not Alembic migrations.
- UAT smoke tests should cover API response envelopes, RBAC enforcement, and frontend route error boundaries.
- Keep seeded credentials development/staging-only and outside production secrets.

## Priority
High

## Dependencies
- MVP modules implemented.
- Final UAT checklist confirmation.
- Sample users, projects, and company data.
- Stakeholder availability for sign-off.

## Definition of Done
- Seed script works in staging.
- UAT checklist is documented.
- Smoke tests pass.
- Launch blockers are tracked and resolved.
- MD and Operation Manager can complete sign-off scenarios.
