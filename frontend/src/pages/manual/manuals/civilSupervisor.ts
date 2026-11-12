import type { Manual } from './common';

export const civilSupervisorManual: Manual = {
  roleKey: 'civil_supervisor',
  roleLabel: 'Civil Supervisor',
  tagline: 'Submit daily supervisor updates and track your assigned project.',
  overview:
    'As a Civil Supervisor, you report on day-to-day site supervision activities. Your key task is submitting Supervisor Updates — a form specifically designed for site supervisors that captures attendance, overtime, work location, progress, delays, and supporting evidence. Your access is focused on the reporting tools you need.',
  permissions: [
    'Scoped dashboard (your project only)',
    'View your assigned projects',
    'Submit supervisor update reports',
    'View your own site updates and accessible site photos',
    'View documents within your project'
  ],
  limitations: [
    'Use Supervisor Site Update for field reporting. Official engineer daily reports are restricted to their authorized roles.',
    'Cannot approve any reports',
    'Cannot manage users or user accounts',
    'Cannot access inventory or materials',
    'Cannot access financial data',
    'Cannot access analytics or company-wide dashboard',
    'Cannot manage or upload documents',
    'Cannot access audit logs'
  ],
  sections: [
    {
      id: 'supervisor-update',
      title: 'Submitting a Supervisor Update',
      icon: '📝',
      content:
        "The Supervisor Update is your primary daily task. It is a streamlined form designed for site supervision data — different from the engineer's daily report.",
      steps: [
        {
          step: 1,
          action: 'Go to Reports',
          detail:
            'Click "Reports" in the sidebar. As a supervisor, this takes you directly to the Supervisor Update page.'
        },
        {
          step: 2,
          action: 'Start or resume an update',
          detail:
            'Use the Supervisor Site Update form or select Resume draft under Recent Site Updates.'
        },
        {
          step: 3,
          action: 'Select your project',
          detail: 'Choose the project you are supervising from the project selector.'
        },
        {
          step: 4,
          action: 'Fill in workforce data',
          detail: 'Enter Attendance and Overtime hours. Set the Update date and Day type.'
        },
        {
          step: 5,
          action: 'Record activities supervised',
          detail: 'Enter Work location and describe the activities in Progress notes.'
        },
        {
          step: 6,
          action: 'Record delays and requirements',
          detail: 'Use Delay notes for setbacks and Required notes for follow-up work or issues.'
        },
        {
          step: 7,
          action: 'Attach evidence',
          detail:
            'Use Upload photos or Upload attachments. Up to five JPEG, PNG, or HEIC photos can be saved, at up to 10 MiB each.'
        },
        {
          step: 8,
          action: 'Submit',
          detail:
            'Choose Submit update. An engineer can select the submitted update as evidence when preparing a daily report.'
        }
      ],
      tips: [
        'Use Save draft to save your work. Open it again with Resume draft under Recent Site Updates.',
        'Submit before leaving site each day — this ensures the record is accurate while the day is fresh.',
        'Be specific about safety observations — they are important for compliance and incident prevention.',
        'If a delivery does not match the delivery note, document the discrepancy before signing anything.'
      ],
      diagram: `
Supervisor Update Flow:
[Supervisor submits update] → [Engineer selects it for a daily report]
                                        ↓
                       [Update verified when engineer submits report]
`
    },
    {
      id: 'viewing-reports',
      title: 'Viewing Past Updates',
      icon: '📋',
      content:
        'Review your site updates and check whether a submitted update was verified in a daily report.',
      steps: [
        { step: 1, action: 'Go to Reports', detail: 'Click "Reports" in the sidebar.' },
        {
          step: 2,
          action: 'View your update history',
          detail:
            'Recent Site Updates shows your drafts, submitted updates, and verified updates for the selected project.'
        },
        {
          step: 3,
          action: 'Check verification',
          detail:
            'A verified update shows the verification time, verifier when available, and linked report reference.'
        }
      ]
    },
    {
      id: 'documents',
      title: 'Viewing Project Documents',
      icon: '📄',
      content:
        'You can view project documents such as method statements, safety plans, and site drawings.',
      steps: [
        { step: 1, action: 'Go to Documents', detail: 'Click "Documents" in the sidebar.' },
        {
          step: 2,
          action: 'Browse documents',
          detail:
            'Use the document list to find the file you need. Filter by type or search by name.'
        },
        {
          step: 3,
          action: 'Download a document',
          detail: 'Use Preview or Download on the document card for the active approved version.'
        }
      ],
      tips: [
        'Check for updated method statements before starting any activity — they may have been revised by the project team.',
        'If you need a document uploaded, contact your Project Manager or Civil Engineer.'
      ]
    },
    {
      id: 'dashboard',
      title: 'Your Dashboard',
      icon: '🏠',
      content:
        'Your dashboard summarizes assigned projects, report and document counts, and unread alerts. Use Reports for the status of your own site updates.',
      tips: ['Check Recent Site Updates in Reports for submitted and verified status.']
    }
  ]
};
