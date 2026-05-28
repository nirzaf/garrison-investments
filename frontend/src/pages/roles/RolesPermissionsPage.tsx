import { BookOpen, Check, Minus } from 'lucide-react';

import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';

const PERMISSIONS = [
  'users:manage',
  'users:read',
  'projects:manage',
  'projects:read',
  'audit:view',
  'dashboard:company',
  'dashboard:scoped',
  'reports:view',
  'reports:submit',
  'reports:approve',
  'inventory:view',
  'inventory:manage',
  'suppliers:manage',
  'documents:view',
  'documents:manage',
  'financial:view',
] as const;

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
  'financial:view': 'View Finance',
};

const ROLES: { key: string; label: string; description: string; permissions: string[] }[] = [
  {
    key: 'admin',
    label: 'Admin',
    description: 'Platform administrator with full access to all features and settings.',
    permissions: [...PERMISSIONS],
  },
  {
    key: 'general_manager',
    label: 'General Manager',
    description: 'Senior company-wide manager with operational visibility across all projects.',
    permissions: [
      'users:read', 'projects:read', 'projects:manage', 'dashboard:company',
      'reports:view', 'reports:approve', 'inventory:view', 'suppliers:manage',
      'documents:view', 'documents:manage', 'financial:view',
    ],
  },
  {
    key: 'operation_manager',
    label: 'Operation Manager',
    description: 'Operations manager with company-wide visibility and approval authority.',
    permissions: [
      'users:read', 'projects:read', 'projects:manage', 'dashboard:company',
      'reports:view', 'reports:approve', 'inventory:view', 'suppliers:manage',
      'documents:view', 'documents:manage', 'financial:view',
    ],
  },
  {
    key: 'project_manager',
    label: 'Project Manager',
    description: 'Project-level manager with scoped dashboard, approvals, and document access.',
    permissions: [
      'dashboard:scoped', 'projects:read', 'reports:view', 'reports:approve',
      'inventory:view', 'documents:view', 'documents:manage', 'financial:view',
    ],
  },
  {
    key: 'civil_engineer',
    label: 'Civil Engineer',
    description: 'Site engineer who can submit reports and work with project-scoped features.',
    permissions: [
      'dashboard:scoped', 'projects:read', 'reports:view', 'reports:submit',
      'inventory:view', 'documents:view', 'documents:manage',
    ],
  },
  {
    key: 'civil_supervisor',
    label: 'Civil Supervisor',
    description: 'Site supervisor who can submit updates and use project-scoped reporting.',
    permissions: [
      'dashboard:scoped', 'projects:read', 'reports:view', 'reports:submit',
      'documents:view',
    ],
  },
  {
    key: 'store_keeper',
    label: 'Store Keeper',
    description: 'Inventory and stores operator with supplier management access.',
    permissions: [
      'dashboard:scoped', 'inventory:view', 'inventory:manage', 'suppliers:manage',
    ],
  },
  {
    key: 'accounts',
    label: 'Accounts',
    description: 'Finance and accounting user with document and financial visibility.',
    permissions: [
      'dashboard:scoped', 'projects:read', 'reports:view', 'documents:view',
      'documents:manage', 'financial:view',
    ],
  },
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
                  role.key === currentRole
                    ? 'bg-brand-50 text-brand-700'
                    : 'text-theme-text-muted'
                }`}
                key={role.key}
              >
                <span className="block">{role.label}</span>
                {role.key === currentRole && (
                  <StatusBadge tone="info">Your Role</StatusBadge>
                )}
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
                    className={`p-3 text-center ${
                      role.key === currentRole ? 'bg-brand-50' : ''
                    }`}
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

function RoleCard({
  role,
  isCurrent,
}: {
  role: (typeof ROLES)[number];
  isCurrent: boolean;
}) {
  const denied = PERMISSIONS.filter((p) => !role.permissions.includes(p));

  return (
    <div
      className={`rounded-lg border bg-theme-card p-5 shadow-sm ${
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

      {user && (
        <div className="rounded-lg border-l-4 border-brand-500 bg-brand-50/50 p-5">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium text-theme-text-secondary">Your role:</span>
            <StatusBadge tone="info">{roleLabel(currentRole)}</StatusBadge>
          </div>
          <p className="mt-2 text-sm text-theme-text-secondary">
            You have <span className="font-semibold text-theme-text-primary">{user.permissions?.length ?? 0}</span> of{' '}
            {PERMISSIONS.length} permissions.
          </p>
        </div>
      )}

      <section>
        <h3 className="mb-3 text-lg font-semibold text-theme-text-primary">Permission Matrix</h3>
        <div className="rounded-lg border border-theme-border bg-theme-card shadow-sm">
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
    </div>
  );
}
