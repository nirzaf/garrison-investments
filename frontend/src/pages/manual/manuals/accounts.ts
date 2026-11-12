import type { Manual } from './common';

export const accountsManual: Manual = {
  roleKey: 'accounts',
  roleLabel: 'Accounts',
  tagline: 'Review invoices, record payments, and manage accounting documents.',
  overview:
    'Accounts can access project details, official daily reports, documents, and Finance across the company. Use the project-scoped Dashboard for activity in assigned projects and Finance for invoices and payments.',
  permissions: [
    'Scoped dashboard',
    'View company project details',
    'View official daily reports across the company',
    'View and manage documents',
    'Create and correct eligible invoices, reject eligible submissions, and record payments'
  ],
  limitations: [
    'Cannot submit or approve reports',
    'Cannot manage users',
    'Materials and supplier management are outside Accounts access',
    'Company Analytics and Launch readiness are management pages',
    'Cannot access audit logs',
    'Invoice approval requires an eligible Admin or Operation Manager'
  ],
  sections: [
    {
      id: 'dashboard',
      title: 'Your Dashboard',
      icon: '🏠',
      content:
        'Your dashboard shows activity and report and document counts for assigned projects, plus your unread alerts. Use Finance for the invoice register and project budgets.',
      tips: [
        'Use your dashboard as a starting point each morning to check for new financial entries or document uploads that require your review.'
      ]
    },
    {
      id: 'finance',
      title: 'Accessing Financial Data',
      icon: '💰',
      content:
        'The Finance page shows the invoice register, project budget comparison, and recorded payments.',
      steps: [
        { step: 1, action: 'Go to Finance', detail: 'Click "Finance" in the sidebar.' },
        {
          step: 2,
          action: 'Select a project',
          detail:
            'Choose Project filter to show the project budget, billable invoices, and recorded payments.'
        },
        {
          step: 3,
          action: 'Enter an invoice',
          detail:
            'Choose New invoice and complete the project, invoice dates and amounts, and supplier if applicable. Select Submit invoice.'
        },
        {
          step: 4,
          action: 'View supplier invoices',
          detail:
            'Open the invoice number to review its status, attachment, and payments. Use Correct invoice and Resubmit invoice when an unpaid rejected invoice is eligible.'
        },
        {
          step: 5,
          action: 'Record a payment',
          detail:
            'On an approved invoice, use Record payment and enter an amount within the outstanding balance.'
        }
      ],
      tips: [
        'Use Invoice status filter to find submitted, approved, or rejected invoices.',
        'If you find a discrepancy, raise it with the Store Keeper or Project Manager.'
      ],
      diagram: `
Invoice workflow:
[Submit invoice] → [Eligible manager decides]
                       ├─ [Approved] → [Record payment]
                       └─ [Rejected] → [Correct and resubmit if unpaid]
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
            'Enter the title and document type, choose the project or company-wide scope, select the file, and choose Upload.'
        },
        {
          step: 4,
          action: 'Download or verify',
          detail: 'Use Preview or Download on the document card for the active approved version.'
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
        'Review official daily reports across the company. Use Supervisor updates to inspect submitted and verified field updates.',
      steps: [
        {
          step: 1,
          action: 'Go to Reports',
          detail: 'Click "Reports" in the sidebar (takes you to Daily Reports).'
        },
        {
          step: 2,
          action: 'Browse the report list',
          detail: 'Read the report card and check the status and recorded work.'
        },
        {
          step: 3,
          action: 'Download the approved report',
          detail: 'Use Download PDF on an approved report card to review the full record.'
        },
        {
          step: 4,
          action: 'Cross-reference with finance',
          detail:
            'Review the invoice and report evidence together when reconciling project records.'
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
          detail:
            'Choose a project name for its Overview, Team, and Timeline. Use Finance for the budget comparison.'
        }
      ]
    }
  ]
};
