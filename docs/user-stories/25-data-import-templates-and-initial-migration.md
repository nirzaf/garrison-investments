# Data Import Templates and Initial Migration

## Title
Data Import Templates and Initial Migration

## User Story
As an Admin,
I want import templates and controlled initial data migration,
so that active users, projects, suppliers, materials, documents, BOQ, and opening stock can be loaded accurately.

## Description
Create import templates, validation rules, preview workflows, and migration scripts for the initial launch data set. Historical data migration remains optional unless legally required.

## Acceptance Criteria
1. Given source spreadsheets are available,
   When I upload an import file,
   Then the system validates required columns and shows errors before saving.

2. Given valid import data is confirmed,
   When I run the import,
   Then records are created or linked without duplicates.

3. Given material opening stock is imported,
   When import succeeds,
   Then stock balances and movement history reflect the opening balance.

4. Given historical reports or documents are not required,
   When MVP launches,
   Then only active projects and opening balances are migrated.

## Business Rules
- Existing data import can happen later, but active launch data is required.
- Import templates are required for users, projects, suppliers, materials, documents, BOQ, and opening stock.
- Material opening stock should be imported.
- Source spreadsheets must be collected before final schema and import-template lock.
- Historical reports/documents are not migrated in MVP unless legally required.
- Soft delete and historical continuity rules must be respected.

## UI/UX Notes
- Import screens should show template download, upload, validation preview, error rows, and final confirmation.
- Validation errors should identify row number, column, and expected value.
- Admins should be able to rerun failed imports after correction.

## Technical Notes
- Build import templates with stable column names.
- Implement dry-run validation before writes.
- Use transactions and idempotency keys or natural keys to reduce duplicate risk.
- Record import batches and imported row status.
- Create opening stock movements rather than directly editing stock balances.
- Follow `ARCHITECTURE.md` bulk operation model: imports are multipart CSV/XLSX uploads processed asynchronously through Celery when large.
- Use service-layer validation and repository writes; do not put import business rules in route handlers.
- Import APIs must return consistent error envelopes with row, field, and message details.

## Priority
Medium

## Dependencies
- Final source spreadsheets.
- Final schema for users, projects, suppliers, materials, documents, BOQ, and stock.
- Data quality review.
- Legal decision on historical reports/documents migration.

## Definition of Done
- Import templates are available.
- Import validation catches missing and invalid data.
- Valid imports create expected records.
- Opening stock imports create movement history.
- Tests cover validation, duplicate handling, and rollback behavior.
