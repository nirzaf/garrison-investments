import type { Manual } from './common';

export const generalManagerManual: Manual = {
  roleKey: 'general_manager',
  roleLabel: 'General Manager',
  tagline: 'Company-wide visibility and operational oversight across all projects.',
  overview:
    "As General Manager, you have a bird's-eye view of all company operations. You can see all projects, approve reports from the field, manage documents, access financial data, and plan deliveries. You are responsible for strategic oversight and ensuring that operations run smoothly across the board.",
  permissions: [
    'View all users',
    'View and manage all projects',
    'Access the full company-wide dashboard',
    'View and approve all reports',
    'View and manage all inventory',
    'Manage suppliers',
    'View and manage all documents',
    'Access all financial data',
    'Access analytics and delivery planning'
  ],
  limitations: [
    'Cannot create or deactivate user accounts (Admin only)',
    'Cannot access audit logs or security events',
    'Cannot bulk-import users'
  ],
  sections: [
    {
      id: 'dashboard',
      title: 'Your Dashboard',
      icon: '🏠',
      content:
        'Your dashboard shows a company-wide summary: active projects, recent reports, pending approvals, and key metrics. Unlike scoped roles, you see data from all projects.',
      diagram: `
Dashboard Overview:
┌──────────────────────────────────────────────────┐
│  Company Dashboard (All Projects)                │
├────────────┬─────────────┬────────────┬──────────┤
│  Active    │  Pending    │  Reports   │  Finance │
│  Projects  │  Approvals  │  This Week │  Summary │
└────────────┴─────────────┴────────────┴──────────┘
│              Project List (all projects)          │
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
          detail: 'Click "Projects" in the sidebar to see all active projects.'
        },
        {
          step: 2,
          action: 'Open a project',
          detail:
            'Click on any project to view its detail page: reports, materials, and financials.'
        },
        {
          step: 3,
          action: 'Manage project details',
          detail: 'Edit the project name, location, status, or assigned staff from the detail page.'
        }
      ]
    },
    {
      id: 'approvals',
      title: 'Approving Reports',
      icon: '✅',
      content: 'Review field reports from engineers and supervisors and approve or reject them.',
      steps: [
        { step: 1, action: 'Go to Approvals', detail: 'Click "Approvals" in the sidebar.' },
        {
          step: 2,
          action: 'Open a pending report',
          detail: 'Click on a report item in the list to open it.'
        },
        {
          step: 3,
          action: 'Review details',
          detail: 'Read the report description, activities, quantities, and attached photos.'
        },
        {
          step: 4,
          action: 'Make a decision',
          detail:
            'Click "Approve" to accept, or "Reject" with a reason. The submitter will be notified.'
        }
      ],
      tips: [
        'Prioritise reviewing reports submitted today — engineers rely on approvals to progress their workflows.',
        'Use the filter to view reports by project or date range.'
      ]
    },
    {
      id: 'finance',
      title: 'Reviewing Financials',
      icon: '💰',
      content: 'Access financial records, project costs, and supplier invoices.',
      steps: [
        { step: 1, action: 'Go to Finance', detail: 'Click "Finance" in the sidebar.' },
        {
          step: 2,
          action: 'Select a view',
          detail: 'Filter by project or date to focus on specific financial data.'
        },
        {
          step: 3,
          action: 'Export reports',
          detail:
            'Download financial summaries using the export function for board reports or external use.'
        }
      ]
    },
    {
      id: 'analytics',
      title: 'Analytics and launch readiness',
      icon: '📊',
      content: 'Access executive-level charts and manage delivery scheduling.',
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
          detail: 'Filter by project, document type, or date to find what you need.'
        },
        {
          step: 3,
          action: 'Upload a document',
          detail: 'Click "Upload", select the file and document category, then save.'
        }
      ]
    }
  ]
};
