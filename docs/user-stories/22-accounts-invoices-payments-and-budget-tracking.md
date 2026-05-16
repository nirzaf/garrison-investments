# Accounts, Invoices, Payments, and Budget Tracking

## Title
Accounts, Invoices, Payments, and Budget Tracking

## User Story
As an Accounts user,
I want to track invoices, payments, manpower costs, material costs, and project budgets,
so that project financial status and approvals are visible to authorized management.

## Description
Implement structured accounts records for invoices, payments, budgets, cost summaries, financial visibility restrictions, and Operation Manager approval.

## Acceptance Criteria
1. Given I am an Accounts user,
   When I create an invoice,
   Then structured fields, attachment, approval state, and payment status are saved.

2. Given an invoice is submitted,
   When the approval workflow runs,
   Then Accounts review/create and Operation Manager approval are enforced.

3. Given payments are recorded,
   When I view invoice detail,
   Then payment status and history are visible.

4. Given a user lacks finance permissions,
   When they access financial reports or values,
   Then sensitive values are hidden or access is denied.

## Business Rules
- Accounts tracks material usage, project budget, manpower, invoicing, and payment status.
- Invoice data is structured in database fields, not only uploaded as documents.
- Accounts users can approve invoices and Operation Manager must also approve.
- Financial values are visible to Admin, Accounts, Operation Manager, General Manager, and explicitly allowed Project Managers.
- OCR is future enhancement, not MVP.
- Material purchases do not need to connect to invoices in MVP.

## UI/UX Notes
- Accounts screens should be desktop-optimized with searchable tables and export actions.
- Finance visibility should be clear and consistent.
- Invoice attachment preview/download must be protected and audited.

## Technical Notes
- Use `invoices` and `payments` schema references.
- Add APIs for invoices, payments, budget summaries, and financial reports.
- Integrate approval engine for invoice/payment approval.
- Link invoices to project, supplier, attachment, approval, and payment status.
- Keep OCR placeholder isolated from MVP requirements.
- Follow `../../ARCHITECTURE.md` caching guidance: do not cache financial records aggressively.
- FinanceService owns invoice/payment workflow and visibility rules; routes stay thin and repositories own data access.
- Invoice attachments must use private MinIO presigned access and download audit logging.

## Priority
Medium

## Dependencies
- Project setup and BOQ.
- Supplier management.
- Generic approval engine.
- Document/file storage.
- Confirmation whether salary sheets are Phase 1 or later.
- Confirmation which Project Managers can view financial reports.

## Definition of Done
- Invoices and payments can be created, approved, viewed, and updated.
- Budget versus actual summary is available.
- Financial permissions are enforced.
- File access is audited.
- Tests cover finance visibility, invoice workflow, and payment status.
