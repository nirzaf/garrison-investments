# Project Setup, BOQ, and Team Assignment

## Title
Project Setup, BOQ, and Team Assignment

## User Story
As an Operation Manager,
I want to create projects with BOQ, milestones, and assigned team members,
so that site activity, reports, documents, and costs can be tracked by project.

## Description
Implement project creation, generated project codes, project members, BOQ line items, milestones, activities, timeline data, and project read-only behavior after completion.

## Acceptance Criteria
1. Given I am allowed to create projects,
   When I submit a valid project form,
   Then the system creates a project with a unique generated project code.

2. Given a project exists,
   When I assign employees to it,
   Then those users can access project-specific records according to role permissions.

3. Given BOQ items are added or imported,
   When I view the project,
   Then BOQ quantities, rates, amounts, phases, disciplines, and milestones are available.

4. Given a project is completed,
   When users access it,
   Then it remains searchable and read-only instead of hidden.

## Business Rules
- Project codes are auto-generated and unique.
- Project creation requires scope of work, deadline, and BOQ.
- Users can be assigned to multiple projects in the initial stage.
- BOQ supports manual entry and spreadsheet import.
- BOQ fields include item code, description, unit, quantity, rate, amount, discipline, phase, and milestone.
- Completed or old projects become read-only and searchable.

## UI/UX Notes
- Project management screens should support search, filters, sorting, export, and saved filters where applicable.
- Project forms should provide selectable phases, milestones, activities, and BOQ line items.
- Timeline views should be clear on desktop and readable on tablets.

## Technical Notes
- Use `projects`, `project_members`, `project_milestones`, and `boq_items` schema references.
- Add endpoints for project CRUD, members, timeline, milestones, and BOQ.
- Design import validation before saving BOQ rows.
- Keep project location as text plus optional map image for MVP.
- Follow `../ARCHITECTURE.md` layering: project routes only validate and delegate, ProjectService owns project code generation and business rules, repositories own async SQLAlchemy queries.
- List endpoints must use the architecture pagination envelope and common filters.
- Use partial unique indexes for active-only uniqueness such as project code and BOQ identifiers where needed.

## Priority
High

## Dependencies
- User roles and permissions.
- Company BOQ spreadsheet format.
- Discipline weights for project progress calculation.
- Initial active project data for seed/UAT.

## Definition of Done
- Projects can be created, updated, listed, searched, and viewed.
- Project members can be assigned.
- BOQ and milestones can be entered or imported.
- Completed projects are read-only.
- API and UI tests cover project creation and member access.
