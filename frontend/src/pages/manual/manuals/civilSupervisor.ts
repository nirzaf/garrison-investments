import type { Manual } from './common';

export const civilSupervisorManual: Manual = {
  roleKey: 'civil_supervisor',
  roleLabel: 'Civil Supervisor',
  tagline: 'Submit daily supervisor updates and track your assigned project.',
  overview:
    'As a Civil Supervisor, you report on day-to-day site supervision activities. Your key task is submitting Supervisor Updates — a form specifically designed for site supervisors that captures worker attendance, activities overseen, safety observations, and materials received. Your access is focused on the reporting tools you need.',
  permissions: [
    'Scoped dashboard (your project only)',
    'View your assigned projects',
    'Submit supervisor update reports',
    'View reports within your project',
    'View documents within your project',
  ],
  limitations: [
    'Cannot submit the standard daily engineer report (you use the Supervisor Update form instead)',
    'Cannot approve any reports',
    'Cannot manage users or user accounts',
    'Cannot access inventory or materials',
    'Cannot access financial data',
    'Cannot access analytics or company-wide dashboard',
    'Cannot manage or upload documents',
    'Cannot access audit logs',
  ],
  sections: [
    {
      id: 'supervisor-update',
      title: 'Submitting a Supervisor Update',
      icon: '📝',
      content:
        'The Supervisor Update is your primary daily task. It is a streamlined form designed for site supervision data — different from the engineer\'s daily report.',
      steps: [
        { step: 1, action: 'Go to Reports', detail: 'Click "Reports" in the sidebar. As a supervisor, this takes you directly to the Supervisor Update page.' },
        { step: 2, action: 'Start a new update', detail: 'Click "New Update" or the equivalent button.' },
        { step: 3, action: 'Select your project', detail: 'Choose the project you are supervising from the project selector.' },
        { step: 4, action: 'Fill in workforce data', detail: 'Enter the number of workers present today, their trades, and any absenteeism.' },
        { step: 5, action: 'Record activities supervised', detail: 'List the construction activities you supervised today and your observations on quality and safety.' },
        { step: 6, action: 'Note materials received', detail: 'Record any materials delivered to site today including quantities and delivery note references.' },
        { step: 7, action: 'Add safety observations', detail: 'Note any safety incidents, near-misses, or hazards observed and what corrective action was taken.' },
        { step: 8, action: 'Submit', detail: 'Click "Submit". The update goes to your Project Manager or Operation Manager for review.' },
      ],
      tips: [
        'Submit before leaving site each day — this ensures the record is accurate while the day is fresh.',
        'Be specific about safety observations — they are important for compliance and incident prevention.',
        'If a delivery does not match the delivery note, document the discrepancy before signing anything.',
      ],
      diagram: `
Supervisor Update Flow:
[You fill in daily update] ──→ [Submit]
                                    │
                        [Manager reviews in Approvals]
                                    │
                ┌───────────────────┴────────────────────┐
                ▼                                        ▼
          [Approved ✓]                            [Rejected ✗]
                │                                        │
      [Update finalised]            [You receive notification → Correct & resubmit]
`,
    },
    {
      id: 'viewing-reports',
      title: 'Viewing Past Updates',
      icon: '📋',
      content: 'Review your previously submitted supervisor updates and track their approval status.',
      steps: [
        { step: 1, action: 'Go to Reports', detail: 'Click "Reports" in the sidebar.' },
        { step: 2, action: 'View your update history', detail: 'See a list of all your submitted updates with their current status.' },
        { step: 3, action: 'Check for rejections', detail: 'If a report has been rejected, it will be highlighted. Click to see the reason and resubmit after corrections.' },
      ],
    },
    {
      id: 'documents',
      title: 'Viewing Project Documents',
      icon: '📄',
      content: 'You can view project documents such as method statements, safety plans, and site drawings.',
      steps: [
        { step: 1, action: 'Go to Documents', detail: 'Click "Documents" in the sidebar.' },
        { step: 2, action: 'Browse documents', detail: 'Use the document list to find the file you need. Filter by type or search by name.' },
        { step: 3, action: 'Download a document', detail: 'Click on a document to open or download it.' },
      ],
      tips: [
        'Check for updated method statements before starting any activity — they may have been revised by the project team.',
        'If you need a document uploaded, contact your Project Manager or Civil Engineer.',
      ],
    },
    {
      id: 'dashboard',
      title: 'Your Dashboard',
      icon: '🏠',
      content: 'Your dashboard shows a quick summary scoped to your project: your recent updates and their statuses.',
      tips: ['If you see old pending reports in your dashboard, follow up to ensure they have been reviewed by your manager.'],
    },
  ],
};
