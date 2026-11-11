import type { Manual } from './common';

export const operationManagerManual: Manual = {
  roleKey: 'operation_manager',
  roleLabel: 'Operation Manager',
  tagline: 'Operations control — approve, oversee, and keep projects moving.',
  overview:
    'As Operation Manager, you share the same broad access as the General Manager. You can view all projects, approve field reports, manage documents, monitor inventory, and handle financial overviews. Your focus is on the day-to-day operational efficiency of all active projects.',
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
        'Your dashboard shows operations data across all projects: pending approvals, material consumption, report volumes, and delivery schedules.',
      tips: [
        'Check pending approvals every morning — field teams depend on timely responses to keep work moving.'
      ]
    },
    {
      id: 'approvals',
      title: 'Approving Reports',
      icon: '✅',
      content:
        'This is likely your highest-frequency task. Engineers and supervisors submit daily reports; you review and approve or reject them.',
      steps: [
        { step: 1, action: 'Go to Approvals', detail: 'Click "Approvals" in the sidebar.' },
        {
          step: 2,
          action: 'View pending items',
          detail: 'All pending reports are listed. The most recent are typically at the top.'
        },
        {
          step: 3,
          action: 'Open and review',
          detail:
            'Click a report. Review the description, activity log, quantities, and any attached photos.'
        },
        {
          step: 4,
          action: 'Approve or reject',
          detail:
            'Click "Approve" if everything looks correct. If there are issues, click "Reject" and provide a clear reason so the engineer can correct and resubmit.'
        }
      ],
      tips: [
        'Always review photos before approving material deliveries — discrepancies in quantity are common.',
        'If a report is incomplete, reject with specific feedback rather than leaving it pending.'
      ],
      diagram: `
Report Approval Flow:
[Engineer submits] ──→ [Pending in Approvals inbox]
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
          detail: 'Click on a project to view its daily report history, team, and status.'
        },
        {
          step: 3,
          action: 'Monitor report health',
          detail:
            'Look for projects with no recent report submissions — this may indicate a site issue.'
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
          detail: 'See the inventory list with current quantities, units, and associated projects.'
        },
        {
          step: 3,
          action: 'Review consumption trends',
          detail: 'Use filters to identify which projects are consuming materials at a high rate.'
        }
      ]
    },
    {
      id: 'analytics',
      title: 'Analytics & Delivery',
      icon: '📊',
      content: 'Use analytics to identify performance trends and manage delivery schedules.',
      steps: [
        {
          step: 1,
          action: 'Go to Analytics',
          detail: 'Click "Analytics" for operational charts and trends.'
        },
        {
          step: 2,
          action: 'Go to Delivery',
          detail: 'Click "Delivery" to view and coordinate material delivery plans.'
        }
      ]
    },
    {
      id: 'finance',
      title: 'Finance',
      icon: '💰',
      content: 'Access project financials and supplier cost data.',
      steps: [
        { step: 1, action: 'Go to Finance', detail: 'Click "Finance" in the sidebar.' },
        {
          step: 2,
          action: 'Review project costs',
          detail: 'Filter by project to see cost summaries and identify budget overruns.'
        }
      ]
    }
  ]
};
