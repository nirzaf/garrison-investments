import type { Manual } from './common';

export const projectManagerManual: Manual = {
  roleKey: 'project_manager',
  roleLabel: 'Project Manager',
  tagline: 'Your project, your view — manage reports, documents, and finances within your scope.',
  overview:
    'As a Project Manager, you oversee the day-to-day operations of your assigned project(s). You can view and approve reports submitted by engineers and supervisors on your project, manage documents, track materials, and review financial data. Your dashboard is scoped to your project(s) only.',
  permissions: [
    'Scoped dashboard (your project only)',
    'View your assigned projects',
    'View and approve reports within your project',
    'View inventory',
    'View and manage documents within your project',
    'View financial data'
  ],
  limitations: [
    'Cannot access company-wide analytics or delivery planning',
    'Cannot manage users',
    'Cannot manage suppliers',
    'Cannot manage inventory (view only)',
    'Cannot access audit logs',
    'Dashboard is scoped to your assigned project(s) only'
  ],
  sections: [
    {
      id: 'dashboard',
      title: 'Your Scoped Dashboard',
      icon: '🏠',
      content:
        'Your dashboard shows data scoped to your assigned project(s). You will see pending approvals, recent report activity, and material usage — all filtered for your project.',
      diagram: `
Your Dashboard (Project-Scoped):
┌──────────────────────────────────────────────────┐
│  Project Dashboard: [Your Project Name]          │
├───────────────┬───────────────┬──────────────────┤
│  Pending      │  Reports      │  Materials       │
│  Approvals    │  This Week    │  Summary         │
└───────────────┴───────────────┴──────────────────┘
│  Recent Reports (from your project only)         │
└──────────────────────────────────────────────────┘
`,
      tips: [
        'Check your dashboard each morning to catch any pending approvals before the field team starts work.'
      ]
    },
    {
      id: 'approvals',
      title: 'Approving Reports',
      icon: '✅',
      content:
        'Your main daily task is reviewing and approving reports submitted by engineers and supervisors on your project.',
      steps: [
        {
          step: 1,
          action: 'Go to Approvals',
          detail: 'Click "Approvals" in the sidebar. You will only see reports from your project.'
        },
        {
          step: 2,
          action: 'Open a report',
          detail: 'Click on a pending report to view its details.'
        },
        {
          step: 3,
          action: 'Review the report',
          detail:
            'Check the activities listed, quantities recorded, and any attached photos or notes.'
        },
        {
          step: 4,
          action: 'Approve or reject',
          detail:
            'Click "Approve" to accept. If there are issues, click "Reject" with a clear reason for the engineer.'
        }
      ],
      tips: [
        'Engineers cannot progress their workflow until you approve. Aim to review reports by end of day.',
        'If quantities seem off, cross-reference with the Materials page to verify stock movements.'
      ]
    },
    {
      id: 'reports',
      title: 'Viewing Daily Reports',
      icon: '📋',
      content: 'View the history of daily reports submitted for your project.',
      steps: [
        {
          step: 1,
          action: 'Go to Reports',
          detail: 'Click "Reports" in the sidebar (points to Daily Reports by default).'
        },
        {
          step: 2,
          action: 'Browse the report list',
          detail:
            'You will see all reports for your project, with status (pending, approved, rejected).'
        },
        {
          step: 3,
          action: 'Filter by date',
          detail: 'Use the date range filter to review a specific week or month.'
        }
      ]
    },
    {
      id: 'documents',
      title: 'Managing Documents',
      icon: '📄',
      content:
        'Keep project documentation organised — contracts, drawings, permits, and site records.',
      steps: [
        { step: 1, action: 'Go to Documents', detail: 'Click "Documents" in the sidebar.' },
        {
          step: 2,
          action: 'Search or browse',
          detail: 'Find documents by type, category, or search keyword.'
        },
        {
          step: 3,
          action: 'Upload a document',
          detail: 'Click "Upload", select your file and document category, then confirm.'
        },
        {
          step: 4,
          action: 'Download or share',
          detail: 'Click on a document to download it or copy a share link for your team.'
        }
      ],
      tips: [
        'Keep the Documents folder organised by naming files consistently: YYYY-MM-DD_ProjectName_DocType.'
      ]
    },
    {
      id: 'inventory',
      title: 'Viewing Materials',
      icon: '📦',
      content: 'Monitor material consumption and stock levels for your project.',
      steps: [
        { step: 1, action: 'Go to Materials', detail: 'Click "Materials" in the sidebar.' },
        {
          step: 2,
          action: 'View current stock',
          detail: 'See the inventory table with material names, quantities, and units.'
        },
        {
          step: 3,
          action: 'Track consumption',
          detail:
            'Compare inventory levels with report quantities to ensure materials are being logged correctly.'
        }
      ]
    },
    {
      id: 'finance',
      title: 'Project Financials',
      icon: '💰',
      content: 'View financial records associated with your project.',
      steps: [
        { step: 1, action: 'Go to Finance', detail: 'Click "Finance" in the sidebar.' },
        {
          step: 2,
          action: 'Filter to your project',
          detail:
            'The finance view is pre-scoped to your project, but confirm the project selector shows the right project.'
        },
        {
          step: 3,
          action: 'Review cost lines',
          detail: 'Check cost breakdowns, supplier invoices, and budget vs. actual spending.'
        }
      ]
    }
  ]
};
