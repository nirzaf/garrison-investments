# Daily Report Approval, Rejection, and History

## Title
Daily Report Approval, Rejection, and History

## User Story
As a Project Manager,
I want to approve or reject daily reports with visible history,
so that the official project record is controlled and traceable.

## Description
Implement the first-release daily report approval workflow from supervisor update to engineer report to Project Manager approval, including rejection comments, approval history, immutable approved reports, and late/missing report rules.

## Acceptance Criteria
1. Given an engineer submits a daily report,
   When I open my approval inbox,
   Then I see the pending report with relevant project, date, and submitter details.

2. Given I approve a report,
   When approval succeeds,
   Then the report becomes official and cannot be edited.

3. Given I reject a report,
   When I submit a rejection reason,
   Then the report returns to draft and the reason remains visible in history.

4. Given a report is late or missing after the cutoff,
   When the alert rule runs,
   Then the submitter is notified first and the Project Manager is notified if still missing.

## Business Rules
- Daily report approval must confirm that the target was covered.
- Rejection reason is mandatory.
- Approved items cannot be reopened or revised.
- Approval history must be visible inside the report.
- Late cutoff defaults to 10:00 AM the next day.
- Weekend/holiday lateness checks are skipped unless work was scheduled.
- Admin overrides must be fully audited.

## UI/UX Notes
- Approval screens must show the report content, attachments, and history before action buttons.
- Approve and reject actions must be clearly separated.
- Rejection comments should remain visible to relevant users.
- Status badges should clearly identify draft, submitted, approved, and rejected states.

## Technical Notes
- Implement report-specific approval first, then align with the generic approval engine later.
- Add immutable state checks to report update APIs.
- Add late/missing report detection and notification triggers.
- Store approval actor, timestamp, decision, comments, and prior state.
- Follow `ARCHITECTURE.md` immutability-after-approval rule for daily reports.
- Put approval transition rules in services; repositories should only persist and query approval/report data.
- Late report checks should run through Celery Beat maintenance tasks, not blocking request handlers.

## Priority
High

## Dependencies
- Engineer daily report flow.
- Basic notifications.
- Project role assignment.
- Confirmation that 10:00 AM cutoff matches site operations.

## Definition of Done
- Reports can be approved and rejected by authorized managers.
- Approved reports are immutable.
- Rejection history remains visible.
- Late/missing report alerts work.
- Tests cover approval, rejection, immutability, and permission failures.
