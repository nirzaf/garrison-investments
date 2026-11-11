import type { Manual } from './common';

export const civilEngineerManual: Manual = {
  roleKey: 'civil_engineer',
  roleLabel: 'Civil Engineer',
  tagline: "Submit daily reports and stay on top of your project's progress.",
  overview:
    'As a Civil Engineer, you are the primary point of contact between the construction site and the portal. Your main responsibilities are submitting daily progress reports, documenting site activities, and uploading supporting evidence such as photos. Your view is scoped to the project(s) you have been assigned to.',
  permissions: [
    'Scoped dashboard (your project only)',
    'View your assigned projects',
    'Submit daily reports',
    'View reports within your project',
    'View inventory',
    'View and manage documents within your project'
  ],
  limitations: [
    'Cannot approve reports (approval authority belongs to managers)',
    'Cannot manage users or user accounts',
    'Cannot manage suppliers',
    'Cannot access financial data',
    'Cannot manage inventory (view only)',
    'Cannot access analytics or company-wide dashboard',
    'Cannot access audit logs'
  ],
  sections: [
    {
      id: 'daily-report',
      title: 'Submitting a Daily Report',
      icon: '📝',
      content:
        'Daily reports are the core of your workflow. You submit one per day per project to document site progress, activities, material usage, and any issues encountered.',
      steps: [
        {
          step: 1,
          action: 'Go to Reports',
          detail: 'Click "Reports" in the sidebar. This takes you to the Daily Report page.'
        },
        {
          step: 2,
          action: 'Click "New Report"',
          detail: 'Click the "New Report" or equivalent button at the top of the page.'
        },
        {
          step: 3,
          action: 'Select your project',
          detail: 'Choose the project this report is for from the project selector.'
        },
        {
          step: 4,
          action: 'Fill in activities',
          detail:
            'Describe the work carried out today: which activities, what progress was made, and any deviations from the plan.'
        },
        {
          step: 5,
          action: 'Record material usage',
          detail:
            'Enter quantities of materials used. Cross-reference with what was physically counted on site.'
        },
        {
          step: 6,
          action: 'Add notes/photos',
          detail:
            'Attach any relevant photos from site and add notes about site conditions, weather, or blockers.'
        },
        {
          step: 7,
          action: 'Submit the report',
          detail:
            'Click "Submit". The report will be sent to your Project Manager or approver for review.'
        }
      ],
      tips: [
        'Submit reports before end of business each day — managers review them in the morning.',
        'Be specific about quantities. Vague entries (e.g., "some concrete poured") lead to rejected reports.',
        'If you made a mistake, you can edit a report before it is approved.',
        'If your report is rejected, check the rejection reason in your notifications and correct it.'
      ],
      diagram: `
Daily Report Workflow:
[You fill in report] ──→ [Submit]
                              │
                    [Project Manager reviews]
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
        [Approved ✓]                    [Rejected ✗]
              │                               │
    [Report finalised]         [Notification → You correct]
                                              │
                                        [Resubmit]
`
    },
    {
      id: 'viewing-reports',
      title: 'Viewing Past Reports',
      icon: '📋',
      content:
        'You can view all reports you have previously submitted, including their approval status.',
      steps: [
        { step: 1, action: 'Go to Reports', detail: 'Click "Reports" in the sidebar.' },
        {
          step: 2,
          action: 'Browse your reports',
          detail:
            'The report list shows all your submissions with statuses: Pending, Approved, or Rejected.'
        },
        {
          step: 3,
          action: 'Filter by date',
          detail: 'Use the date range picker to find a specific week or month of reports.'
        },
        {
          step: 4,
          action: 'Open a report',
          detail: 'Click on any report to view its full details and approval history.'
        }
      ]
    },
    {
      id: 'photos',
      title: 'Site Photos',
      icon: '📷',
      content: 'Upload and manage site photos that serve as evidence for daily reports.',
      steps: [
        {
          step: 1,
          action: 'Go to Photos',
          detail: 'Click "Photos" in the sidebar to open the photo gallery.'
        },
        {
          step: 2,
          action: 'Upload photos',
          detail: 'Click "Upload" and select photos from your device. Add captions or tags.'
        },
        {
          step: 3,
          action: 'Attach to reports',
          detail:
            'When submitting a daily report, link photos from the gallery or upload directly in the report form.'
        }
      ],
      tips: [
        'Take photos of material deliveries with the delivery note visible for accurate quantity verification.'
      ]
    },
    {
      id: 'documents',
      title: 'Project Documents',
      icon: '📄',
      content:
        'View and manage project documents such as drawings, specifications, and site instructions.',
      steps: [
        { step: 1, action: 'Go to Documents', detail: 'Click "Documents" in the sidebar.' },
        {
          step: 2,
          action: 'Find a document',
          detail: 'Use the search or filter by document type to quickly locate what you need.'
        },
        {
          step: 3,
          action: 'Upload a document',
          detail: 'If you have a new site document, click "Upload" and categorise it correctly.'
        },
        {
          step: 4,
          action: 'Download drawings',
          detail: 'Click on a drawing or specification document to download the latest version.'
        }
      ],
      tips: [
        'Always download the latest version of drawings before starting work — documents can be updated by the project team.'
      ]
    },
    {
      id: 'inventory-view',
      title: 'Checking Materials',
      icon: '📦',
      content:
        'View current inventory levels to understand what materials are available on your project.',
      steps: [
        { step: 1, action: 'Go to Materials', detail: 'Click "Materials" in the sidebar.' },
        {
          step: 2,
          action: 'Check stock levels',
          detail: 'See the current quantities of materials allocated to your project.'
        },
        {
          step: 3,
          action: 'Report discrepancies',
          detail:
            'If the portal shows a quantity that does not match the physical count, raise it with your project manager.'
        }
      ]
    }
  ]
};
