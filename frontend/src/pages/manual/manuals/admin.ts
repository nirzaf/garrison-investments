import type { Manual } from './common';

export const adminManual: Manual = {
  roleKey: 'admin',
  roleLabel: 'Admin',
  tagline: 'Full platform control — you can see and do everything.',
  overview:
    'As an Admin, you have unrestricted access to every feature in the Garrisons portal. You are responsible for managing users, overseeing all projects, reviewing audit trails, approving reports, and maintaining the overall health of the system. Your role is the control centre of the entire platform.',
  permissions: [
    'Manage and view all users',
    'Create, manage, and view all projects',
    'Access the full company-wide dashboard',
    'View and approve all reports',
    'Submit reports',
    'Manage and view all inventory',
    'Manage suppliers',
    'View and manage all documents',
    'Access all financial data',
    'View audit logs and security events',
    'Access analytics and delivery planning',
    'Import users in bulk'
  ],
  limitations: [],
  sections: [
    {
      id: 'user-management',
      title: 'Managing Users',
      icon: '👥',
      content:
        'You can create, edit, and manage all user accounts. Go to Users → Admin → Users from the sidebar.',
      steps: [
        {
          step: 1,
          action: 'Navigate to Users',
          detail: 'Click "Users" in the sidebar under the Admin section.'
        },
        {
          step: 2,
          action: 'View all users',
          detail: 'You will see a table of all registered users with their roles and statuses.'
        },
        {
          step: 3,
          action: 'Create a new user',
          detail:
            'Click the "Add User" button, fill in the full name, email, and assign a role, then save.'
        },
        {
          step: 4,
          action: 'Edit or deactivate',
          detail:
            'Click on a user row to edit their details or change their role. Deactivate accounts when staff leave.'
        }
      ],
      tips: [
        "Always assign the least-privileged role appropriate to the user's responsibilities.",
        'Use the Imports page to bulk-create multiple users from a CSV file.',
        'Deactivate (do not delete) accounts when users leave — this preserves audit history.'
      ]
    },
    {
      id: 'import-users',
      title: 'Bulk Import Users',
      icon: '📥',
      content: 'Use the Import page to create many users at once from a structured file.',
      steps: [
        { step: 1, action: 'Navigate to Imports', detail: 'Click "Imports" in the sidebar.' },
        {
          step: 2,
          action: 'Prepare your file',
          detail:
            'Download the sample CSV template and fill in the required columns: full_name, email, role.'
        },
        {
          step: 3,
          action: 'Upload and review',
          detail:
            'Upload the completed CSV. Review any validation errors shown on screen before confirming.'
        },
        {
          step: 4,
          action: 'Confirm import',
          detail: 'Click "Import" to create the accounts. Users will receive credentials by email.'
        }
      ],
      tips: ['Double-check email addresses before importing — they are used for login.']
    },
    {
      id: 'projects',
      title: 'Managing Projects',
      icon: '🏗️',
      content:
        'Create and manage all projects in the system. Projects scope the data that other roles (engineers, supervisors) see.',
      steps: [
        { step: 1, action: 'Go to Projects', detail: 'Click "Projects" in the sidebar.' },
        {
          step: 2,
          action: 'Create a project',
          detail: 'Click "New Project", fill in the project name, location, and assigned staff.'
        },
        {
          step: 3,
          action: 'Assign team members',
          detail:
            'Add engineers, supervisors, and a project manager to each project so they get scoped data access.'
        },
        {
          step: 4,
          action: 'Monitor progress',
          detail:
            'Use the project detail page to see submitted reports, approved records, and financials.'
        }
      ]
    },
    {
      id: 'approvals',
      title: 'Approving Reports',
      icon: '✅',
      content:
        'Review and approve or reject daily reports and supervisor updates submitted by field staff.',
      steps: [
        { step: 1, action: 'Go to Approvals', detail: 'Click "Approvals" in the sidebar.' },
        {
          step: 2,
          action: 'Review pending items',
          detail:
            'You will see a list of reports awaiting your decision. Click a report to open it.'
        },
        {
          step: 3,
          action: 'Read the report',
          detail: 'Review the description, quantities, photos, and any notes from the submitter.'
        },
        {
          step: 4,
          action: 'Approve or reject',
          detail:
            'Click "Approve" to accept the report or "Reject" with a reason. Submitters are notified automatically.'
        }
      ],
      tips: [
        'Check photos carefully before approving material deliveries.',
        'Rejected reports can be resubmitted by the original engineer after corrections.'
      ]
    },
    {
      id: 'audit',
      title: 'Audit Logs & Security',
      icon: '🔍',
      content:
        'Review a complete audit trail of all actions taken in the portal for compliance and investigation.',
      steps: [
        { step: 1, action: 'Go to Audit', detail: 'Click "Audit" in the sidebar.' },
        {
          step: 2,
          action: 'Filter events',
          detail: 'Use date range, user, or action type filters to narrow down the audit log.'
        },
        {
          step: 3,
          action: 'Investigate anomalies',
          detail:
            'Look for unexpected actions like bulk deletions, login failures, or out-of-hours access.'
        }
      ],
      tips: [
        'Review audit logs monthly as a standard security practice.',
        'The Security page shows security-specific events for a focused view.'
      ]
    },
    {
      id: 'analytics',
      title: 'Analytics and launch readiness',
      icon: '📊',
      content:
        'Access company-wide analytics and delivery schedule planning, available exclusively to high-level management roles.',
      steps: [
        {
          step: 1,
          action: 'Click Analytics',
          detail: 'Select "Analytics" from the sidebar. This page shows company-wide KPI charts.'
        },
        {
          step: 2,
          action: 'Open Launch readiness',
          detail: 'Review the deployment, recovery, and user acceptance checks for a release.'
        }
      ]
    },
    {
      id: 'finance',
      title: 'Finance Overview',
      icon: '💰',
      content:
        'Access the finance page to view financial records, supplier invoices, and project cost breakdowns.',
      steps: [
        { step: 1, action: 'Go to Finance', detail: 'Click "Finance" in the sidebar.' },
        {
          step: 2,
          action: 'Filter by project',
          detail: 'Use the dropdown or filter options to view financials for a specific project.'
        },
        {
          step: 3,
          action: 'Export if needed',
          detail: 'Use the export button to download financial summaries for external reporting.'
        }
      ]
    }
  ]
};
