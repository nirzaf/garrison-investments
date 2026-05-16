# Engineer Daily Report Flow

## Title
Engineer Daily Report Flow

## User Story
As a Civil Engineer,
I want to verify supervisor updates and submit the official daily report,
so that project progress and site records are accurate and ready for Project Manager approval.

## Description
Implement the Civil Engineer reporting flow with required daily report fields, supervisor input verification, safety data, WIR/inspection status, photos, attachments, report number generation, and draft/submission states.

## Acceptance Criteria
1. Given supervisor updates exist for my project,
   When I create the daily report,
   Then I can review and verify those updates before submission.

2. Given I fill all required report fields,
   When I save as draft,
   Then the report remains editable by me according to workflow rules.

3. Given I submit the report,
   When submission succeeds,
   Then a unique report number is generated and the report moves to Project Manager approval.

4. Given required fields are missing,
   When I try to submit,
   Then field-level validation prevents submission.

## Business Rules
- The official report is the final Civil Engineer report approved by the Project Manager.
- Required fields include project, date, work area/location, manpower, overtime, work completed, progress, safety incidents, WIR/inspection status, delays, next-day plan, photos, and attachments.
- Report number format is `PROJECTCODE-DR-YYYYMMDD-###`.
- Multiple reports per project are allowed.
- Future-dated reports are allowed.
- Approved reports cannot be edited.
- Rejected reports return to draft with rejection comments visible.

## UI/UX Notes
- The report form should be structured into clear sections.
- Dynamic rows are needed for manpower, equipment, and material consumption.
- Progress entry should support manual values and future calculated values.
- Reports should be printable and readable on desktop and tablet.

## Technical Notes
- Use `daily_reports`, `report_manpower`, `report_equipment`, `report_material_consumption`, and `photos` schema references.
- Implement report CRUD, draft save, submit, detail, and list APIs.
- Add validation for required fields, project access, and workflow state.
- Prepare material consumption linkage for future stock reduction.
- Follow the `../ARCHITECTURE.md` ReportService pattern: service generates report numbers, validates project/user rules, creates child rows, links photos, and commits transactions.
- Report repositories must use async SQLAlchemy, `selectinload` for child rows, and default soft-delete filtering.
- Response models must be Pydantic V2 schemas with `from_attributes=True`.

## Priority
High

## Dependencies
- Supervisor site update flow.
- Project setup and team assignment.
- Photo and attachment management.
- Final company daily report fields and templates.

## Definition of Done
- Engineers can create, save, edit, and submit official reports.
- Report numbers are generated correctly.
- Required validations work.
- Report details show all submitted sections.
- API and UI tests cover draft, submit, and validation paths.
