import { useCallback, useEffect, useRef, useState } from 'react';

import type { components } from '../../api/schema';
import { supportPost, supportRequest } from '../../api/support';
import { SupportAdminActionDialog } from './SupportAdminActionDialog';
import { buttonClass, formatObserved, panelCardClass } from './supportPanelUtils';

type Profile = components['schemas']['SupportCompanyUserProfileRead'];
type AccessRead = components['schemas']['SupportCompanyUserAccessRead'];
type SessionsRead = components['schemas']['SupportUserSessionInventoryRead'];
type ActivityPage = components['schemas']['SupportUserActivityPage'];
type DiagnoseRead = components['schemas']['SupportDiagnoseCaseRead'];

type TabKey = 'overview' | 'access' | 'sessions' | 'security' | 'activity' | 'support';

export function SupportUserDetailPage({
  userId,
  onBack,
  onExpired
}: {
  userId: string;
  onBack: () => void;
  onExpired: () => void;
}) {
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [profile, setProfile] = useState<Profile | null>(null);
  const [access, setAccess] = useState<AccessRead | null>(null);
  const [sessions, setSessions] = useState<SessionsRead | null>(null);
  const [activity, setActivity] = useState<ActivityPage | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');

  // Active command modal states
  const [activeDialog, setActiveDialog] = useState<
    | null
    | 'toggle_state'
    | 'unlock'
    | 'change_role'
    | 'membership'
    | 'recovery'
    | 'revoke_all_sessions'
    | { kind: 'revoke_selected_session'; sessionId: string }
  >(null);
  const [reason, setReason] = useState('');
  const [selectedRole, setSelectedRole] = useState('');
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [membershipAction, setMembershipAction] = useState<'assign' | 'revoke'>('assign');
  const [roleInProject, setRoleInProject] = useState('');
  const [explainProjectId, setExplainProjectId] = useState('');
  const [diagnoseReason, setDiagnoseReason] = useState('');
  const [diagnoseResult, setDiagnoseResult] = useState<DiagnoseRead | null>(null);
  const [diagnoseError, setDiagnoseError] = useState('');
  const [diagnosePending, setDiagnosePending] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  const loadCore = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPending(true);
    setError('');
    try {
      const [profResp, accResp] = await Promise.all([
        supportRequest(`/company/users/${encodeURIComponent(userId)}`, {
          signal: controller.signal
        }),
        supportRequest(`/company/users/${encodeURIComponent(userId)}/access`, {
          signal: controller.signal
        })
      ]);
      if (controller.signal.aborted) return;
      if (profResp.status === 401 || accResp.status === 401) {
        onExpired();
        return;
      }
      if (!profResp.ok) {
        setError('The business user profile could not be loaded.');
        return;
      }
      const profData = (await profResp.json()) as Profile;
      setProfile(profData);
      setSelectedRole(profData.role);
      if (accResp.ok) {
        const accData = (await accResp.json()) as AccessRead;
        setAccess(accData);
        if (accData.eligible_projects.length > 0 && !selectedProjectId) {
          setSelectedProjectId(accData.eligible_projects[0].project_id);
        }
      }
    } catch {
      if (!controller.signal.aborted) setError('The business user profile could not be loaded.');
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }, [onExpired, selectedProjectId, userId]);

  useEffect(() => {
    setProfile(null);
    setAccess(null);
    setSessions(null);
    setActivity(null);
    setActiveDialog(null);
    setDiagnoseResult(null);
    void loadCore();
    return () => abortRef.current?.abort();
  }, [loadCore, userId]);

  const loadSessions = useCallback(async () => {
    try {
      const resp = await supportRequest(`/company/users/${encodeURIComponent(userId)}/sessions`);
      if (resp.status === 401) {
        onExpired();
        return;
      }
      if (resp.ok) setSessions((await resp.json()) as SessionsRead);
    } catch {
      // Handled inline in sessions tab
    }
  }, [onExpired, userId]);

  const loadActivity = useCallback(async () => {
    try {
      const resp = await supportRequest(`/company/users/${encodeURIComponent(userId)}/activity`);
      if (resp.status === 401) {
        onExpired();
        return;
      }
      if (resp.ok) setActivity((await resp.json()) as ActivityPage);
    } catch {
      // Handled inline in activity tab
    }
  }, [onExpired, userId]);

  useEffect(() => {
    if (activeTab === 'sessions') void loadSessions();
    if (activeTab === 'activity') void loadActivity();
  }, [activeTab, loadActivity, loadSessions]);

  async function explainProjectAccess(projId: string) {
    setExplainProjectId(projId);
    const query = projId ? `?project_id=${encodeURIComponent(projId)}` : '';
    const resp = await supportRequest(
      `/company/users/${encodeURIComponent(userId)}/access${query}`
    );
    if (resp.status === 401) {
      onExpired();
      return;
    }
    if (resp.ok) setAccess((await resp.json()) as AccessRead);
  }

  async function handleDiagnoseCase() {
    if (diagnosePending || diagnoseReason.trim().length < 10) return;
    setDiagnosePending(true);
    setDiagnoseError('');
    try {
      const resp = await supportPost(`/company/users/${encodeURIComponent(userId)}/diagnose-case`, {
        reason: diagnoseReason.trim(),
        ...(explainProjectId ? { project_id: explainProjectId } : {})
      });
      if (resp.status === 401) {
        onExpired();
        return;
      }
      if (!resp.ok) {
        const body = (await resp.json().catch(() => null)) as { detail?: string } | null;
        setDiagnoseError(body?.detail || 'Support case could not be linked.');
        return;
      }
      setDiagnoseResult((await resp.json()) as DiagnoseRead);
      void loadCore();
    } catch {
      setDiagnoseError('Support case could not be linked.');
    } finally {
      setDiagnosePending(false);
    }
  }

  function actionAvailability(kind: string) {
    return profile?.available_actions.find((a) => a.action_kind === kind);
  }

  return (
    <section aria-label="User 360 profile" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" className={buttonClass} onClick={onBack}>
          ← Back to People & Access
        </button>
        {profile && (
          <button type="button" className={buttonClass} onClick={() => void loadCore()}>
            Refresh profile
          </button>
        )}
      </div>

      {pending && <p role="status">Loading user profile…</p>}
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}

      {profile && (
        <>
          <header className={panelCardClass}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">{profile.full_name}</h2>
                <p className="text-xs text-theme-text-secondary">
                  {profile.email_masked}
                  {profile.employee_code ? ` · Code ${profile.employee_code}` : ''}
                  {profile.designation ? ` · ${profile.designation}` : ''}
                </p>
                <p className="mt-1 font-mono text-[11px] text-theme-text-secondary">
                  Account ID: <code>{profile.user_id}</code> · Access revision{' '}
                  {profile.access_revision}
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5 text-xs">
                <span className="rounded border border-theme-border px-2 py-0.5 font-medium">
                  {profile.role_label}
                </span>
                <span className="rounded border border-theme-border px-2 py-0.5 font-medium uppercase">
                  {profile.state}
                </span>
                <span className="rounded border border-theme-border px-2 py-0.5">
                  {profile.has_linked_employee
                    ? `HR record linked (${profile.employee_status ?? 'linked'})`
                    : 'No linked HR record'}
                </span>
              </div>
            </div>

            <nav
              aria-label="User 360 tabs"
              className="flex flex-wrap gap-1.5 border-t border-theme-border pt-2"
            >
              {(
                [
                  ['overview', 'Overview'],
                  ['access', 'Access'],
                  ['sessions', 'Sessions'],
                  ['security', 'Security & Recovery'],
                  ['activity', 'Activity'],
                  ['support', 'Support History']
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === key}
                  onClick={() => {
                    setActiveTab(key);
                    setActiveDialog(null);
                  }}
                  className={`${buttonClass} ${
                    activeTab === key ? 'bg-brand-600 text-white border-brand-600' : ''
                  }`}
                >
                  {label}
                </button>
              ))}
            </nav>
          </header>

          {activeDialog && (
            <div className="space-y-2">
              <label className="block text-xs font-medium">
                Operational reason for audit receipt (10–300 chars)
                <input
                  type="text"
                  aria-label="Command operational reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  minLength={10}
                  maxLength={300}
                  placeholder="Describe why this change is authorized…"
                  className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1.5 text-xs"
                />
              </label>

              {activeDialog === 'toggle_state' && (
                <SupportAdminActionDialog
                  title={
                    profile.is_active ? 'Disable business account' : 'Reactivate business account'
                  }
                  description="Updates account sign-in eligibility, increments access_revision, and revokes active sessions."
                  onExpired={onExpired}
                  onCancel={() => setActiveDialog(null)}
                  onCompleted={() => void loadCore()}
                  buildRequest={() =>
                    reason.trim().length >= 10
                      ? {
                          command_kind: 'set_account_state',
                          target_user_id: profile.user_id,
                          expected_user_revision: profile.access_revision,
                          active: !profile.is_active,
                          reason_code: 'suspected_access',
                          reason: reason.trim()
                        }
                      : null
                  }
                />
              )}

              {activeDialog === 'unlock' && (
                <SupportAdminActionDialog
                  title="Clear failed sign-in lock"
                  description="Resets failed login counter and clears temporary lockout."
                  onExpired={onExpired}
                  onCancel={() => setActiveDialog(null)}
                  onCompleted={() => void loadCore()}
                  buildRequest={() =>
                    reason.trim().length >= 10
                      ? {
                          command_kind: 'unlock_account',
                          target_user_id: profile.user_id,
                          expected_user_revision: profile.access_revision,
                          reason_code: 'failed_sign_in',
                          reason: reason.trim()
                        }
                      : null
                  }
                />
              )}

              {activeDialog === 'change_role' && (
                <SupportAdminActionDialog
                  title="Change business role"
                  description="Assigns a role within the 10-role business ceiling and invalidates existing sessions."
                  onExpired={onExpired}
                  onCancel={() => setActiveDialog(null)}
                  onCompleted={() => void loadCore()}
                  buildRequest={() =>
                    reason.trim().length >= 10 && selectedRole
                      ? {
                          command_kind: 'change_business_role',
                          target_user_id: profile.user_id,
                          expected_user_revision: profile.access_revision,
                          new_role: selectedRole,
                          reason_code: 'role_adjustment',
                          reason: reason.trim()
                        }
                      : null
                  }
                />
              )}

              {activeDialog === 'membership' && (
                <SupportAdminActionDialog
                  title={`${membershipAction === 'assign' ? 'Assign' : 'Revoke'} project membership`}
                  description="Updates project membership and increments both project and user access revisions."
                  onExpired={onExpired}
                  onCancel={() => setActiveDialog(null)}
                  onCompleted={() => void loadCore()}
                  buildRequest={() => {
                    const targetProj = access?.eligible_projects.find(
                      (p) => p.project_id === selectedProjectId
                    );
                    if (reason.trim().length < 10 || !targetProj) return null;
                    return {
                      command_kind: 'change_project_membership',
                      target_user_id: profile.user_id,
                      expected_user_revision: profile.access_revision,
                      project_id: targetProj.project_id,
                      expected_project_revision: targetProj.project_revision,
                      action: membershipAction,
                      ...(membershipAction === 'assign' && roleInProject.trim()
                        ? { role_in_project: roleInProject.trim() }
                        : {}),
                      reason_code: 'project_membership',
                      reason: reason.trim()
                    };
                  }}
                />
              )}

              {activeDialog === 'recovery' && (
                <SupportAdminActionDialog
                  title="Send recipient-mediated recovery instructions"
                  description="Delivers a one-time recovery code directly to the user's verified email. The operator never sees the secret."
                  onExpired={onExpired}
                  onCancel={() => setActiveDialog(null)}
                  onCompleted={() => void loadCore()}
                  buildRequest={() =>
                    reason.trim().length >= 10
                      ? {
                          command_kind: 'request_account_recovery',
                          target_user_id: profile.user_id,
                          expected_user_revision: profile.access_revision,
                          reason_code: 'verified_user_report',
                          reason: reason.trim()
                        }
                      : null
                  }
                />
              )}

              {activeDialog === 'revoke_all_sessions' && (
                <SupportAdminActionDialog
                  title="Revoke all business sessions"
                  description="Revokes all active sessions, refresh tokens, and pending challenges for this user."
                  onExpired={onExpired}
                  onCancel={() => setActiveDialog(null)}
                  onCompleted={() => {
                    void loadCore();
                    void loadSessions();
                  }}
                  buildRequest={() =>
                    reason.trim().length >= 10
                      ? {
                          command_kind: 'revoke_business_session',
                          target_user_id: profile.user_id,
                          expected_user_revision: profile.access_revision,
                          scope: 'all',
                          reason_code: 'suspected_access',
                          reason: reason.trim()
                        }
                      : null
                  }
                />
              )}

              {typeof activeDialog === 'object' &&
                activeDialog.kind === 'revoke_selected_session' && (
                  <SupportAdminActionDialog
                    title="Revoke selected business session"
                    description={`Revokes session ${activeDialog.sessionId} and its bound refresh tokens.`}
                    onExpired={onExpired}
                    onCancel={() => setActiveDialog(null)}
                    onCompleted={() => {
                      void loadCore();
                      void loadSessions();
                    }}
                    buildRequest={() =>
                      reason.trim().length >= 10
                        ? {
                            command_kind: 'revoke_business_session',
                            target_user_id: profile.user_id,
                            expected_user_revision: profile.access_revision,
                            scope: 'selected',
                            session_id: activeDialog.sessionId,
                            reason_code: 'suspected_access',
                            reason: reason.trim()
                          }
                        : null
                    }
                  />
                )}
            </div>
          )}

          {activeTab === 'overview' && (
            <section aria-label="User overview tab" className={panelCardClass}>
              <h3 className="font-semibold">Account overview & available interventions</h3>
              <dl className="grid gap-2 text-xs sm:grid-cols-3">
                <div>
                  <dt className="text-theme-text-secondary">Assigned projects</dt>
                  <dd className="font-medium">{profile.assigned_project_count}</dd>
                </div>
                <div>
                  <dt className="text-theme-text-secondary">Active business sessions</dt>
                  <dd className="font-medium">{profile.active_session_count}</dd>
                </div>
                <div>
                  <dt className="text-theme-text-secondary">Verified recovery email</dt>
                  <dd className="font-medium">
                    {profile.recovery_destination_verified ? 'Verified' : 'Unverified'}
                  </dd>
                </div>
                <div>
                  <dt className="text-theme-text-secondary">Masked phone</dt>
                  <dd className="font-medium">{profile.phone_masked ?? 'Not recorded'}</dd>
                </div>
                <div>
                  <dt className="text-theme-text-secondary">Last sign-in</dt>
                  <dd className="font-medium">
                    {profile.last_login_at ? formatObserved(profile.last_login_at) : 'Never'}
                  </dd>
                </div>
                <div>
                  <dt className="text-theme-text-secondary">Confidential HR data</dt>
                  <dd className="font-medium">Not disclosed in technical portal</dd>
                </div>
              </dl>

              <div className="space-y-2 border-t border-theme-border pt-3">
                <h4 className="text-xs font-semibold">Permitted actions & policy reasons</h4>
                <ul className="space-y-1.5 text-xs">
                  {profile.available_actions.map((act) => (
                    <li
                      key={act.action_kind}
                      className="flex flex-wrap items-center justify-between gap-2 rounded border border-theme-border p-2"
                    >
                      <div>
                        <span className="font-medium">{act.label}</span>
                        <span className="ml-2 text-theme-text-secondary">
                          ({act.allowed ? 'Available' : 'Unavailable'}) — {act.reason}
                        </span>
                      </div>
                      {act.action_kind === 'set_account_state' && (
                        <button
                          type="button"
                          className={buttonClass}
                          disabled={!act.allowed}
                          onClick={() => {
                            setReason('');
                            setActiveDialog('toggle_state');
                          }}
                        >
                          {profile.is_active ? 'Disable account' : 'Reactivate account'}
                        </button>
                      )}
                      {act.action_kind === 'unlock_account' && (
                        <button
                          type="button"
                          className={buttonClass}
                          disabled={!act.allowed}
                          onClick={() => {
                            setReason('');
                            setActiveDialog('unlock');
                          }}
                        >
                          Clear sign-in lock
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          {activeTab === 'access' && access && (
            <section aria-label="User access tab" className={panelCardClass}>
              <h3 className="font-semibold">Effective permissions, role & project access</h3>

              <div className="space-y-2 rounded border border-theme-border p-3 text-xs">
                <h4 className="font-semibold">Why can’t this person access a project?</h4>
                <div className="flex flex-wrap items-end gap-2">
                  <label className="block">
                    Select project to diagnose
                    <select
                      aria-label="Select project to diagnose"
                      value={explainProjectId}
                      onChange={(e) => void explainProjectAccess(e.target.value)}
                      className="mt-1 block rounded border border-theme-border bg-theme-card px-2 py-1 text-xs"
                    >
                      <option value="">Select a project…</option>
                      {access.eligible_projects.map((p) => (
                        <option key={p.project_id} value={p.project_id}>
                          {p.project_code} — {p.project_name} ({p.project_status})
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {access.focused_project_explanation && (
                  <div
                    role="status"
                    aria-label="Focused project access explanation"
                    className="mt-2 rounded border border-theme-border bg-theme-main p-2"
                  >
                    <p className="font-semibold">
                      {access.focused_project_explanation.label} ·{' '}
                      <span className="uppercase">
                        {access.focused_project_explanation.category.replace(/_/g, ' ')}
                      </span>
                    </p>
                    <p className="mt-0.5">{access.focused_project_explanation.explanation}</p>
                  </div>
                )}
              </div>

              <div className="grid gap-3 sm:grid-cols-2 text-xs">
                <div className="space-y-2 rounded border border-theme-border p-3">
                  <h4 className="font-semibold">Change business role</h4>
                  <label className="block">
                    Target business role
                    <select
                      aria-label="Target business role"
                      value={selectedRole}
                      onChange={(e) => setSelectedRole(e.target.value)}
                      className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                    >
                      {access.assignable_roles.map((r) => (
                        <option key={r.role} value={r.role}>
                          {r.label} ({r.role})
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className={buttonClass}
                    disabled={
                      !actionAvailability('change_business_role')?.allowed ||
                      selectedRole === profile.role
                    }
                    onClick={() => {
                      setReason('');
                      setActiveDialog('change_role');
                    }}
                  >
                    Prepare role change
                  </button>
                </div>

                <div className="space-y-2 rounded border border-theme-border p-3">
                  <h4 className="font-semibold">Assign or revoke project membership</h4>
                  <label className="block">
                    Project
                    <select
                      aria-label="Membership project"
                      value={selectedProjectId}
                      onChange={(e) => setSelectedProjectId(e.target.value)}
                      className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                    >
                      {access.eligible_projects.map((p) => (
                        <option key={p.project_id} value={p.project_id}>
                          {p.project_code} — {p.project_name} (
                          {p.is_member ? 'Member' : 'Not member'})
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="block">
                      Action
                      <select
                        aria-label="Membership action"
                        value={membershipAction}
                        onChange={(e) => setMembershipAction(e.target.value as 'assign' | 'revoke')}
                        className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                      >
                        <option value="assign">Assign to project</option>
                        <option value="revoke">Remove from project</option>
                      </select>
                    </label>
                    {membershipAction === 'assign' && (
                      <label className="block">
                        Role in project (optional)
                        <input
                          type="text"
                          aria-label="Role in project"
                          value={roleInProject}
                          onChange={(e) => setRoleInProject(e.target.value)}
                          maxLength={100}
                          className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                        />
                      </label>
                    )}
                  </div>
                  <button
                    type="button"
                    className={buttonClass}
                    disabled={!actionAvailability('change_project_membership')?.allowed}
                    onClick={() => {
                      setReason('');
                      setActiveDialog('membership');
                    }}
                  >
                    Prepare membership change
                  </button>
                </div>
              </div>

              <div className="space-y-2 text-xs">
                <h4 className="font-semibold">
                  Active project memberships ({access.project_memberships.length})
                </h4>
                {access.project_memberships.length === 0 ? (
                  <p className="text-theme-text-secondary">No active project memberships.</p>
                ) : (
                  <ul className="space-y-1">
                    {access.project_memberships.map((m) => (
                      <li
                        key={m.membership_id}
                        className="flex items-center justify-between rounded border border-theme-border px-2 py-1"
                      >
                        <span>
                          <strong>{m.project_code}</strong> — {m.project_name} ({m.project_status})
                          {m.role_in_project ? ` · ${m.role_in_project}` : ''}
                        </span>
                        <span className="font-mono text-[11px] text-theme-text-secondary">
                          rev {m.project_revision}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="space-y-2 text-xs">
                <h4 className="font-semibold">Structured policy & denial explanations</h4>
                <ul className="space-y-1">
                  {access.explanations.map((item) => (
                    <li
                      key={item.subject_key}
                      className="rounded border border-theme-border px-2 py-1.5"
                    >
                      <span className="font-medium">{item.label}</span> ·{' '}
                      <span className="font-mono uppercase text-[11px]">
                        {item.category.replace(/_/g, ' ')}
                      </span>
                      <p className="text-theme-text-secondary">{item.explanation}</p>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="space-y-1 text-xs">
                <h4 className="font-semibold">
                  Effective permissions ({access.effective_permissions.length})
                </h4>
                <div className="flex flex-wrap gap-1">
                  {access.effective_permissions.map((perm) => (
                    <code
                      key={perm}
                      className="rounded border border-theme-border px-1.5 py-0.5 font-mono text-[11px]"
                    >
                      {perm}
                    </code>
                  ))}
                </div>
              </div>
            </section>
          )}

          {activeTab === 'sessions' && (
            <section aria-label="User sessions tab" className={panelCardClass}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold">Business session inventory</h3>
                <button
                  type="button"
                  className={buttonClass}
                  disabled={!actionAvailability('revoke_business_session')?.allowed}
                  onClick={() => {
                    setReason('');
                    setActiveDialog('revoke_all_sessions');
                  }}
                >
                  Revoke all business sessions
                </button>
              </div>
              <p className="text-xs text-theme-text-secondary">
                Shows session lifecycle metadata only. Access and refresh token values are never
                disclosed.
              </p>
              {sessions?.has_unindexed_legacy_tokens && (
                <p
                  role="alert"
                  className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs"
                >
                  This account has legacy refresh tokens not bound to a specific session ID. Use
                  “Revoke all business sessions” to invalidate every token.
                </p>
              )}
              {!sessions ? (
                <p className="text-xs text-theme-text-secondary">
                  Session inventory requires the <code>company.sessions.read</code> capability.
                </p>
              ) : sessions.sessions.length === 0 ? (
                <p className="text-xs text-theme-text-secondary">No recorded business sessions.</p>
              ) : (
                <ul className="space-y-2 text-xs">
                  {sessions.sessions.map((s) => (
                    <li
                      key={s.session_id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded border border-theme-border p-2"
                    >
                      <div>
                        <p className="font-mono text-[11px]">{s.session_id}</p>
                        <p className="text-theme-text-secondary">
                          State: <strong className="uppercase">{s.state}</strong> · Created{' '}
                          {formatObserved(s.created_at)} · Last active{' '}
                          {formatObserved(s.last_active_at)} · Expires{' '}
                          {formatObserved(s.expires_at)}
                        </p>
                      </div>
                      {s.state === 'active' && (
                        <button
                          type="button"
                          className={buttonClass}
                          disabled={!actionAvailability('revoke_business_session')?.allowed}
                          onClick={() => {
                            setReason('');
                            setActiveDialog({
                              kind: 'revoke_selected_session',
                              sessionId: s.session_id
                            });
                          }}
                        >
                          Revoke session
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {activeTab === 'security' && (
            <section aria-label="User security and recovery tab" className={panelCardClass}>
              <h3 className="font-semibold">Security & recipient-mediated recovery</h3>
              <p className="text-xs text-theme-text-secondary">
                Recovery instructions are delivered directly to the verified account email (
                {profile.email_masked}). The technical owner never enters or views a user’s
                password, reset link, or OTP.
              </p>
              <div className="rounded border border-theme-border p-3 text-xs space-y-2">
                <p>
                  Recovery destination status:{' '}
                  <strong>
                    {profile.recovery_destination_verified
                      ? 'Verified via prior email OTP sign-in'
                      : 'Not yet verified'}
                  </strong>
                </p>
                <p>Policy status: {actionAvailability('request_account_recovery')?.reason}</p>
                <button
                  type="button"
                  className={buttonClass}
                  disabled={!actionAvailability('request_account_recovery')?.allowed}
                  onClick={() => {
                    setReason('');
                    setActiveDialog('recovery');
                  }}
                >
                  Send recovery instructions
                </button>
              </div>
            </section>
          )}

          {activeTab === 'activity' && (
            <section aria-label="User activity tab" className={panelCardClass}>
              <h3 className="font-semibold">Recent account & administrative events</h3>
              {!activity || activity.items.length === 0 ? (
                <p className="text-xs text-theme-text-secondary">No recent events recorded.</p>
              ) : (
                <ul className="space-y-1.5 text-xs">
                  {activity.items.map((item) => (
                    <li
                      key={`${item.source}:${item.event_id}`}
                      className="rounded border border-theme-border px-2 py-1.5"
                    >
                      <div className="flex flex-wrap justify-between gap-2">
                        <span className="font-medium">{item.summary}</span>
                        <time className="text-theme-text-secondary" dateTime={item.occurred_at}>
                          {formatObserved(item.occurred_at)}
                        </time>
                      </div>
                      <p className="font-mono text-[11px] text-theme-text-secondary">
                        Source: {item.source}
                        {item.authorization_mode ? ` · Mode: ${item.authorization_mode}` : ''}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {activeTab === 'support' && (
            <section aria-label="User support history tab" className={panelCardClass}>
              <h3 className="font-semibold">Support cases & contextual diagnosis</h3>
              <p className="text-xs text-theme-text-secondary">
                Automatically link or open an auditable support case for {profile.full_name} without
                copying raw UUIDs.
              </p>
              <div className="space-y-2 rounded border border-theme-border p-3 text-xs">
                <label className="block">
                  Diagnosis reason (10–300 chars)
                  <input
                    type="text"
                    aria-label="Diagnosis reason"
                    value={diagnoseReason}
                    onChange={(e) => setDiagnoseReason(e.target.value)}
                    minLength={10}
                    maxLength={300}
                    placeholder="Explain why a support case is needed for this account…"
                    className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
                  />
                </label>
                <button
                  type="button"
                  className={buttonClass}
                  disabled={diagnosePending || diagnoseReason.trim().length < 10}
                  onClick={() => void handleDiagnoseCase()}
                >
                  {diagnosePending ? 'Linking case…' : 'Open or link support case'}
                </button>
                {diagnoseError && (
                  <p role="alert" className="text-red-700">
                    {diagnoseError}
                  </p>
                )}
                {diagnoseResult && (
                  <p role="status" className="rounded bg-theme-main p-2 font-mono">
                    {diagnoseResult.created_new ? 'Created new case' : 'Linked existing case'}:{' '}
                    <code>{diagnoseResult.case_id}</code> ({diagnoseResult.status} · rev{' '}
                    {diagnoseResult.revision})
                  </p>
                )}
              </div>

              <div className="space-y-1 text-xs">
                <h4 className="font-semibold">
                  Linked support cases ({profile.linked_cases.length})
                </h4>
                {profile.linked_cases.length === 0 ? (
                  <p className="text-theme-text-secondary">
                    No linked support cases for this user.
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {profile.linked_cases.map((c) => (
                      <li
                        key={c.case_id}
                        className="rounded border border-theme-border px-2 py-1 font-mono text-[11px]"
                      >
                        {c.external_ref ?? c.case_id} · {c.status} · rev {c.revision}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          )}
        </>
      )}
    </section>
  );
}
