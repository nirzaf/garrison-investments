# Supervisor Site Update Flow

## Title
Supervisor Site Update Flow

## User Story
As a Civil Supervisor,
I want to submit site updates with attendance, work location, overtime, progress, and photos,
so that the Civil Engineer can verify the site activity before the official daily report is submitted.

## Description
Implement the supervisor update flow as an input to the official daily report, not as the final daily report itself. This supports mobile-first field entry and later engineer verification.

## Acceptance Criteria
1. Given I am a Civil Supervisor assigned to a project,
   When I open the update form,
   Then I can enter work location, attendance, overtime, work progress, delays, and required notes.

2. Given I attach photos or allowed supporting files,
   When I save or submit the update,
   Then the files are associated with the project and update.

3. Given I submit the supervisor update,
   When the Civil Engineer opens the project reporting flow,
   Then my update is available for verification.

4. Given the update is submitted,
   When I try to edit fields that are locked by workflow,
   Then the system prevents unauthorized changes.

## Business Rules
- Civil Supervisors do not submit the official daily report.
- Supervisor updates include attendance, work location, overtime details, and progress.
- Multiple users cannot contribute to the same draft report.
- Previous-date submissions require admin approval unless allowed by business rules.
- Weekend and holiday updates are allowed when work is scheduled and must be marked by day type.

## UI/UX Notes
- The form must be mobile-first and tolerate weak H+ network conditions.
- Autosave should run every 30 seconds and on field blur/change when supported.
- Required fields must be clear before submit.
- Camera/photo upload should be easy from a phone.

## Technical Notes
- Model supervisor updates separately or as report inputs so the official report remains the engineer-approved record.
- Link updates to project, date, supervisor, attachments, and verification status.
- Add API validation for assigned project access.
- Prepare the data shape for engineer verification and report generation.
- Implement backend logic in a reporting service following `ARCHITECTURE.md`; routes must not contain workflow rules.
- Use React Hook Form + Zod for form state and validation, and TanStack Query mutations for save/submit.
- Autosave and weak-network retry behavior should prepare for the architecture offline/idempotency model even before Phase 3 full offline support.

## Priority
High

## Dependencies
- Authentication and role permissions.
- Project setup and team assignment.
- Photo and attachment upload foundation.
- Final company paper form fields.

## Definition of Done
- Supervisors can create and submit project updates.
- Updates are visible to engineers for the same project.
- Mobile entry is usable.
- Required validations are implemented.
- Tests cover create, submit, permission, and date rules.
