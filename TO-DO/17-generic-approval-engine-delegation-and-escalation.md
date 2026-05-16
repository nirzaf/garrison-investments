# Generic Approval Engine, Delegation, and Escalation

## Title
Generic Approval Engine, Delegation, and Escalation

## User Story
As an Operation Manager,
I want a reusable approval engine for reports, documents, materials, invoices, payments, and project changes,
so that all approval workflows are consistent, traceable, and escalated when delayed.

## Description
Generalize approval behavior beyond daily reports and documents to support multi-level approval chains, delegation, escalation, admin overrides, comments, inbox/outbox views, and entity-specific workflow rules.

## Acceptance Criteria
1. Given a workflow-enabled entity is submitted,
   When approval rules are evaluated,
   Then the correct approver chain is created automatically.

2. Given an approver is unavailable or inactive,
   When delegation or reassignment is configured,
   Then the delegated approver can act and the audit log records the change.

3. Given an approval is pending for 24 hours,
   When the reminder job runs,
   Then the approver receives a reminder.

4. Given an approval is still pending after 48 hours,
   When the escalation job runs,
   Then the next configured escalation recipient is notified.

## Business Rules
- Daily reports, material requests, documents, invoices, payments, and project changes require approval.
- Approvers are determined automatically by project and role.
- Rejection reason is mandatory.
- Approved items cannot be reopened or revised.
- Approval comments are visible only to managers.
- Admin overrides are allowed but must be fully audited.
- Material requests above USD 1,000 require Operation Manager approval.

## UI/UX Notes
- Approval inbox should include pending, rejected, and approved tabs.
- Approval detail should preview the request content before action.
- Delegation and override actions must require a reason.
- Managers should see comments and history clearly.

## Technical Notes
- Use `approvals` schema reference.
- Add generic entity type and entity ID fields for workflow targets.
- Implement approval services that entity modules can call.
- Add inbox, outbox, detail, approve, reject, delegate, and override APIs.
- Ensure entity modules enforce final approved immutability.
- Follow `ARCHITECTURE.md` polymorphic association pattern with `request_type` and `request_id`.
- ApprovalService must own workflow rules, transaction boundaries, notifications, and cross-domain coordination.
- Repository queries for inbox/outbox should use composite indexes such as approver plus status and avoid Redis caching for approval inboxes.

## Priority
High

## Dependencies
- Auth, RBAC, users, projects, notifications, and audit logs.
- Confirmation of high-risk or non-material items requiring Operation Manager approval.
- Timely activity scoring rules.

## Definition of Done
- Generic approvals support configured entity types.
- Delegation, escalation, rejection, and override work.
- Audit and notifications are integrated.
- API and UI tests cover approval chains and permissions.
- Existing report and document workflows can use or align with the engine.
