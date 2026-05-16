# Photo and Attachment Upload Management

## Title
Photo and Attachment Upload Management

## User Story
As a field user,
I want to upload site photos and supporting attachments,
so that project reports include verifiable visual and document evidence.

## Description
Implement upload, compression, thumbnail generation, metadata, download, deletion rules, watermarks, and attachment support for reports and project records.

## Acceptance Criteria
1. Given I am completing a site update or report,
   When I upload allowed files,
   Then the files are stored with metadata and linked to the correct project record.

2. Given I upload a photo,
   When processing completes,
   Then original, compressed display, and thumbnail versions are available.

3. Given a report has been submitted,
   When I try to delete its photos,
   Then deletion is blocked unless I have Admin recovery permissions.

4. Given I download or view a protected file,
   When the action succeeds,
   Then the action is logged for audit.

## Business Rules
- Maximum 5 photos per report.
- Photo file size limit is 10 MB each.
- Allowed photo formats include JPG, PNG, and HEIC.
- PDFs are attachments or documents, not photos.
- Photos should be watermarked with the company name.
- Users cannot delete photos after report submission.
- Deleted photos remain recoverable by Admin.
- Block executable and script file types by default.

## UI/UX Notes
- Upload must support drag-drop on desktop and camera capture on mobile.
- Show upload progress, previews, and failure states.
- Display thumbnails in report forms and detail pages.
- Mobile upload should tolerate weak network conditions where possible.

## Technical Notes
- Use MinIO or S3-compatible object storage.
- Prefer presigned URLs for large file/photo uploads.
- Generate thumbnail and compressed versions asynchronously.
- Store project, report number, uploader, timestamp, original filename, size, MIME type, and optional location metadata.
- HEIC browser-display conversion requires stakeholder confirmation.
- Follow `../../ARCHITECTURE.md` file security exactly: whitelist by MIME magic bytes, randomized object keys, temporary signed download URLs, and no private file serving through Nginx.
- Photo processing must use Celery image tasks for thumbnail generation, compression, and watermarking.
- Store file binary data only in MinIO and metadata only in PostgreSQL.

## Priority
High

## Dependencies
- Object storage setup.
- Report and supervisor update flows.
- Company watermark text or asset.
- Confirmation of GPS/location metadata requirement.
- Confirmation of HEIC conversion behavior.

## Definition of Done
- Upload, preview, download, and protected delete behavior work.
- Photo variants and metadata are stored.
- Unsupported files are blocked.
- View/download actions are audited.
- Tests cover limits, permissions, and file validation.
