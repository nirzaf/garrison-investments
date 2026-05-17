import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

import {
  createUser,
  deactivateUser,
  listUsers,
  type CreateUserPayload,
  type UserRecord
} from '../../api/users';

const roles = [
  'admin',
  'general_manager',
  'operation_manager',
  'project_manager',
  'civil_engineer',
  'civil_supervisor',
  'store_keeper',
  'accounts'
];

const initialForm: CreateUserPayload = {
  email: '',
  full_name: '',
  role: 'civil_engineer',
  employee_code: '',
  phone: '',
  designation: '',
  temporary_password: 'ChangeMe123!'
};

function roleLabel(role: string) {
  return role
    .split('_')
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(' ');
}

export function UserManagementPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [activeFilter, setActiveFilter] = useState('active');
  const [roleFilter, setRoleFilter] = useState('');
  const [search, setSearch] = useState('');
  const [form, setForm] = useState<CreateUserPayload>(initialForm);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const filters = useMemo(
    () => ({
      active: activeFilter === 'all' ? undefined : activeFilter === 'active',
      role: roleFilter || undefined,
      search: search || undefined
    }),
    [activeFilter, roleFilter, search]
  );

  const loadUsers = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listUsers(filters);
      setUsers(response.items);
      setTotal(response.total);
    } catch {
      setError('Unable to load users.');
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await createUser(form);
      setForm(initialForm);
      await loadUsers();
    } catch {
      setError('Unable to create user.');
    }
  }

  async function handleDeactivate(user: UserRecord) {
    const confirmed = window.confirm(`Deactivate ${user.full_name}?`);
    if (!confirmed) return;
    setError(null);
    try {
      await deactivateUser(user.id);
      await loadUsers();
    } catch {
      setError('Unable to deactivate user.');
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-600">Admin</p>
          <h2 className="text-2xl font-semibold text-theme-text-primary">Users</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <input
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search"
            value={search}
          />
          <select
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setRoleFilter(event.target.value)}
            value={roleFilter}
          >
            <option value="">All roles</option>
            {roles.map((role) => (
              <option key={role} value={role}>
                {roleLabel(role)}
              </option>
            ))}
          </select>
          <select
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setActiveFilter(event.target.value)}
            value={activeFilter}
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="all">All statuses</option>
          </select>
        </div>
      </div>

      {error ? <p className="alert-error rounded-md px-3 py-2 text-sm">{error}</p> : null}

      <section className="rounded-lg border border-theme-border bg-theme-card p-4 shadow-sm">
        <form className="grid gap-3 lg:grid-cols-4" onSubmit={handleCreate}>
          <input
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setForm({ ...form, full_name: event.target.value })}
            placeholder="Full name"
            required
            value={form.full_name}
          />
          <input
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setForm({ ...form, email: event.target.value })}
            placeholder="Email"
            required
            type="email"
            value={form.email}
          />
          <select
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setForm({ ...form, role: event.target.value })}
            value={form.role}
          >
            {roles.map((role) => (
              <option key={role} value={role}>
                {roleLabel(role)}
              </option>
            ))}
          </select>
          <input
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setForm({ ...form, employee_code: event.target.value })}
            placeholder="Employee code"
            required
            value={form.employee_code}
          />
          <input
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setForm({ ...form, phone: event.target.value })}
            placeholder="Phone"
            required
            value={form.phone}
          />
          <input
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setForm({ ...form, designation: event.target.value })}
            placeholder="Designation"
            value={form.designation ?? ''}
          />
          <input
            className="rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
            onChange={(event) => setForm({ ...form, temporary_password: event.target.value })}
            placeholder="Temporary password"
            required
            type="password"
            value={form.temporary_password}
          />
          <button
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
            type="submit"
          >
            Create user
          </button>
        </form>
      </section>

      <section className="overflow-hidden rounded-lg border border-theme-border bg-theme-card shadow-sm">
        <div className="border-b border-theme-border px-4 py-3 text-sm text-theme-text-secondary">
          {isLoading ? 'Loading users' : `${total} users`}
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-theme-border text-sm">
            <thead className="bg-theme-main text-left text-xs font-semibold uppercase text-theme-text-muted">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Employee</th>
                <th className="px-4 py-3">Phone</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-theme-border">
              {users.map((user) => (
                <tr key={user.id}>
                  <td className="px-4 py-3">
                    <p className="font-medium text-theme-text-primary">{user.full_name}</p>
                    <p className="text-xs text-theme-text-muted">{user.email}</p>
                  </td>
                  <td className="px-4 py-3">{roleLabel(user.role)}</td>
                  <td className="px-4 py-3">{user.employee_code}</td>
                  <td className="px-4 py-3">{user.phone}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-1 text-xs font-semibold ${
                        user.is_active
                          ? 'bg-[var(--status-success-bg)] text-[var(--status-success-text)]'
                          : 'bg-theme-card-elevated text-theme-text-secondary'
                      }`}
                    >
                      {user.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {user.is_active ? (
                      <button
                        className="text-sm font-medium text-[var(--status-error-text)] hover:opacity-80"
                        onClick={() => void handleDeactivate(user)}
                        type="button"
                      >
                        Deactivate
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
