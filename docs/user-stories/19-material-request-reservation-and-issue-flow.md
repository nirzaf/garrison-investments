# Material Request, Reservation, and Issue Flow

## Title
Material Request, Reservation, and Issue Flow

## User Story
As a site team member,
I want to request materials and have them approved, reserved, and issued,
so that project work receives materials through a controlled stock workflow.

## Description
Implement material request lifecycle from requester through Engineer, Project Manager, and Operation Manager where required, including reservation and issue behavior.

## Acceptance Criteria
1. Given I am an authorized requester,
   When I submit a material request,
   Then it enters the correct approval chain.

2. Given a request is approved,
   When stock is available,
   Then the requested quantity is reserved before issue.

3. Given a Store Keeper issues material,
   When the issue is recorded,
   Then stock decreases and the movement is linked to project and request.

4. Given requested stock is unavailable,
   When the request is reviewed,
   Then the system prevents negative stock and shows available quantity.

## Business Rules
- Supervisors, Engineers, and Project Managers can create material requests.
- Everyone can request material, but final approval is required.
- Material requests above USD 1,000 require Operation Manager approval.
- Material request lifecycle is requested, approved, reserved, issued, partially issued, or cancelled.
- Material requests should reserve stock before issue.
- Outgoing materials should be linked to a daily report where applicable.
- Stock cannot go negative.

## UI/UX Notes
- Request forms should show item availability by location.
- Approvers should see cost information only if their role allows it.
- Store Keeper screens should show approved requests ready for reservation or issue.
- Partial issue status must be clear.

## Technical Notes
- Use the generic approval engine for request approvals.
- Add APIs for material requests, reservation, issue, cancel, and status history.
- Use transactions to keep approval, reservation, and stock movement consistent.
- Link material issue to project, location, request, handler, and optional daily report.
- Follow `../ARCHITECTURE.md` service-layer rule: MaterialRequestService coordinates approval, reservation, movement creation, and notification.
- Stock writes must be transactionally safe in PostgreSQL and must never be implemented as frontend-only state changes.
- Use typed application exceptions for insufficient stock or invalid status transitions and map them to consistent 409 responses.

## Priority
Medium

## Dependencies
- Generic approval engine.
- Inventory catalog, locations, and stock.
- Supplier and pricing rules.
- Confirmation of Project Manager price visibility.

## Definition of Done
- Material requests can be created, approved, reserved, issued, partially issued, and cancelled.
- Negative stock is blocked.
- Approval routing works.
- Stock movements are created.
- Tests cover lifecycle, permissions, and transaction failure cases.
