import type { Manual } from './common';

export const generalManagerManual: Manual = {
  roleKey: 'general_manager',
  roleLabel: 'General Manager',
  tagline: 'Company-wide visibility and operational oversight across all projects.',
  overview:
    "As General Manager, you have a bird's-eye view of all company operations. You can see all projects, decide submitted daily reports, manage documents and suppliers, and access financial data. You are responsible for strategic oversight and ensuring that operations run smoothly across the board.",
  permissions: [
    'View all users',
    'View and manage all projects',
    'Access the full company-wide dashboard',
    'View and decide submitted official daily reports',
    'View stock and material requests across the company',
    'Manage suppliers',
    'View and upload documents across the company',
    'Access all financial data',
    'Access analytics and launch readiness'
  ],
  limitations: [
    'Cannot create or deactivate user accounts (Admin only)',
    'Cannot access audit logs or security events',
    'Cannot bulk-import users',
    'Stock receipts, reservation, and issue require inventory management permission',
    'Invoice and document approval require an eligible approver'
  ],
  sections: [
    {
      id: 'dashboard',
      title: 'Your Dashboard',
      icon: '🏠',
      content:
        'Your dashboard shows company-wide counts of active projects, pending and approved reports, and pending documents. It also shows recent activity and your unread alerts.',
      diagram: `
Dashboard Overview:
┌──────────────────────────────────────────────────┐
│  Company Dashboard (All Projects)                │
├────────────┬─────────────┬────────────┬──────────┤
│  Active    │  Pending    │  Approved  │  Pending │
│  Projects  │  Reports    │  Reports   │  Docs    │
└────────────┴─────────────┴────────────┴──────────┘
│                   Recent Activity                 │
└──────────────────────────────────────────────────┘
`,
      tips: ['Use the dashboard as your daily starting point to spot bottlenecks early.']
    },
    {
      id: 'projects',
      title: 'Viewing & Managing Projects',
      icon: '🏗️',
      content:
        'You have access to all projects. You can also manage project details and team assignments.',
      steps: [
        {
          step: 1,
          action: 'Go to Projects',
          detail: 'Open Projects and use search or status filters to find a project.'
        },
        {
          step: 2,
          action: 'Open a project',
          detail: 'Choose a project name to open its Overview, Team, and Timeline tabs.'
        },
        {
          step: 3,
          action: 'Manage project details',
          detail:
            'Edit project details from Overview and assign staff from Team. Completed and cancelled projects are read-only.'
        }
      ]
    },
    {
      id: 'approvals',
      title: 'Approving Reports',
      icon: '✅',
      content:
        'Review official daily reports and linked supervisor evidence before recording a decision.',
      steps: [
        { step: 1, action: 'Go to Approvals', detail: 'Click "Approvals" in the sidebar.' },
        {
          step: 2,
          action: 'Find a submitted report',
          detail: 'Open Report approvals and find the submitted report card.'
        },
        {
          step: 3,
          action: 'Review details',
          detail:
            'Review the report contents, attachments, history, and linked supervisor evidence.'
        },
        {
          step: 4,
          action: 'Make a decision',
          detail:
            'Confirm target coverage and choose Approve, or enter a reason and choose Reject to return the report to draft.'
        }
      ],
      tips: [
        'Prioritise reviewing reports submitted today — engineers rely on approvals to progress their workflows.',
        'Use Supervisor updates to review submitted and verified field updates.'
      ]
    },
    {
      id: 'finance',
      title: 'Reviewing Financials',
      icon: '💰',
      content: 'Review invoices, recorded payments, outstanding amounts, and budget comparisons.',
      steps: [
        { step: 1, action: 'Go to Finance', detail: 'Click "Finance" in the sidebar.' },
        {
          step: 2,
          action: 'Select a view',
          detail: 'Use Project filter and Invoice status filter to narrow the invoice register.'
        },
        {
          step: 3,
          action: 'Review an invoice',
          detail:
            'Open an invoice number for its details and recorded payments. The project budget comparison appears after selecting a project.'
        }
      ]
    },
    {
      id: 'analytics',
      title: 'Analytics and launch readiness',
      icon: '📊',
      content:
        'Use Analytics for company-wide project and material metrics and Launch readiness for release verification.',
      steps: [
        {
          step: 1,
          action: 'Go to Analytics',
          detail:
            'Click "Analytics" for charts on project progress, report submission rates, and more.'
        },
        {
          step: 2,
          action: 'Open Launch readiness',
          detail: 'Review release verification and acceptance checks.'
        }
      ]
    },
    {
      id: 'documents',
      title: 'Documents',
      icon: '📄',
      content:
        'View and manage all documents across projects — contracts, drawings, compliance certificates, and more.',
      steps: [
        { step: 1, action: 'Go to Documents', detail: 'Click "Documents" in the sidebar.' },
        {
          step: 2,
          action: 'Browse or search',
          detail: 'Search or filter by project and document type to find what you need.'
        },
        {
          step: 3,
          action: 'Upload a document',
          detail:
            'Complete the upload form, choose the file, then select Upload. Use Upload replacement to add a version of an existing document.'
        }
      ]
    }
  ]
};
