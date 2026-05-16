# Report PDF Export and Email Delivery

## Title
Report PDF Export and Email Delivery

## User Story
As a Project Manager,
I want approved daily reports exported as PDFs and emailed,
so that official site records can be shared and archived in company format.

## Description
Generate printable daily report PDFs using company or client templates, allow PDF download, and email the PDF after approval.

## Acceptance Criteria
1. Given a report is approved,
   When I open the report detail,
   Then I can download a PDF version.

2. Given the approval completes,
   When the system processes post-approval tasks,
   Then the report PDF is emailed to configured recipients.

3. Given a company or client template is configured,
   When the PDF is generated,
   Then the output follows that template.

4. Given PDF generation fails,
   When the report remains approved,
   Then the failure is logged and visible to authorized support users.

## Business Rules
- Daily reports must be printable as PDF.
- After approvals, the daily report PDF should be emailed.
- Reports should use the company's own format.
- If a client has a required format, the system should allow that template to be uploaded or used.
- Official PDFs must preserve report number, approval status, approver, and timestamps.

## UI/UX Notes
- PDF download should be available from report detail.
- Users should see a clear generation or email status.
- Report layout should match company paper forms where users rely on them.

## Technical Notes
- Use a server-side PDF generation service such as WeasyPrint or equivalent.
- Queue email delivery through Celery.
- Store generated PDF metadata and regeneration status if needed.
- Add retry and error logging for email delivery.
- Follow `../../ARCHITECTURE.md` task layer: `generate_report_pdf` and email notification work must run through Celery queues with retries.
- Large or asynchronous exports should return a task response and be polled through export task endpoints when generation cannot complete in-request.
- Store generated files in MinIO with database metadata only.

## Priority
High

## Dependencies
- Approved daily report flow.
- Email service configuration.
- Company and client report templates.
- File storage service.

## Definition of Done
- Approved reports can be exported to PDF.
- PDF email task runs after approval.
- Template-driven output is supported.
- Failures are logged and recoverable.
- Tests cover successful generation and email failure handling.
