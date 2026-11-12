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
    'View your own daily reports and submitted supervisor updates on assigned projects',
    'View stock and create material requests for assigned active projects',
    'View and manage documents within your project'
  ],
  limitations: [
    'Cannot approve reports (approval authority belongs to managers)',
    'Cannot manage users or user accounts',
    'Cannot manage suppliers',
    'Cannot access financial data',
    'Stock receipts, reservation, and issue require inventory management permission',
    'Cannot access analytics or company-wide dashboard',
    'Cannot access audit logs'
  ],
  sections: [
    {
      id: 'daily-report',
      title: 'Submitting a Daily Report',
      icon: '📝',
      content:
        'Daily reports are the core of your workflow. Use the form to document site progress, activities, material usage, and any issues encountered.',
      steps: [
        {
          step: 1,
          action: 'Go to Reports',
          detail: 'Click "Reports" in the sidebar. This takes you to the Daily Report page.'
        },
        {
          step: 2,
          action: 'Start or resume a report',
          detail:
            'Use the Engineer Daily Report form, or choose Resume report on one of your drafts under Recent Daily Reports.'
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
          action: 'Link field evidence',
          detail:
            'Select relevant submitted Supervisor Updates and add evidence with Upload photos or Upload attachments. The updates are verified when you submit.'
        },
        {
          step: 7,
          action: 'Submit the report',
          detail:
            'Choose Save draft to continue later or Submit report to send it for manager review. Submitting requires a connection.'
        }
      ],
      tips: [
        'Submit reports before end of business each day — managers review them in the morning.',
        'Be specific about quantities. Vague entries (e.g., "some concrete poured") lead to rejected reports.',
        'Edit a draft before submission. A submitted report is read-only until a reviewer returns it.',
        'If a reviewer returns your report, open it from the notification or choose Resume report, correct the draft, and submit again.'
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
      content: 'Recent Daily Reports shows your reports and their status for the selected project.',
      steps: [
        { step: 1, action: 'Go to Reports', detail: 'Click "Reports" in the sidebar.' },
        {
          step: 2,
          action: 'Browse your reports',
          detail:
            'Recent Daily Reports shows your drafts, submitted reports, and approved reports for the selected project.'
        },
        {
          step: 3,
          action: 'Resume a draft',
          detail:
            'Choose Resume report to load an editable draft, including one returned by a reviewer.'
        },
        {
          step: 4,
          action: 'Download an approved report',
          detail: 'Use Download PDF on the approved report card.'
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
          action: 'Open the report form',
          detail: 'Go to Reports and complete the required fields or resume your draft.'
        },
        {
          step: 2,
          action: 'Upload photos',
          detail:
            'Use Upload photos in the report form. Each report accepts up to five JPEG, PNG, or HEIC photos, up to 10 MiB each.'
        },
        {
          step: 3,
          action: 'Check saved evidence',
          detail:
            'Review saved files in the draft. Offline files queue for upload when your account reconnects. Use Photos to review accessible uploads.'
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
          detail:
            'Enter the document title, type, and assigned project, select the file, then choose Upload. Use Upload replacement on an existing document for a new version.'
        },
        {
          step: 4,
          action: 'Download drawings',
          detail: 'Choose Download on the document card to get the active approved version.'
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
        'Check company-wide stock by location and request materials for assigned active projects.',
      steps: [
        { step: 1, action: 'Go to Materials', detail: 'Click "Materials" in the sidebar.' },
        {
          step: 2,
          action: 'Check stock levels',
          detail:
            'Select an inventory item and check On hand, Reserved, and Available in its stock matrix.'
        },
        {
          step: 3,
          action: 'Create a material request',
          detail:
            'Select an assigned active project and source location, add the item quantities, and choose Create request. Follow the request in Materials or My submitted requests in Approvals.'
        }
      ]
    }
  ]
};
