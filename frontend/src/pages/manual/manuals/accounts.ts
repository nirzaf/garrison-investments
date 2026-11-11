import type { Manual } from './common';

export const accountsManual: Manual = {
  roleKey: 'accounts',
  roleLabel: 'Accounts',
  tagline: 'Finance visibility and document access — keep the numbers in order.',
  overview:
    'As an Accounts user, your focus is on financial data, project cost tracking, and documentation. You can view financial records across your assigned project scope, access and manage documents relevant to accounting (invoices, contracts, certificates), and review daily reports for cost reconciliation purposes.',
  permissions: [
    'Scoped dashboard',
    'View assigned projects',
    'View reports within your project scope',
    'View and manage documents',
    'Access financial data'
  ],
  limitations: [
    'Cannot submit or approve reports',
    'Cannot manage users',
    'Cannot manage inventory or suppliers',
    'Cannot access analytics or delivery planning',
    'Cannot access audit logs',
    'Dashboard and data are scoped (not company-wide unless assigned to a company-level project)'
  ],
  sections: [
    {
      id: 'dashboard',
      title: 'Your Dashboard',
      icon: '🏠',
      content:
        'Your dashboard provides a project-scoped financial overview: cost summaries, recent financial activity, and document activity.',
      tips: [
        'Use your dashboard as a starting point each morning to check for new financial entries or document uploads that require your review.'
      ]
    },
    {
      id: 'finance',
      title: 'Accessing Financial Data',
      icon: '💰',
      content:
        'The Finance page is your primary workspace. You can view project cost breakdowns, supplier invoices, and financial summaries.',
      steps: [
        { step: 1, action: 'Go to Finance', detail: 'Click "Finance" in the sidebar.' },
        {
          step: 2,
          action: 'Select a project',
          detail: 'Use the project selector to filter financial data for a specific project.'
        },
        {
          step: 3,
          action: 'Review cost entries',
          detail: 'Browse cost lines, supplier charges, and budget comparisons.'
        },
        {
          step: 4,
          action: 'View supplier invoices',
          detail:
            'Click on an invoice line to see the full invoice detail or download the document.'
        },
        {
          step: 5,
          action: 'Export data',
          detail:
            'Use the export button to download the financial summary as a spreadsheet for external reporting.'
        }
      ],
      tips: [
        'Cross-reference material issues from the Materials page with finance entries to ensure all consumed materials are accounted for.',
        'If you find a discrepancy, raise it with the Store Keeper or Project Manager.'
      ],
      diagram: `
Financial Data Sources (in the Finance page):
[Material Issues] ──→ [Project Cost Lines]
[Supplier Invoices] ──→ [Finance Records]
[Report Quantities] ──→ [Activity Cost Tracking]
                              │
                              ▼
                   [Finance Page Summary]
                              │
                              ▼
                   [Export to Spreadsheet]
`
    },
    {
      id: 'documents',
      title: 'Managing Accounting Documents',
      icon: '📄',
      content:
        'Use the Documents page to manage financial documents: invoices, purchase orders, payment certificates, contracts, and tax documents.',
      steps: [
        { step: 1, action: 'Go to Documents', detail: 'Click "Documents" in the sidebar.' },
        {
          step: 2,
          action: 'Filter by document type',
          detail:
            'Use the type/category filter to view only financial documents (invoices, contracts, etc.).'
        },
        {
          step: 3,
          action: 'Upload a document',
          detail:
            'Click "Upload", select your file, choose the appropriate category (e.g., Invoice, Contract), and confirm.'
        },
        {
          step: 4,
          action: 'Download or verify',
          detail: 'Click on a document to download it or verify its contents against your records.'
        }
      ],
      tips: [
        'Name documents consistently: YYYY-MM-DD_SupplierName_InvoiceNumber.pdf',
        'Always upload the original document, not a scanned photo when possible — it is easier to read and archive.'
      ]
    },
    {
      id: 'reports-view',
      title: 'Reviewing Daily Reports',
      icon: '📋',
      content:
        'You can view daily reports from engineers and supervisors to reconcile material usage and labour activities with financial entries.',
      steps: [
        {
          step: 1,
          action: 'Go to Reports',
          detail: 'Click "Reports" in the sidebar (takes you to Daily Reports).'
        },
        {
          step: 2,
          action: 'Browse the report list',
          detail: 'View all approved reports for your project. Filter by date range.'
        },
        {
          step: 3,
          action: 'Open a report',
          detail: 'Click a report to view materials used, activities, and any notes.'
        },
        {
          step: 4,
          action: 'Cross-reference with finance',
          detail: 'Use the quantities in the report to verify matching entries in the Finance page.'
        }
      ],
      tips: [
        'Focus on approved reports — pending or rejected reports may not yet reflect actual site activity.',
        'If material quantities in a report do not match finance entries, alert the Project Manager.'
      ]
    },
    {
      id: 'projects-view',
      title: 'Viewing Projects',
      icon: '🏗️',
      content:
        'You can view project details to understand the scope and context of financial data.',
      steps: [
        { step: 1, action: 'Go to Projects', detail: 'Click "Projects" in the sidebar.' },
        {
          step: 2,
          action: 'Open a project',
          detail: 'Click on a project to see its details, team, and financial summary.'
        }
      ]
    }
  ]
};
