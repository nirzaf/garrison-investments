import { useCallback, useEffect, useState } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import { SupportCustodyPanel } from './SupportCustodyPanel';
import { buttonClass, formatObserved, panelCardClass } from './supportPanelUtils';

type OwnerSecurityRead = components['schemas']['SupportOwnerSecurityRead'];

export function SupportOwnerSecurityPanel({
  canManageOperators,
  onExpired
}: {
  canManageOperators: boolean;
  onExpired: () => void;
}) {
  const [data, setData] = useState<OwnerSecurityRead | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setPending(true);
    setError('');
    try {
      const resp = await supportRequest('/company/owner-security');
      if (resp.status === 401) {
        onExpired();
        return;
      }
      if (!resp.ok) {
        setError('Owner security posture could not be loaded.');
        return;
      }
      setData((await resp.json()) as OwnerSecurityRead);
    } catch {
      setError('Owner security posture could not be loaded.');
    } finally {
      setPending(false);
    }
  }, [onExpired]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <section aria-label="Owner security posture" className={panelCardClass}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold">Owner Security & Enrolled Devices</h2>
            <p className="text-xs text-theme-text-secondary">
              Technical session assurance, enrolled WebAuthn passkeys, and custody guidance.
            </p>
          </div>
          <button
            type="button"
            className={buttonClass}
            disabled={pending}
            onClick={() => void load()}
          >
            {pending ? 'Checking…' : 'Refresh security posture'}
          </button>
        </div>

        {error && (
          <p role="alert" className="text-xs text-red-700">
            {error}
          </p>
        )}

        {data && (
          <div className="space-y-3 text-xs">
            <dl className="grid gap-2 sm:grid-cols-3">
              <div>
                <dt className="text-theme-text-secondary">Operator label & status</dt>
                <dd className="font-medium">
                  {data.display_label} ({data.status} · epoch {data.grant_epoch})
                </dd>
              </div>
              <div>
                <dt className="text-theme-text-secondary">Custody mode</dt>
                <dd className="font-medium">
                  {data.custody_mode === 'single_owner'
                    ? 'Single-owner custody'
                    : data.custody_mode === 'paired'
                      ? 'Paired custodian'
                      : 'Unknown'}
                </dd>
              </div>
              <div>
                <dt className="text-theme-text-secondary">Current session assurance</dt>
                <dd className="font-medium uppercase">{data.session_auth_method}</dd>
              </div>
              <div>
                <dt className="text-theme-text-secondary">Active enrolled passkeys</dt>
                <dd className="font-medium">
                  {data.active_passkey_count} (minimum required: {data.minimum_passkeys_required})
                </dd>
              </div>
              <div>
                <dt className="text-theme-text-secondary">Session idle deadline</dt>
                <dd className="font-medium">{formatObserved(data.session_idle_deadline)}</dd>
              </div>
              <div>
                <dt className="text-theme-text-secondary">Session absolute expiry</dt>
                <dd className="font-medium">{formatObserved(data.session_expires_at)}</dd>
              </div>
            </dl>

            <div>
              <h3 className="font-semibold">Enrolled hardware / device-bound passkeys</h3>
              <ul className="mt-1 space-y-1">
                {data.passkeys.map((pk) => (
                  <li
                    key={pk.credential_id}
                    className="flex flex-wrap items-center justify-between rounded border border-theme-border px-2 py-1 font-mono text-[11px]"
                  >
                    <span>
                      Key <code>{pk.credential_hash_prefix}…</code> · status: {pk.status} · sign
                      count: {pk.sign_count}
                    </span>
                    <span>Enrolled {formatObserved(pk.created_at)}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <h3 className="font-semibold">Owner custody & recovery guardrails</h3>
              <ul className="mt-1 list-disc pl-5 space-y-0.5 text-theme-text-secondary">
                {data.recovery_guidance.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>

            <div>
              <h3 className="font-semibold">Recent technical authentication events</h3>
              <ul className="mt-1 space-y-1">
                {data.recent_auth_events.map((ev) => (
                  <li
                    key={ev.id}
                    className="flex justify-between rounded border border-theme-border px-2 py-1 text-[11px]"
                  >
                    <span className="font-medium">{ev.action}</span>
                    <span className="text-theme-text-secondary">
                      {formatObserved(ev.occurred_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </section>

      {canManageOperators && <SupportCustodyPanel onExpired={onExpired} />}
    </div>
  );
}
