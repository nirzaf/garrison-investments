import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import { SupportAdminActionDialog } from './SupportAdminActionDialog';
import { SupportUserDetailPage } from './SupportUserDetailPage';
import { buttonClass, formatObserved, panelCardClass } from './supportPanelUtils';

type UserPage = components['schemas']['SupportCompanyUserPage'];
type UserSummary = components['schemas']['SupportCompanyUserSummary'];

const BUSINESS_ROLES_OPTIONS = [
  ['managing_director', 'Managing Director'],
  ['operations_director', 'Operations Director'],
  ['group_project_manager', 'Group Project Manager'],
  ['mep_project_manager', 'MEP Project Manager'],
  ['quantity_surveyor', 'Quantity Surveyor'],
  ['senior_site_supervisor', 'Senior Site Supervisor'],
  ['site_supervisor', 'Site Supervisor'],
  ['hr_manager', 'HR Manager'],
  ['hr_executive_reader', 'HR Executive'],
  ['administrative_executive', 'Administrative Executive']
] as const;

export function SupportUsersPage({
  capabilities,
  selectedUserId,
  onSelectUser,
  onExpired
}: {
  capabilities: string[];
  selectedUserId: string | null;
  onSelectUser: (userId: string | null) => void;
  onExpired: () => void;
}) {
  const canReadDirectory = capabilities.includes('company.directory.read');
  const canManageAccounts = capabilities.includes('company.accounts.manage');

  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('');
  const [page, setPage] = useState<UserPage | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  // Create account form state
  const [showCreate, setShowCreate] = useState(false);
  const [newFullName, setNewFullName] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newEmployeeCode, setNewEmployeeCode] = useState('');
  const [newPhone, setNewPhone] = useState('');
  const [newDesignation, setNewDesignation] = useState('');
  const [newRole, setNewRole] = useState('site_supervisor');
  const [createReason, setCreateReason] = useState('');

  // Bounded bulk lifecycle state (max 25 explicit rows)
  const [selectedMap, setSelectedMap] = useState<Record<string, UserSummary>>({});
  const [bulkOperation, setBulkOperation] = useState<
    'disable' | 'reactivate' | 'unlock' | 'revoke_sessions'
  >('revoke_sessions');
  const [bulkReason, setBulkReason] = useState('');
  const [showBulkDialog, setShowBulkDialog] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  const loadDirectory = useCallback(
    async (cursor?: string | null) => {
      if (!canReadDirectory) return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setPending(true);
      setError('');
      try {
        const params = new URLSearchParams();
        if (search.trim()) params.set('search', search.trim());
        if (roleFilter) params.set('role', roleFilter);
        if (stateFilter) params.set('state', stateFilter);
        if (cursor) params.set('cursor', cursor);
        params.set('limit', '25');
        const response = await supportRequest(`/company/users?${params.toString()}`, {
          signal: controller.signal
        });
        if (controller.signal.aborted) return;
        if (response.status === 401) {
          onExpired();
          return;
        }
        if (response.status === 403) {
          setError('Company account directory requires the company.directory.read capability.');
          return;
        }
        if (!response.ok) throw new Error();
        const data = (await response.json()) as UserPage;
        if (!controller.signal.aborted) setPage(data);
      } catch {
        if (!controller.signal.aborted) {
          setError('The company account directory could not be loaded.');
        }
      } finally {
        if (!controller.signal.aborted) setPending(false);
      }
    },
    [canReadDirectory, onExpired, roleFilter, search, stateFilter]
  );

  useEffect(() => {
    if (!selectedUserId && canReadDirectory) {
      void loadDirectory(null);
    }
    return () => abortRef.current?.abort();
  }, [canReadDirectory, loadDirectory, selectedUserId]);

  if (!canReadDirectory) {
    return (
      <section aria-label="People and access directory" className={panelCardClass}>
        <h2 className="font-semibold">People & Access</h2>
        <p role="alert" className="text-xs text-theme-text-secondary">
          Unavailable: operator account lacks <code>company.directory.read</code>. Case-only
          <code>directory.read</code> remains scoped to assigned support cases.
        </p>
      </section>
    );
  }

  if (selectedUserId) {
    return (
      <SupportUserDetailPage
        userId={selectedUserId}
        onBack={() => onSelectUser(null)}
        onExpired={onExpired}
      />
    );
  }

  const selectedEntries = Object.values(selectedMap);

  function toggleRow(user: UserSummary) {
    setSelectedMap((prev) => {
      const next = { ...prev };
      if (next[user.user_id]) {
        delete next[user.user_id];
      } else if (Object.keys(next).length < 25) {
        next[user.user_id] = user;
      }
      return next;
    });
  }

  function submitSearch(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    void loadDirectory(null);
  }

  return (
    <section aria-label="People and access directory" className="space-y-4">
      <div className={panelCardClass}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold">People & Access Directory</h2>
            <p className="text-xs text-theme-text-secondary">
              Find a person, inspect their effective role and project access, and execute audited
              lifecycle changes.
            </p>
          </div>
          {canManageAccounts && (
            <button
              type="button"
              className="rounded bg-brand-600 px-3 py-1.5 text-xs font-medium text-white"
              onClick={() => setShowCreate((v) => !v)}
            >
              {showCreate ? 'Close create form' : '+ Create or invite user'}
            </button>
          )}
        </div>

        {showCreate && canManageAccounts && (
          <div
            aria-label="Create or invite business user"
            className="space-y-3 rounded border border-theme-border p-3 text-xs"
          >
            <h3 className="font-semibold">Create or invite a business user</h3>
            <p className="text-theme-text-secondary">
              All identity fields are required. One-time activation instructions are sent directly
              to the recipient’s email; the operator never views a password or code.
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="block">
                Full name
                <input
                  type="text"
                  aria-label="New user full name"
                  value={newFullName}
                  onChange={(e) => setNewFullName(e.target.value)}
                  required
                  maxLength={120}
                  className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                />
              </label>
              <label className="block">
                Verified email address
                <input
                  type="email"
                  aria-label="New user email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  required
                  maxLength={254}
                  className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                />
              </label>
              <label className="block">
                Employee code
                <input
                  type="text"
                  aria-label="New user employee code"
                  value={newEmployeeCode}
                  onChange={(e) => setNewEmployeeCode(e.target.value)}
                  required
                  maxLength={64}
                  className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                />
              </label>
              <label className="block">
                Phone number
                <input
                  type="text"
                  aria-label="New user phone"
                  value={newPhone}
                  onChange={(e) => setNewPhone(e.target.value)}
                  required
                  maxLength={32}
                  className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                />
              </label>
              <label className="block">
                Business role
                <select
                  aria-label="New user business role"
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                >
                  {BUSINESS_ROLES_OPTIONS.map(([val, label]) => (
                    <option key={val} value={val}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                Designation (optional)
                <input
                  type="text"
                  aria-label="New user designation"
                  value={newDesignation}
                  onChange={(e) => setNewDesignation(e.target.value)}
                  maxLength={100}
                  className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                />
              </label>
            </div>
            <label className="block">
              Operational reason (10–300 chars)
              <input
                type="text"
                aria-label="Account creation reason"
                value={createReason}
                onChange={(e) => setCreateReason(e.target.value)}
                minLength={10}
                maxLength={300}
                className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
              />
            </label>
            <SupportAdminActionDialog
              title="Create and invite business user"
              description="Creates the business account and queues a recipient-only invitation."
              onExpired={onExpired}
              onCancel={() => setShowCreate(false)}
              onCompleted={() => {
                void loadDirectory(null);
              }}
              buildRequest={() => {
                if (
                  newFullName.trim().length < 2 ||
                  !newEmail.trim() ||
                  !newEmployeeCode.trim() ||
                  newPhone.trim().length < 5 ||
                  createReason.trim().length < 10
                ) {
                  return null;
                }
                return {
                  command_kind: 'create_business_account',
                  email: newEmail.trim(),
                  full_name: newFullName.trim(),
                  role: newRole,
                  employee_code: newEmployeeCode.trim(),
                  phone: newPhone.trim(),
                  ...(newDesignation.trim() ? { designation: newDesignation.trim() } : {}),
                  project_assignments: [],
                  reason_code: 'account_provisioning',
                  reason: createReason.trim()
                };
              }}
            />
          </div>
        )}

        <form onSubmit={submitSearch} className="grid gap-2 sm:grid-cols-4 text-xs">
          <label className="block">
            Search name, email, or code
            <input
              type="search"
              aria-label="Search accounts"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              maxLength={120}
              placeholder="e.g. name, code, email"
              className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
            />
          </label>
          <label className="block">
            Business role
            <select
              aria-label="Filter by business role"
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
              className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
            >
              <option value="">All business roles</option>
              {BUSINESS_ROLES_OPTIONS.map(([val, label]) => (
                <option key={val} value={val}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            Account state
            <select
              aria-label="Filter by account state"
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
            >
              <option value="">All states</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="locked">Locked</option>
            </select>
          </label>
          <div className="flex items-end gap-2">
            <button type="submit" className={buttonClass} disabled={pending}>
              {pending ? 'Searching…' : 'Search directory'}
            </button>
          </div>
        </form>

        {error && (
          <p role="alert" className="text-xs text-red-700">
            {error}
          </p>
        )}

        {canManageAccounts && selectedEntries.length > 0 && (
          <div
            aria-label="Bulk account lifecycle workspace"
            className="space-y-2 rounded border border-theme-border p-3 text-xs"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-semibold">
                Selected accounts for bounded bulk action: {selectedEntries.length} / 25
              </span>
              <button
                type="button"
                className={buttonClass}
                onClick={() => {
                  setSelectedMap({});
                  setShowBulkDialog(false);
                }}
              >
                Clear selection
              </button>
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              <label className="block">
                Bulk lifecycle operation
                <select
                  aria-label="Bulk lifecycle operation"
                  value={bulkOperation}
                  onChange={(e) =>
                    setBulkOperation(
                      e.target.value as 'disable' | 'reactivate' | 'unlock' | 'revoke_sessions'
                    )
                  }
                  className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                >
                  <option value="revoke_sessions">Revoke sessions</option>
                  <option value="disable">Disable accounts</option>
                  <option value="reactivate">Reactivate accounts</option>
                  <option value="unlock">Clear sign-in locks</option>
                </select>
              </label>
              <label className="block sm:col-span-2">
                Bulk operational reason (10–300 chars)
                <input
                  type="text"
                  aria-label="Bulk operational reason"
                  value={bulkReason}
                  onChange={(e) => setBulkReason(e.target.value)}
                  minLength={10}
                  maxLength={300}
                  className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                />
              </label>
            </div>
            {!showBulkDialog ? (
              <button type="button" className={buttonClass} onClick={() => setShowBulkDialog(true)}>
                Prepare bulk command
              </button>
            ) : (
              <SupportAdminActionDialog
                title={`Bulk ${bulkOperation.replace(/_/g, ' ')} (${selectedEntries.length} accounts)`}
                description="Applies per-item atomic checks and preserves the last-usable-director anti-lockout rule."
                onExpired={onExpired}
                onCancel={() => setShowBulkDialog(false)}
                onCompleted={() => {
                  setSelectedMap({});
                  void loadDirectory(null);
                }}
                buildRequest={() =>
                  bulkReason.trim().length >= 10 && selectedEntries.length > 0
                    ? {
                        command_kind: 'bulk_account_lifecycle',
                        operation: bulkOperation,
                        targets: selectedEntries.map((u) => ({
                          user_id: u.user_id,
                          expected_user_revision: u.access_revision
                        })),
                        reason_code: 'suspected_access',
                        reason: bulkReason.trim()
                      }
                    : null
                }
              />
            )}
          </div>
        )}

        {page && (
          <div className="space-y-2 text-xs">
            <p className="text-theme-text-secondary">
              Matching business accounts: <strong>{page.total}</strong>
            </p>
            {page.items.length === 0 ? (
              <p>No business accounts matched the current filters.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-theme-border text-theme-text-secondary">
                      {canManageAccounts && <th className="py-1.5 pr-2">Select</th>}
                      <th className="py-1.5 pr-2">Person</th>
                      <th className="py-1.5 pr-2">Business Role</th>
                      <th className="py-1.5 pr-2">State</th>
                      <th className="py-1.5 pr-2">Projects</th>
                      <th className="py-1.5 pr-2">Last Sign-in</th>
                      <th className="py-1.5">Profile</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((item) => (
                      <tr key={item.user_id} className="border-b border-theme-border/60">
                        {canManageAccounts && (
                          <td className="py-1.5 pr-2">
                            <input
                              type="checkbox"
                              aria-label={`Select ${item.full_name}`}
                              checked={Boolean(selectedMap[item.user_id])}
                              onChange={() => toggleRow(item)}
                            />
                          </td>
                        )}
                        <td className="py-1.5 pr-2">
                          <div className="font-medium">{item.full_name}</div>
                          <div className="text-theme-text-secondary">
                            {item.email_masked}
                            {item.employee_code ? ` · ${item.employee_code}` : ''}
                          </div>
                        </td>
                        <td className="py-1.5 pr-2">{item.role_label}</td>
                        <td className="py-1.5 pr-2 uppercase font-medium">{item.state}</td>
                        <td className="py-1.5 pr-2">{item.assigned_project_count}</td>
                        <td className="py-1.5 pr-2">
                          {item.last_login_at ? formatObserved(item.last_login_at) : 'Never'}
                        </td>
                        <td className="py-1.5">
                          <button
                            type="button"
                            className={buttonClass}
                            onClick={() => onSelectUser(item.user_id)}
                          >
                            Open User 360
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {page.next_cursor && (
              <button
                type="button"
                className={buttonClass}
                disabled={pending}
                onClick={() => void loadDirectory(page.next_cursor)}
              >
                Load next page
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
