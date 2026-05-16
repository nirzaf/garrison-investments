# Document Upload, Versioning, and Approval

## Title
Document Upload, Versioning, and Approval

## User Story
As a project team member,
I want to upload, version, approve, and find project documents,
so that users work from the correct active documents and older versions remain traceable.

## Description
Implement first-release document management for MAR, MIR, WIR, delivery notes, drawings, BOQs, contracts, WIRs, and invoices where permitted. Documents require metadata, version history, approval before active status, superseded warnings, browser PDF preview, search, and download.

## Acceptance Criteria
1. Given I upload a document with metadata,
   When the upload succeeds,
   Then it is stored as pending approval and is linked to the relevant project or record.

2. Given I upload a new version,
   When it becomes active,
   Then the prior active version is marked superseded and remains downloadable for authorized users.

3. Given I view a superseded document,
   When the system detects that status,
   Then I see a strong warning before viewing or downloading.

4. Given I search by title, metadata, or file content,
   When matching documents exist,
   Then I see authorized results only.

## Business Rules
- Documents and version control are required in the first release.
- Document types include MAR, MIR, WIR, and delivery notes.
- Documents require approval before becoming active.
- Maximum document file size is 60 MB.
- Old document versions remain downloadable.
- Financial documents are visible to Admin, Accounts, Project Manager, and Operation Manager.
- Document expiry dates and renewal reminders are required.
- Superseded access differs by role and needs stakeholder confirmation.

## UI/UX Notes
- Document library should support filters, list/grid display, search, upload, and version history.
- PDF preview is required in the browser.
- Superseded warnings must be visually prominent.
- Metadata forms should match company standards where available.

## Technical Notes
- Use `documents` and `document_versions` schema references.
- Add upload/download APIs, version APIs, search API, and approval hooks.
- Store documents in MinIO through authorized access only.
- Use PostgreSQL full-text search for metadata and extracted text where feasible.
- Audit all view and download actions.
- Follow `../ARCHITECTURE.md` file-access flow: FastAPI checks RBAC/project access, returns a short-lived MinIO presigned URL, and records the download audit event.
- Use `documents` plus `document_versions` with immutable active versions and superseded records instead of overwriting files.
- Implement list/search endpoints with the architecture pagination and filtering conventions.

## Priority
High

## Dependencies
- Object storage setup.
- Project setup.
- Approval workflow.
- Company document numbering and revision standards.
- Confirmation of roles allowed to download superseded versions.

## Definition of Done
- Users can upload, version, approve, view, preview, search, and download documents.
- Superseded warnings work.
- Role visibility is enforced.
- Document actions are audited.
- Tests cover upload, versioning, approval, access control, and search.
