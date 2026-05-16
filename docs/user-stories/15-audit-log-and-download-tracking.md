# Audit Log and Download Tracking

## Title
Audit Log and Download Tracking

## User Story
As an Admin,
I want important actions and downloads audited,
so that the company can trace access, approvals, and changes for compliance.

## Description
Implement audit logging for authentication, create/update/delete, approval, view/download, admin overrides, and sensitive file access.

## Acceptance Criteria
1. Given a user logs in, fails login, or logs out,
   When the event occurs,
   Then an audit log entry records the actor, timestamp, and event type.

2. Given a protected file is viewed or downloaded,
   When the action succeeds,
   Then an audit entry records the user, file, project, and action.

3. Given an approval override or delegation occurs,
   When the action is saved,
   Then the audit log records original approver, acting user, reason, and timestamp.

4. Given I am an Admin,
   When I open audit logs,
   Then I can search and filter logs without exposing them to non-admin users.

## Business Rules
- Audit logs are visible only to Admin.
- Audit logs record view/download actions and create/update/delete/login/approve actions.
- Admin overrides and delegated approvals must be fully audited.
- Audit logs should be retained for 7 years unless legal requirements differ.
- Deleted records remain recoverable for 30 days.

## UI/UX Notes
- Admin audit table should support search, filters, sorting, and detail view.
- Sensitive values should be masked where appropriate.
- Audit entries should use readable event labels.

## Technical Notes
- Use `activity_log` schema reference.
- Add middleware or service-level audit hooks.
- Keep audit writes reliable but avoid blocking user workflows unnecessarily.
- Include request metadata where allowed, such as IP, user agent, and entity identifiers.
- Follow `../../ARCHITECTURE.md` audit design: use a custom APIRoute wrapper where response status is needed, because dependencies cannot capture final response outcomes.
- Record create, update, soft delete, login, logout, approve, reject, download, and admin override using the architecture field model.
- Keep audit log access admin-only and never cache audit-log reads.

## Priority
High

## Dependencies
- Authentication.
- User and role permissions.
- File download endpoints.
- Approval workflows.
- Confirmation of legal retention period if longer than 7 years.

## Definition of Done
- Required actions are audited.
- Admin can search and filter audit logs.
- Non-admin users cannot access audit logs.
- Download tracking works for documents, photos, reports, and invoices.
- Tests cover audit creation and access restrictions.
