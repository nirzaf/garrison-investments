import { BookOpen, Check, Minus } from 'lucide-react';
import { useState } from 'react';

import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';

import rolePermissions from './rolePermissions.json';

const PERMISSIONS = rolePermissions.permissions;

const PERMISSION_LABELS: Record<string, string> = {
  'users:manage': 'Manage Users',
  'users:read': 'View Users',
  'projects:manage': 'Manage Projects',
  'projects:read': 'View Projects',
  'audit:view': 'View Audit Logs',
  'dashboard:company': 'Company Dashboard',
  'dashboard:scoped': 'Scoped Dashboard',
  'reports:view': 'View Reports',
  'reports:submit': 'Submit Reports',
  'reports:approve': 'Approve Reports',
  'inventory:view': 'View Inventory',
  'inventory:manage': 'Manage Inventory',
  'suppliers:manage': 'Manage Suppliers',
  'documents:view': 'View Documents',
  'documents:manage': 'Manage Documents',
  'financial:view': 'View Finance'
};

const ROLES: { key: string; label: string; description: string; permissions: string[] }[] = [
  {
    key: 'admin',
    label: 'Admin',
    description: 'Platform administrator with full access to all features and settings.',
    permissions: rolePermissions.roles.admin
  },
  {
    key: 'general_manager',
    label: 'General Manager',
    description: 'Senior company-wide manager with operational visibility across all projects.',
    permissions: rolePermissions.roles.general_manager
  },
  {
    key: 'operation_manager',
    label: 'Operation Manager',
    description: 'Operations manager with company-wide visibility and approval authority.',
    permissions: rolePermissions.roles.operation_manager
  },
  {
    key: 'project_manager',
    label: 'Project Manager',
    description: 'Project-level manager with scoped dashboard, approvals, and document access.',
    permissions: rolePermissions.roles.project_manager
  },
  {
    key: 'civil_engineer',
    label: 'Civil Engineer',
    description: 'Site engineer who can submit reports and work with project-scoped features.',
    permissions: rolePermissions.roles.civil_engineer
  },
  {
    key: 'civil_supervisor',
    label: 'Civil Supervisor',
    description: 'Site supervisor who can submit updates and use project-scoped reporting.',
    permissions: rolePermissions.roles.civil_supervisor
  },
  {
    key: 'store_keeper',
    label: 'Store Keeper',
    description: 'Inventory and stores operator with supplier management access.',
    permissions: rolePermissions.roles.store_keeper
  },
  {
    key: 'accounts',
    label: 'Accounts',
    description: 'Finance and accounting user with document and financial visibility.',
    permissions: rolePermissions.roles.accounts
  }
];

function roleLabel(role: string) {
  return role
    .split('_')
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(' ');
}

