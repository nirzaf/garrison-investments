# User Roles, Permissions, and Admin Management

## Title
User Roles, Permissions, and Admin Management

## User Story
As an Admin,
I want to manage users, roles, and account status,
so that employees have the correct access without losing historical records.

## Description
Create role-based access control and admin user management for the MVP roles: Admin, General Manager, Operation Manager, Project Manager, Civil Engineer, Civil Supervisor, Store Keeper, and Accounts.

## Acceptance Criteria
1. Given I am an Admin,
   When I create a user,
   Then I can assign one role and required employee details.

2. Given a user leaves or changes position,
   When I deactivate or reassign them,
   Then historical reports, approvals, and audit logs keep the original user reference.

3. Given I access a protected module,
   When my role does not allow that action,
   Then the action is blocked in both UI and API.

4. Given I am an Admin,
   When I view users,
   Then I can filter active, inactive, and role-specific users.

## Business Rules
- Each user has exactly one role in MVP.
- Employee codes and phone numbers are mandatory.
- Users must be deactivated, renamed, or reassigned instead of permanently deleted.
- Admins cannot edit or delete approved reports.
- MVP uses fixed role permissions but the database should allow customizable permissions later.
- Store Keepers access only material and inventory screens.
- Accounts can see project budgets, invoices, reports, and materials.

## UI/UX Notes
- Admin screens should be desktop-optimized with search, filters, sorting, and clear status badges.
- Role and permission labels should be understandable to non-technical admins.
- Destructive actions must require confirmation.

## Technical Notes
- Implement RBAC middleware and route dependencies.
- Add role-filtered navigation and action visibility.
- Use soft delete or deactivation for users.
- Preserve foreign key references to inactive users.
- Add tests for API permission enforcement, not only UI hiding.
- Follow `ARCHITECTURE.md` RBAC matrix as the starting permission model.
- Keep route handlers thin; put account lifecycle and permission business rules in a user/admin service.
- Repository queries must exclude `deleted_at` records by default and preserve inactive historical references.

## Priority
High

## Dependencies
- Authentication and session security.
- Final role permission matrix.
- Confirmation of General Manager approval authority versus read-only visibility.

## Definition of Done
- Admin can create, update, deactivate, and view users.
- Role permissions are enforced in API and UI.
- Historical references remain intact.
- Permission tests cover major modules and denied actions.
- User management is included in UAT seed data.
