# Basic Notifications and Alerts

## Title
Basic Notifications and Alerts

## User Story
As a portal user,
I want in-app and email notifications for required actions and status changes,
so that I do not miss approvals, reports, documents, or alerts.

## Description
Implement notification records, unread counts, notification history, email delivery, header bell, and triggers for first-release operational events.

## Acceptance Criteria
1. Given a report is submitted for approval,
   When the notification trigger runs,
   Then the assigned approver receives an in-app and email notification.

2. Given a report is approved or rejected,
   When the decision is recorded,
   Then the requester receives a notification.

3. Given I have unread notifications,
   When I view the header,
   Then I see the unread count.

4. Given I open notification history,
   When records exist within retention,
   Then I can view them and mark them read.

## Business Rules
- Email and in-app notifications are required.
- Events include report submitted, report approved, report rejected, low stock, late report, new document, and pending approval.
- User-facing notification retention is 90 days.
- Audit logs are retained separately.
- Pending approvals get a reminder after 24 hours and escalation after 48 hours.
- Users can mute notifications where allowed.

## UI/UX Notes
- Add notification bell and dropdown in the header.
- Add a full notification history page.
- Notification messages should clearly identify the project, item, and required action.
- Muting controls should not hide mandatory compliance alerts unless policy allows it.

## Technical Notes
- Use `notifications` schema reference.
- Add APIs for list, unread count, mark read, and mark all read.
- Dispatch emails with Celery.
- Implement recipient matrix for missing report, approval, low stock, and new active document events.
- Add scheduled jobs for reminders and retention cleanup.
- Follow `ARCHITECTURE.md` notification flow: service layer creates in-app notifications, Celery sends email, client polls unread count every 60 seconds.
- Keep notification retention cleanup in Celery Beat maintenance tasks.
- Notification APIs must use `/api/v1` REST conventions and Pydantic response envelopes where lists are returned.

## Priority
High

## Dependencies
- Authentication and users.
- Report approval flow.
- Document approval flow.
- Email service configuration.
- Confirmation whether General Manager receives selected notifications.

## Definition of Done
- In-app and email notifications are created for MVP events.
- Header unread count works.
- Notification history and read actions work.
- Reminder and escalation jobs are implemented.
- Tests cover recipient routing and retention behavior.
