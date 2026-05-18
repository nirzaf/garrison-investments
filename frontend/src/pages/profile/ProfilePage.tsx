import { Link } from 'react-router-dom';

import { useAuth } from '../../context/useAuth';
import { StatusBadge } from '../../components/shared/StatusBadge';

function roleLabel(role: string) {
  return role
    .split('_')
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(' ');
}

function ProfileField({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="rounded-md border border-theme-border bg-theme-main p-4">
      <p className="text-xs font-medium uppercase text-theme-text-muted">{label}</p>
      <p className="mt-1 text-sm font-semibold text-theme-text-primary">{value || 'Not set'}</p>
    </div>
  );
}

export function ProfilePage() {
  const { user } = useAuth();

  if (!user) return null;
  const permissions = user.permissions ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">My account</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Profile</h2>
        </div>
        <Link
          className="inline-flex min-h-10 items-center justify-center rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
          to="/change-password"
        >
          Change password
        </Link>
      </div>

      <section className="rounded-lg border border-theme-border bg-theme-card p-5 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-xl font-semibold text-theme-text-primary">{user.full_name}</h3>
            <p className="text-sm text-theme-text-secondary">{user.email}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge tone="info">{roleLabel(user.role)}</StatusBadge>
            <StatusBadge tone={user.is_active ? 'success' : 'danger'}>
              {user.is_active ? 'Active' : 'Inactive'}
            </StatusBadge>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <ProfileField label="Employee code" value={user.employee_code} />
        <ProfileField label="Phone" value={user.phone} />
        <ProfileField label="Designation" value={user.designation} />
        <ProfileField
          label="Password status"
          value={user.must_change_password ? 'Password change required' : 'Password current'}
        />
      </section>

      <section className="rounded-lg border border-theme-border bg-theme-card p-5 shadow-sm">
        <h3 className="text-lg font-semibold text-theme-text-primary">Access permissions</h3>
        <div className="mt-4 flex flex-wrap gap-2">
          {permissions.length > 0 ? (
            permissions.map((permission) => (
              <span
                className="rounded-full border border-theme-border bg-theme-card-elevated px-3 py-1 text-xs font-medium text-theme-text-secondary"
                key={permission}
              >
                {permission}
              </span>
            ))
          ) : (
            <p className="text-sm text-theme-text-secondary">No permissions assigned.</p>
          )}
        </div>
      </section>
    </div>
  );
}
