import type { Manual } from './common';

export const operationManagerManual: Manual = {
  roleKey: 'operation_manager',
  roleLabel: 'Operation Manager',
  tagline: 'Operations control — approve, oversee, and keep projects moving.',
  overview:
    'Operation Manager can manage projects, decide submitted daily reports and eligible invoices, approve document versions, and monitor inventory and supplier compliance.',
  permissions: [
    'View all users',
    'View and manage all projects',
    'Access the full company-wide dashboard',
    'View and decide submitted official daily reports',
    'View stock and material requests across the company',
    'Manage suppliers',
    'View and manage all documents',
    'Access finance and decide eligible invoices',
    'Access analytics and launch readiness'
  ],
  limitations: [
    'Cannot create or deactivate user accounts (Admin only)',
    'Cannot access audit logs or security events',
    'Cannot bulk-import users',
    'Stock receipts, reservation, and issue require inventory management permission',
    'Invoice approval excludes the original creator and current approval submitter'
  ],
  sections: [
    {
      id: 'dashboard',
      title: 'Your Dashboard',
      icon: '🏠',
      content:
        'Your dashboard shows company-wide active projects, pending and approved reports, and pending documents, along with recent activity and your unread alerts.',
      tips: [
        'Check pending approvals every morning — field teams depend on timely responses to keep work moving.'
      ]
    },
    {
      id: 'approvals',
      title: 'Approving Reports',
      icon: '✅',
      content:
        'Review official daily reports from engineers. Linked supervisor updates are available as evidence after the engineer submits the report.',
      steps: [
        { step: 1, action: 'Go to Approvals', detail: 'Click "Approvals" in the sidebar.' },
        {
          step: 2,
          action: 'View pending items',
          detail: 'Open Report approvals to find submitted daily reports.'
        },
        {
          step: 3,
          action: 'Open and review',
          detail: 'Review the report card, attachments, history, and linked supervisor evidence.'
        },
        {
          step: 4,
          action: 'Approve or reject',
          detail:
            'Confirm target coverage and choose Approve. To return the report to draft for correction, enter a reason and choose Reject.'
        }
      ],
      tips: [
        'Review attached photos and recorded quantities before deciding the report.',
        'If a report is incomplete, reject with specific feedback rather than leaving it pending.'
      ],
      diagram: `
Report Approval Flow:
[Engineer submits] ──→ [Submitted in Report approvals]
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
               [Approve]            [Reject + Reason]
                    │                   │
          [Report marked Approved]  [Engineer notified]
                    │                   │
           [Visible in Daily Reports]  [Engineer corrects & resubmits]
`
    },
    {
      id: 'projects',
      title: 'Projects Overview',
      icon: '🏗️',
      content: 'Track all active projects and their operational status.',
      steps: [
        { step: 1, action: 'Go to Projects', detail: 'Click "Projects" in the sidebar.' },
        {
          step: 2,
          action: 'Open a project',
          detail: 'Choose a project name to open its Overview, Team, and Timeline tabs.'
        },
        {
          step: 3,
          action: 'Maintain the project record',
          detail:
            'Use Overview to edit project details, Team for assignments, and Timeline to review and update tasks.'
        }
      ]
    },
    {
      id: 'inventory',
      title: 'Materials & Inventory',
      icon: '📦',
      content: 'Monitor material usage and inventory levels across all projects.',
      steps: [
        { step: 1, action: 'Go to Materials', detail: 'Click "Materials" in the sidebar.' },
        {
          step: 2,
          action: 'View current stock',
          detail:
            'Select an item to view its stock matrix by location, including On hand, Reserved, and Available.'
        },
        {
          step: 3,
          action: 'Review consumption trends',
          detail:
            'Use Analytics to review material usage trends or export a filtered material usage report.'
        }
      ]
    },
    {
      id: 'analytics',
      title: 'Analytics and launch readiness',
      icon: '📊',
      content:
        'Use Analytics to identify performance trends and Launch readiness to review release checks.',
      steps: [
        {
          step: 1,
          action: 'Go to Analytics',
          detail: 'Click "Analytics" for operational charts and trends.'
        },
        {
          step: 2,
          action: 'Open Launch readiness',
          detail: 'Review the operations guide and the release acceptance checks.'
        }
      ]
    },
    {
      id: 'finance',
      title: 'Finance',
      icon: '💰',
      content:
        'Review supplier invoices, their payments, and the comparison of project budget to billable invoices.',
      steps: [
        { step: 1, action: 'Go to Finance', detail: 'Click "Finance" in the sidebar.' },
        {
          step: 2,
          action: 'Review project budget',
          detail: 'Select a project to see budget, billable invoices, and recorded payments.'
        },
        {
          step: 3,
          action: 'Decide an invoice',
          detail:
            'Open the invoice number. Choose Approve invoice or Reject invoice when available and enter the reason for a rejection.'
        }
      ]
    }
  ]
};
