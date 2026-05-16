# Supplier Management and Compliance

## Title
Supplier Management and Compliance

## User Story
As a Store Keeper or Accounts user,
I want to manage suppliers and compliance details,
so that materials, invoices, and purchasing context are linked to verified supplier records.

## Description
Implement supplier records with categories, ratings, payment terms, TDS fields, compliance status, and soft deactivation.

## Acceptance Criteria
1. Given I have permission to manage suppliers,
   When I create a supplier,
   Then required contact, tax, payment, category, and compliance fields are saved.

2. Given a supplier has TDS documentation,
   When I upload or update it,
   Then certificate, expiry, and compliance status are visible to authorized users.

3. Given a supplier is no longer active,
   When I deactivate it,
   Then historical materials and invoices keep their supplier reference.

4. Given I create material records,
   When supplier selection is required,
   Then only active supplier records are selectable by default.

## Business Rules
- Supplier records are required before creating materials.
- Supplier records include TDS.
- Supplier ratings, supplier categories, and payment terms are required.
- Supplier TDS fields include certificate or file, tax registration number, expiry date, uploaded document, and compliance status.
- Supplier records use soft delete or deactivation.

## UI/UX Notes
- Supplier management should support search, filters, and compliance status badges.
- Expiring TDS certificates should be visually highlighted.
- Financial or tax fields should be visible only to authorized roles where needed.

## Technical Notes
- Use `suppliers` schema reference.
- Add supplier CRUD APIs with soft delete.
- Store compliance files in object storage with audit logging.
- Add expiry reminder hooks for notifications.
- Link suppliers to inventory items and invoices.
- Follow `../ARCHITECTURE.md` soft-delete pattern with `deleted_at` and active-only repository filters.
- Supplier document downloads must use the same MinIO presigned URL and audit flow as other private files.
- Supplier list APIs must use the standard pagination, filtering, and error response conventions.

## Priority
Medium

## Dependencies
- Auth and role permissions.
- Object storage for compliance documents.
- Inventory catalog.
- Accounts module for invoice linkage.

## Definition of Done
- Suppliers can be created, updated, searched, and deactivated.
- TDS and compliance data are stored.
- Historical references remain intact.
- Supplier access is permission-controlled.
- Tests cover CRUD, deactivation, and required fields.
