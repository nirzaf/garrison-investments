import type { Manual } from './common';

export const adminManual: Manual = {
  roleKey: 'admin',
  roleLabel: 'Admin',
  tagline: 'Manage accounts, oversee projects, and review audit and workflow activity.',
  overview:
    'Admin has company-wide oversight and manages accounts, projects, inventory, supplier records, document versions, imports, and audit records. Each workflow still applies its decision and record-state rules.',
  permissions: [
    'Manage and view all users',
    'Create, manage, and view all projects',
    'Access the full company-wide dashboard',
    'View and decide submitted official daily reports',
    'Submit official daily reports',
    'Manage and view all inventory',
    'Manage suppliers',
    'View and manage all documents',
    'Access all financial data',
    'View audit logs and security events',
    'Access analytics and launch readiness',
    'Import users in bulk'
  ],
  limitations: [
    'Use Profile to change your own password. Account management actions apply to other accounts.',
    'Completed and cancelled projects are read-only.',
    'Invoice approval excludes the original creator and current approval submitter.'
  ],
  sections: [
    {
      id: 'user-management',
      title: 'Managing Users',
      icon: '👥',
      content: 'Open Users from the sidebar to create accounts and manage other active users.',
      steps: [
        {
          step: 1,
          action: 'Navigate to Users',
          detail: 'Click Users in the sidebar.'
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
            'Complete the account form with the required details, role, and temporary password. Choose Create user.'
        },
        {
          step: 4,
          action: 'Maintain another account',
          detail:
            'Find the account by name or email. Choose Change role, Reset password, or Deactivate as appropriate.'
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
            'Choose users and download the Template. Complete its required fields, including email, full name, role, employee code, and temporary password.'
        },
        {
          step: 3,
          action: 'Upload and review',
          detail:
            'Select the completed CSV or XLSX file, choose Preview, and correct any validation errors.'
        },
        {
          step: 4,
          action: 'Confirm import',
          detail:
            'Choose Run import to create the accounts. Share temporary credentials through your approved account handover process.'
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
          detail:
            'Choose New project and enter the required project details and BOQ lines. Add milestones and link BOQ items as needed.'
        },
        {
          step: 3,
          action: 'Assign team members',
          detail:
            'Open the project and use Team to assign engineers, supervisors, and a project manager.'
        },
        {
          step: 4,
          action: 'Monitor progress',
          detail:
            'Use Overview for project details, milestones, and BOQ. Use Timeline for tasks, dates, and progress.'
        }
      ]
    },
    {
      id: 'approvals',
      title: 'Approving Reports',
      icon: '✅',
      content:
        'Review submitted official daily reports. An engineer verifies a linked supervisor update when submitting a report.',
      steps: [
        { step: 1, action: 'Go to Approvals', detail: 'Click "Approvals" in the sidebar.' },
        {
          step: 2,
          action: 'Review pending items',
          detail: 'Open Report approvals and find the submitted report card.'
        },
        {
          step: 3,
          action: 'Read the report',
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
        'Review the evidence attached to the report before recording a decision.',
        'Rejected reports can be resubmitted by the original engineer after corrections.'
      ]
    },
    {
      id: 'audit',
      title: 'Audit Logs & Security',
      icon: '🔍',
      content: 'Use recorded audit events and security activity to investigate portal changes.',
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
        'Access company-wide charts and exports. Use Launch readiness for deployment, recovery, and acceptance checks.',
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
        'Use Finance for invoices, payments, outstanding balances, and the project budget comparison.',
      steps: [
        { step: 1, action: 'Go to Finance', detail: 'Click "Finance" in the sidebar.' },
        {
          step: 2,
          action: 'Filter by project',
          detail: 'Use Project filter to show the project budget and billable invoice totals.'
        },
        {
          step: 3,
          action: 'Review invoice details',
          detail:
            'Open an invoice number to see its attachment, status, available actions, and payments.'
        }
      ]
    }
  ]
};
