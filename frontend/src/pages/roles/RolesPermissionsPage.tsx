import { BookOpen, Check, Minus } from 'lucide-react';
import { useState } from 'react';

import { StatusBadge } from '../../components/shared/StatusBadge';
import { useAuth } from '../../context/useAuth';

import rolePermissions from './rolePermissions.json';

const PERMISSIONS = rolePermissions.permissions;
const ROLE_LABELS: Record<string, string> = {
  managing_director: 'Managing Director',
  operations_director: 'Operations Director',
  group_project_manager: 'Group Project Manager',
  mep_project_manager: 'MEP Project Manager',
  quantity_surveyor: 'Quantity Surveyor',
  senior_site_supervisor: 'Senior Site Supervisor',
  site_supervisor: 'Site Supervisor',
  hr_manager: 'HR Manager',
  hr_executive: 'HR Executive',
  administrative_executive: 'Administrative Executive'
};
const PERMISSION_LABELS: Record<string, string> = {
  'users:manage': 'Manage users',
  'users:read': 'Read users',
  'projects:manage': 'Manage projects',
  'projects:read': 'Read projects',
  'audit:view': 'View audit records',
  'dashboard:company': 'Company dashboard',
  'dashboard:scoped': 'Scoped dashboard',
  'reports:view': 'View reports',
  'reports:submit': 'Submit reports',
  'reports:approve': 'Approve reports',
  'inventory:view': 'View inventory',
  'inventory:manage': 'Manage inventory',
  'suppliers:manage': 'Manage suppliers',
  'documents:view': 'View documents',
  'documents:manage': 'Manage documents',
  'financial:view': 'View financial information'
};

const ROLES = Object.entries(rolePermissions.roles).map(([key, permissions]) => ({
  key,
  label: ROLE_LABELS[key] ?? key,
  permissions
}));

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
                {role.key === currentRole ? <StatusBadge tone="info">Your Role</StatusBadge> : null}
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
                const granted = role.permissions.includes(permission);
                return (
                  <td className="p-3 text-center" key={role.key}>
                    {granted ? (
                      <Check aria-label="Granted" className="mx-auto h-4 w-4 text-green-600" />
                    ) : (
                      <Minus aria-label="Not granted" className="mx-auto h-4 w-4 text-theme-text-muted" />
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

export function RolesPermissionsPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<'matrix' | 'docs'>('matrix');
  const currentRole = user?.role ?? '';

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium text-brand-600">Access control</p>
        <h2 className="text-2xl font-semibold text-theme-text-primary">Roles &amp; permissions</h2>
      </div>

      <div className="flex gap-1 border-b border-theme-border">
        {(['matrix', 'docs'] as const).map((value) => (
          <button
            aria-current={tab === value ? 'page' : undefined}
            className={`flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium ${
              tab === value
                ? 'border-brand-600 text-brand-600'
                : 'border-transparent text-theme-text-secondary hover:text-theme-text-primary'
            }`}
            key={value}
            onClick={() => setTab(value)}
            type="button"
          >
            {value === 'matrix' ? <BookOpen aria-hidden="true" className="h-4 w-4" /> : null}
            {value === 'matrix' ? 'Permission Matrix' : 'Access Rules'}
          </button>
        ))}
      </div>

      {tab === 'matrix' ? (
        <>
          {user ? (
            <div className="rounded-lg border-l-4 border-brand-500 bg-brand-50/50 p-5">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-sm font-medium text-theme-text-secondary">Your role:</span>
                <StatusBadge tone="info">{ROLE_LABELS[currentRole] ?? 'Unrecognized role'}</StatusBadge>
              </div>
              <p className="mt-2 text-sm text-theme-text-secondary">
                Your account has {user.permissions?.length ?? 0} of {PERMISSIONS.length} listed
                permissions.
              </p>
            </div>
          ) : null}

          <section>
            <h3 className="mb-3 text-lg font-semibold text-theme-text-primary">Permission matrix</h3>
            <div className="rounded-lg border border-theme-border bg-theme-card shadow-xs">
              <PermissionMatrix currentRole={currentRole} />
            </div>
          </section>

          <section>
            <h3 className="mb-3 text-lg font-semibold text-theme-text-primary">Role summaries</h3>
            <div className="grid gap-3 md:grid-cols-2">
              {ROLES.map((role) => (
                <article
                  className="rounded-lg border border-theme-border bg-theme-card p-4"
                  key={role.key}
                >
                  <h4 className="font-semibold text-theme-text-primary">{role.label}</h4>
                  <p className="mt-1 text-xs text-theme-text-muted">{role.key}</p>
                  <p className="mt-3 text-sm text-theme-text-secondary">
                    {role.permissions.length} of {PERMISSIONS.length} permissions granted.
                  </p>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : (
        <section className="space-y-4 rounded-lg border border-theme-border bg-theme-card p-5 text-sm text-theme-text-secondary">
          <h3 className="text-lg font-semibold text-theme-text-primary">Access rules</h3>
          <ul className="list-inside list-disc space-y-2">
            <li>Each account has exactly one canonical business role.</li>
            <li>Only the ten roles and sixteen permissions shown in the matrix are supported.</li>
            <li>Retired role values, including the former admin role, are rejected and receive no permissions.</li>
            <li>Permission grants do not bypass project membership, ownership, record state, or service checks.</li>
            <li>Submit-only report authors can access their own permitted workflow without general report browsing.</li>
            <li>HR Manager and HR Executive are role labels only; this portal does not provide separate HR modules.</li>
            <li>Role changes and account activation changes require a current record version and revoke prior sessions.</li>
            <li>The production account conversion requires a reviewed UUID-based maintenance manifest; this page does not migrate accounts.</li>
          </ul>
        </section>
      )}
    </div>
  );
}
