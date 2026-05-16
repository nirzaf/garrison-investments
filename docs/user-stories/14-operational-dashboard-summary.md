# Operational Dashboard Summary

## Title
Operational Dashboard Summary

## User Story
As a manager,
I want a focused operational dashboard,
so that I can quickly identify pending approvals, late reports, active projects, and recent activity.

## Description
Build a first-release dashboard that avoids advanced analytics but provides operational summaries needed for launch.

## Acceptance Criteria
1. Given I am a management user,
   When I open the dashboard,
   Then I see company-wide operational summaries according to my permissions.

2. Given I am a field or scoped user,
   When I open the dashboard,
   Then I see only records relevant to my project and role.

3. Given pending approvals or late reports exist,
   When the dashboard loads,
   Then the counts and recent records are visible.

4. Given filters are available,
   When I filter by project or date range,
   Then dashboard summaries update accordingly.

## Business Rules
- Initial delivery should prioritize task update and reporting flow over a dashboard-heavy portal.
- Phase 1 KPIs include pending approvals, late or missing reports, active projects, recent submissions, low stock if materials are included, and upcoming deadlines.
- Company-wide dashboard is restricted to management roles.
- Other roles see scoped dashboards.
- Dashboard numbers should update every few minutes.

## UI/UX Notes
- Use stat cards, recent activity, pending approvals, and simple charts only.
- Avoid dense advanced analytics in Phase 1.
- Provide filters for project and date range where useful.
- Loading and empty states must be clear.

## Technical Notes
- Add `/dashboard/summary` endpoint with role-scoped statistics.
- Use TanStack Query or equivalent client cache with periodic refresh.
- Use existing report, approval, project, notification, and inventory data as available.
- Low-stock cards should remain hidden or empty until inventory is implemented.
- Follow `ARCHITECTURE.md` caching guidance: dashboard summaries may be cached in Redis, but approval inboxes, audit logs, financial records, and inventory stock quantities should not be cached aggressively.
- Dashboard APIs should be implemented in DashboardService and repositories, not direct queries in routes.
- Frontend dashboard data must use TanStack Query server-state caching and invalidation.

## Priority
Medium

## Dependencies
- Authentication and permissions.
- Projects.
- Daily reports.
- Approvals and notifications.
- Decision on whether low-stock dashboard cards are Phase 1 or Phase 2.

## Definition of Done
- Dashboard shows role-scoped operational summaries.
- Filters work.
- Counts match backend data.
- Management visibility is restricted.
- Tests cover scoped data and key dashboard metrics.