function PermissionMatrix({ currentRole }: { currentRole: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[800px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-theme-border">
            <th className="sticky left-0 z-10 bg-theme-card p-3 text-left text-xs font-semibold uppercase text-theme-text-muted">
              Permission
            </th>
            {ROLES.map((role) => (
              <th
                className={`p-3 text-center text-xs font-semibold ${
                  role.key === currentRole ? 'bg-brand-50 text-brand-700' : 'text-theme-text-muted'
                }`}
                key={role.key}
              >
                <span className="block">{role.label}</span>
                {role.key === currentRole && <StatusBadge tone="info">Your Role</StatusBadge>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {PERMISSIONS.map((permission) => (
            <tr className="border-b border-theme-border" key={permission}>
              <td className="sticky left-0 z-10 bg-theme-card p-3 text-sm font-medium text-theme-text-primary">
                {PERMISSION_LABELS[permission] ?? permission}
              </td>
              {ROLES.map((role) => {
                const has = role.permissions.includes(permission);
                return (
                  <td
                    className={`p-3 text-center ${role.key === currentRole ? 'bg-brand-50' : ''}`}
                    key={role.key}
                  >
                    {has ? (
                      <Check className="mx-auto h-5 w-5 text-green-600" />
                    ) : (
                      <Minus className="mx-auto h-5 w-5 text-theme-text-muted" />
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RoleCard({ role, isCurrent }: { role: (typeof ROLES)[number]; isCurrent: boolean }) {
  const denied = PERMISSIONS.filter((p) => !role.permissions.includes(p));

  return (
    <div
      className={`rounded-lg border bg-theme-card p-5 shadow-xs ${
        isCurrent ? 'border-brand-500 ring-2 ring-brand-500' : 'border-theme-border'
      }`}
    >
      <div className="flex items-center gap-2">
        <h3 className="text-lg font-semibold text-theme-text-primary">{role.label}</h3>
        {isCurrent && <StatusBadge tone="info">Your Role</StatusBadge>}
      </div>
      <p className="mt-1 text-sm text-theme-text-secondary">{role.description}</p>

      <div className="mt-4">
        <p className="text-xs font-semibold uppercase text-theme-text-muted">Can do</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {role.permissions.map((p) => (
            <span
              className="rounded-full border border-green-200 bg-green-50 px-2.5 py-0.5 text-xs font-medium text-green-700"
              key={p}
            >
              {PERMISSION_LABELS[p] ?? p}
            </span>
          ))}
        </div>
      </div>

      {denied.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase text-theme-text-muted">Cannot do</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {denied.map((p) => (
              <span
                className="rounded-full border border-theme-border bg-theme-card-elevated px-2.5 py-0.5 text-xs text-theme-text-muted line-through"
                key={p}
              >
                {PERMISSION_LABELS[p] ?? p}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function RolesPermissionsPage() {
  const { user } = useAuth();
  const currentRole = user?.role ?? '';
  const [tab, setTab] = useState<'matrix' | 'docs'>('matrix');

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-brand-600" />
          <p className="text-sm font-medium text-brand-600">Documentation</p>
        </div>
        <h2 className="mt-1 text-2xl font-semibold text-theme-text-primary">
          Roles &amp; Permissions
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-theme-text-secondary">
          This page documents the access control model used in the Garrisons portal. Each user has
          one role, and each role grants a fixed set of permissions that determine which features
          and data you can access.
        </p>
      </div>

      <div className="flex gap-1 border-b border-theme-border">
        {(['matrix', 'docs'] as const).map((t) => (
          <button
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? 'border-b-2 border-brand-600 text-brand-600'
                : 'text-theme-text-secondary hover:text-theme-text-primary'
            }`}
            key={t}
            onClick={() => setTab(t)}
            type="button"
          >
            {t === 'matrix' ? 'Permission Matrix' : 'Full Documentation'}
          </button>
        ))}
      </div>

      {tab === 'matrix' && (
        <>
          {user && (
            <div className="rounded-lg border-l-4 border-brand-500 bg-brand-50/50 p-5">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-sm font-medium text-theme-text-secondary">Your role:</span>
                <StatusBadge tone="info">{roleLabel(currentRole)}</StatusBadge>
              </div>
              <p className="mt-2 text-sm text-theme-text-secondary">
                You have{' '}
                <span className="font-semibold text-theme-text-primary">
                  {user.permissions?.length ?? 0}
                </span>{' '}
                of {PERMISSIONS.length} permissions.
              </p>
            </div>
          )}

          <section>
            <h3 className="mb-3 text-lg font-semibold text-theme-text-primary">
              Permission Matrix
            </h3>
            <div className="rounded-lg border border-theme-border bg-theme-card shadow-xs">
              <PermissionMatrix currentRole={currentRole} />
            </div>
          </section>

          <section>
            <h3 className="mb-3 text-lg font-semibold text-theme-text-primary">Role Details</h3>
            <div className="grid gap-4 md:grid-cols-2">
              {ROLES.map((role) => (
                <RoleCard isCurrent={role.key === currentRole} key={role.key} role={role} />
              ))}
            </div>
          </section>
        </>
      )}

      {tab === 'docs' && <RolesDocumentation />}
    </div>
  );
}

function DocSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-base font-semibold text-theme-text-primary">{title}</h3>
      {children}
    </section>
  );
}

function DocTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-theme-border">
      <table className="min-w-full divide-y divide-theme-border text-sm">
        <thead className="bg-theme-main">
          <tr>
            {headers.map((h) => (
              <th
                className="px-4 py-2 text-left text-xs font-semibold uppercase text-theme-text-muted"
                key={h}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-theme-border bg-theme-card">
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td className="px-4 py-2 text-theme-text-secondary" key={j}>
                  {cell === 'Y' ? (
                    <Check className="h-4 w-4 text-green-600" />
                  ) : cell === '-' ? (
                    <Minus className="h-4 w-4 text-theme-text-muted" />
                  ) : (
                    <code className="rounded bg-theme-card-elevated px-1 py-0.5 text-xs text-brand-600">
                      {cell}
                    </code>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RolesDocumentation() {
  return (
    <div className="space-y-8 text-sm text-theme-text-secondary">
      <DocSection title="How Access Control Works">
        <p>The portal uses role-based access control (RBAC) with permission strings.</p>
        <ul className="list-inside list-disc space-y-1">
          <li>Each user has exactly one role.</li>
          <li>Each role maps to a fixed set of permissions.</li>
          <li>
            Backend APIs enforce authorization using{' '}
            <code className="rounded bg-theme-card-elevated px-1 text-xs text-brand-600">
              require_permission(...)
            </code>
            .
          </li>
          <li>
            The frontend uses the permissions array on the authenticated user to control visible
            routes and nav items.
          </li>
          <li>
            Dashboard, reports, and approvals also apply service-layer data scoping in addition to
            permission checks.
          </li>
        </ul>
      </DocSection>

      <DocSection title="Common Authenticated Experience">
        <p>All authenticated users have access to these baseline features regardless of role:</p>
        <ul className="list-inside list-disc space-y-1">
          <li>Sign in and refresh session tokens</li>
          <li>Change password</li>
          <li>View profile</li>
          <li>Open the dashboard</li>
          <li>View notifications</li>
        </ul>
        <p className="mt-2 rounded-md border border-theme-border bg-theme-card-elevated p-3">
          The dashboard route is not permission-gated on the frontend. The backend scopes returned
          data — company-wide for <code className="text-xs text-brand-600">admin</code>,{' '}
          <code className="text-xs text-brand-600">general_manager</code>,{' '}
          <code className="text-xs text-brand-600">operation_manager</code>, and scoped for all
          other roles.
        </p>
      </DocSection>

      <DocSection title="Implemented Roles">
        <DocTable
          headers={['Role Key', 'Plain-English Meaning', 'Notes']}
          rows={[
            ['admin', 'Platform administrator', 'Full permission set in code'],
            [
              'general_manager',
              'Senior company-wide manager',
              'Company-wide operational visibility; same permission set as operation manager in current code'
            ],
            [
              'operation_manager',
              'Operations manager',
              'Company-wide operational visibility and approvals'
            ],
            [
              'project_manager',
              'Project-level manager',
              'Scoped dashboard plus project, approvals, finance, and document access'
            ],
            [
              'civil_engineer',
              'Site engineer',
              'Can submit reports and work with project-scoped operational features'
            ],
            [
              'civil_supervisor',
              'Site supervisor',
              'Can submit supervisor updates and use project-scoped reporting features'
            ],
            [
              'store_keeper',
              'Inventory and stores operator',
              'Inventory-heavy role with supplier access'
            ],
            [
              'accounts',
              'Finance and accounting user',
              'Finance, documents, and scoped reporting visibility'
            ]
          ]}
        />
      </DocSection>

      <DocSection title="Permission Glossary">
        <DocTable
          headers={['Permission', 'Meaning']}
          rows={[
            ['users:manage', 'Create and manage users; also gates the imports screen'],
            ['users:read', 'Read user-management data'],
            ['projects:manage', 'Create or manage projects and project UI controls'],
            ['projects:read', 'View project data and access project-related screens'],
            ['audit:view', 'Access audit and security-oriented monitoring screens'],
            [
              'dashboard:company',
              'Company-wide management features — analytics and delivery planning'
            ],
            ['dashboard:scoped', 'Scoped dashboard access for non-company-wide roles'],
            ['reports:view', 'View reporting content such as photos and report visibility flows'],
            ['reports:submit', 'Submit daily reports or supervisor updates'],
            ['reports:approve', 'Approve report workflows and access the approvals inbox'],
            ['inventory:view', 'View inventory and materials pages'],
            ['inventory:manage', 'Manage inventory operations'],
            ['suppliers:manage', 'Manage supplier records and supplier TDS document flows'],
            ['documents:manage', 'Access document management features'],
            ['financial:view', 'Access finance features']
          ]}
        />
      </DocSection>

      <DocSection title="Role-Permission Matrix">
        <div className="overflow-x-auto rounded-lg border border-theme-border">
          <table className="min-w-full divide-y divide-theme-border text-xs">
            <thead className="bg-theme-main">
              <tr>
                <th className="sticky left-0 z-10 bg-theme-main px-3 py-2 text-left font-semibold uppercase text-theme-text-muted">
                  Permission
                </th>
                {ROLES.map((r) => (
                  <th
                    className="px-3 py-2 text-center font-semibold uppercase text-theme-text-muted"
                    key={r.key}
                  >
                    {r.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-theme-border bg-theme-card">
              {PERMISSIONS.map((perm) => (
                <tr key={perm}>
                  <td className="sticky left-0 z-10 bg-theme-card px-3 py-2 font-medium text-theme-text-primary">
                    <code className="text-xs text-brand-600">{perm}</code>
                  </td>
                  {ROLES.map((r) => (
                    <td className="px-3 py-2 text-center" key={r.key}>
                      {r.permissions.includes(perm) ? (
                        <Check className="mx-auto h-4 w-4 text-green-600" />
                      ) : (
                        <Minus className="mx-auto h-4 w-4 text-theme-text-muted" />
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DocSection>

      <DocSection title="Route-Level Access">
        <DocTable
          headers={['Route', 'Permission Required', 'Notes']}
          rows={[
            ['/dashboard', 'None', 'Always reachable; backend scopes returned data'],
            ['/profile', 'None', 'Authenticated baseline'],
            ['/change-password', 'None', 'Authenticated baseline'],
            ['/notifications', 'None', 'Authenticated baseline'],
            ['/projects', 'projects:read', 'Project list and detail workflows'],
            ['/admin/users', 'users:read', 'User management screen'],
            ['/admin/audit-logs', 'audit:view', 'Audit log screen'],
            ['/admin/imports', 'users:manage', 'Imports administration'],
            ['/documents', 'documents:view', 'Document library and permitted files'],
            ['/photos', 'reports:view', 'Photo / report evidence view'],
            ['/materials', 'inventory:view', 'Inventory and materials page'],
            ['/suppliers', 'suppliers:manage', 'Supplier register and TDS files'],
            ['/finance', 'financial:view', 'Finance page'],
            ['/analytics', 'dashboard:company', 'Management analytics'],
            ['/security', 'audit:view', 'Security page'],
            ['/delivery', 'dashboard:company', 'Launch readiness checklist'],
            ['/reports/daily', 'reports:view', 'Daily report list and permitted actions'],
            [
              '/reports/supervisor-update',
              'reports:view',
              'Site update review and supervisor authoring'
            ],
            [
              '/approvals',
              'Signed in',
              'Own outbox. Inbox and daily-report approvals require reports:approve.'
            ]
          ]}
        />
      </DocSection>

      <DocSection title="Navigation Special Behavior">
        <ul className="list-inside list-disc space-y-1">
          <li>
            The Reports nav item points to{' '}
            <code className="text-xs text-brand-600">/reports/supervisor-update</code> when the user
            role is <code className="text-xs text-brand-600">civil_supervisor</code>; all other
            roles with reporting access go to{' '}
            <code className="text-xs text-brand-600">/reports/daily</code>.
          </li>
          <li>
            Users with <code className="text-xs text-brand-600">dashboard:company</code> permission
            see the <strong>Analytics</strong> and <strong>Launch readiness</strong> tabs in the
            main navigation.
          </li>
        </ul>
      </DocSection>

      <DocSection title="Functional Access By Business Area">
        <DocTable
          headers={['Business Area', 'Primary Permission', 'Outcome']}
          rows={[
            [
              'User administration',
              'users:manage / users:read',
              'Read or manage users depending on permission'
            ],
            [
              'Project portfolio',
              'projects:read / projects:manage',
              'View projects; management controls enabled for projects:manage'
            ],
            [
              'Dashboard',
              'dashboard:company / dashboard:scoped',
              'Company-wide or scoped visibility. The company permission also opens Analytics and Launch readiness.'
            ],
            ['Daily reports', 'reports:submit', 'Submit daily reports or supervisor updates'],
            [
              'Approvals',
              'Signed in / reports:approve',
              'Own submitted requests and permitted approval inboxes'
            ],
            ['Report evidence', 'reports:view', 'Photos and report-adjacent content'],
            [
              'Inventory and materials',
              'inventory:view / inventory:manage',
              'View materials page and manage inventory operations'
            ],
            ['Suppliers', 'suppliers:manage', 'Supplier register and TDS upload or download'],
            [
              'Documents',
              'documents:view / documents:manage',
              'Read or manage documents within the assigned scope'
            ],
            ['Finance', 'financial:view', 'Finance page and financial reporting'],
            ['Imports', 'users:manage', 'Import administration'],
            ['Audit and security', 'audit:view', 'Audit logs and security page'],
            [
              'Analytics and launch readiness',
              'dashboard:company',
              'Management analytics and release verification checklist'
            ]
          ]}
        />
      </DocSection>

      <DocSection title="Caveats">
        <ul className="list-inside list-disc space-y-1">
          <li>
            <strong>General Manager</strong> and <strong>Operation Manager</strong> have identical
            permission sets in the current code.
          </li>
          <li>
            Dashboard authorization is service-scoped, not route-decorated — all authenticated users
            can open <code className="text-xs text-brand-600">/dashboard</code>.
          </li>
          <li>
            Reports and approvals apply additional service-layer checks beyond the permission flags
            (engineer-only submission, project membership, admin override).
          </li>
          <li>
            The Suppliers page and TDS file access require <code>suppliers:manage</code>.
          </li>
          <li>
            Accounts can read reports, documents, and finance data across the company. Project
            Managers are scoped to assigned projects for those workflows. Inventory reads use
            company-wide visibility for roles with <code>inventory:view</code>.
          </li>
        </ul>
      </DocSection>
    </div>
  );
}
