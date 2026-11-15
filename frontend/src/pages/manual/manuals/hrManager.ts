import type { Manual } from './common';

export const hrManagerManual: Manual = {
  roleKey: 'hr_manager',
  roleLabel: 'HR Manager',
  tagline: 'Maintain the workforce register and review HR decisions.',
  overview:
    'Open HR & Workforce to manage employee records, review submitted changes, and track onboarding, time, leave, and separation.',
  permissions: [
    'Review and activate employee drafts and update protected fields.',
    'Review employment, document, attendance, and leave decisions.',
    'Approve HR access requests for a director to fulfill.',
    'Record clearance and verify account deactivation before closing offboarding.'
  ],
  limitations: [
    'A different reviewer must decide a document version you uploaded or a request you made.',
    'Directors fulfill account changes. Payroll, bank details, and restricted cases are unavailable.'
  ],
  sections: [
    {
      id: 'hr-account-handoff',
      title: 'Account handoff',
      icon: '🔐',
      steps: [
        {
          step: 1,
          action: 'Review the employee draft',
          detail: 'Confirm the work email, employee code, and phone.'
        },
        {
          step: 2,
          action: 'Approve the request',
          detail: 'Review the requested role and reason under Access & Workbook.'
        },
        {
          step: 3,
          action: 'Check fulfillment',
          detail: 'A director completes the approved request under Access & Workbook.'
        }
      ]
    },
    {
      id: 'hr-file-review',
      title: 'Review a personnel document',
      icon: '📄',
      content:
        'Open Docs & Compliance and review a pending version. An approved replacement supersedes the active version.'
    },
    {
      id: 'hr-candidate-cv',
      title: 'Review a candidate CV',
      icon: '📄',
      content:
        'Open Recruitment and find Candidate CVs. Select the candidate and upload the confidential file. A different HR Manager downloads the pending version for review and records the decision. Upload a replacement to keep the version history together.'
    },
    {
      id: 'hr-letter-preview',
      title: 'Preview an employee letter',
      icon: '📄',
      content:
        'Open Policies & Requests and find HR letters. Save a template, find the employee by name or code, choose both records and select Preview letter. Employee details come from the directory. Review the preview before sharing it through the request or personnel document workflow.'
    },
    {
      id: 'hr-calendar-review',
      title: 'Review and publish a work calendar',
      icon: '📅',
      content:
        'In Attendance, open Work calendars, holidays and shifts. Verify the submitted workdays, effective dates, timezone and holidays. Approve a calendar prepared by another person, then publish it before assigning shifts. To change a published schedule, prepare a new calendar for a nonoverlapping period.'
    }
  ]
};
