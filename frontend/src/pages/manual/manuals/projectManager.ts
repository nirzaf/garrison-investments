import type { Manual } from './common';

export const projectManagerManual: Manual = {
  roleKey: 'project_manager',
  roleLabel: 'Project Manager',
  tagline: 'Your project, your view — manage reports, documents, and finances within your scope.',
  overview:
    'As a Project Manager, you oversee the day-to-day operations of your assigned project(s). You can review and decide official daily reports for your assigned projects, inspect linked supervisor evidence, manage documents, request materials, and work with project invoices. Your dashboard is scoped to your project(s) only.',
  permissions: [
    'Scoped dashboard (your project only)',
    'View your assigned projects',
    'View and decide submitted daily reports on assigned projects',
    'View stock and create material requests for assigned active projects',
    'View and manage documents within your project',
    'View financial data'
  ],
  limitations: [
    'Company Analytics and Launch readiness are management pages',
    'Cannot manage users',
    'Cannot manage suppliers',
    'Stock receipts, reservation, and issue require inventory management permission',
    'Cannot access audit logs',
    'Dashboard is scoped to your assigned project(s) only'
  ],
  sections: [
    {
      id: 'dashboard',
      title: 'Your Scoped Dashboard',
      icon: '🏠',
      content:
        'Your dashboard shows data scoped to your assigned project(s). You will see active project and report counts, pending documents, and recent report activity within that scope, along with your unread alerts.',
      diagram: `
Your Dashboard (Project-Scoped):
┌──────────────────────────────────────────────────┐
│  Project Dashboard: [Your Project Name]          │
├───────────────┬───────────────┬──────────────────┤
│  Pending      │  Approved     │  Pending         │
│  Reports      │  Reports      │  Documents       │
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
        'Review submitted official daily reports for your assigned projects and inspect linked supervisor evidence.',
      steps: [
        {
          step: 1,
          action: 'Go to Approvals',
          detail:
            'Open Approvals in the sidebar, then choose Report approvals for submitted reports on assigned projects.'
        },
        {
          step: 2,
          action: 'Open a report',
          detail: 'Find the submitted report card and review the project and report date.'
        },
        {
          step: 3,
          action: 'Review the report',
          detail:
            'Review the report contents, attachments, history, and linked supervisor evidence.'
        },
        {
          step: 4,
          action: 'Approve or reject',
          detail:
            'Confirm target coverage and choose Approve, or enter a reason and choose Reject to return the report to draft.'
        }
      ],
      tips: [
        'Returned reports go back to the engineer for correction and resubmission.',
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
            'Report cards display work completed, next-day plan, safety, history, and status for reports in your scope.'
        },
        {
          step: 3,
          action: 'Download an approved report',
          detail: 'Use Download PDF on the approved report card.'
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
          detail: 'Search or filter by project and document type.'
        },
        {
          step: 3,
          action: 'Upload a document',
          detail:
            'Fill the upload form for an assigned project and choose Upload. Use Upload replacement to add a version to an existing document.'
        },
        {
          step: 4,
          action: 'Review versions',
          detail:
            'Choose Approve on an eligible pending project version. Use Download for the active version or a version-specific download from the history.'
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
      content:
        'View company-wide stock and material movements. Create requests for your assigned active projects.',
      steps: [
        { step: 1, action: 'Go to Materials', detail: 'Click "Materials" in the sidebar.' },
        {
          step: 2,
          action: 'View current stock',
          detail:
            'Select an item to see its location-level On hand, Reserved, and Available balances.'
        },
        {
          step: 3,
          action: 'Request materials',
          detail:
            'Choose an assigned active project and source location, add item quantities, and select Create request. Track it under My submitted requests in Approvals.'
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
            'Use Project filter to select an assigned project. The view is limited to your assigned projects.'
        },
        {
          step: 3,
          action: 'Review invoices and budget',
          detail:
            'Compare the project budget with billable invoices and recorded payments. Open an invoice number for its details or choose New invoice to enter a new one.'
        }
      ]
    }
  ]
};
