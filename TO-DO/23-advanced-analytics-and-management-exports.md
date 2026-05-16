# Advanced Analytics and Management Exports

## Title
Advanced Analytics and Management Exports

## User Story
As a General Manager,
I want advanced charts and exportable management reports,
so that I can analyze project progress, costs, materials, and operational performance.

## Description
Implement Phase 3 analytics and export capabilities beyond the Phase 1 operational dashboard, including charts, Excel exports, PDF summaries, material consumption trends, and project-wise financial reports.

## Acceptance Criteria
1. Given I have management permissions,
   When I open analytics,
   Then I can view project progress, report trends, material usage, and financial summaries.

2. Given I apply filters,
   When I export a report,
   Then the exported Excel or PDF reflects the selected project, date range, location, and department.

3. Given material usage data exists,
   When I view trends,
   Then the system shows consumption patterns and forecast-ready summaries.

4. Given a user lacks management permissions,
   When they access advanced analytics,
   Then access is denied or scoped appropriately.

## Business Rules
- Management report format should include Excel.
- Export templates include daily report PDF, project progress Excel, and material usage Excel.
- Dashboard filters include project, date range, location, and department.
- Financial reports include bookkeeping, project-wise profit and loss, and salary sheets when included.
- Advanced dashboard KPIs are decided later and should not block Phase 1.

## UI/UX Notes
- Analytics pages should use clear charts and tables, not overloaded dashboards.
- Export actions should indicate file type and active filters.
- Management views should be desktop-first.

## Technical Notes
- Use Recharts or equivalent for charts.
- Use openpyxl or equivalent for Excel exports.
- Use server-side PDF generation for project summaries.
- Ensure export APIs enforce the same permissions as screen views.
- Keep forecasting simple until validated by real data.
- Follow `ARCHITECTURE.md` bulk operation rule: large exports return `202 Accepted` with a task ID and client polling.
- Export generation should run through Celery report queues, with generated files stored in MinIO.
- Frontend analytics must use TanStack Query for server state and Recharts for charts.

## Priority
Low

## Dependencies
- Daily reports, projects, inventory, accounts, and approvals.
- Final management KPI definitions.
- Export template requirements.
- Salary sheet phase confirmation.

## Definition of Done
- Advanced analytics pages are available to authorized users.
- Excel and PDF exports work with filters.
- Financial and material data obey permissions.
- Tests cover export correctness and access control.
- Export templates are approved by stakeholders.
