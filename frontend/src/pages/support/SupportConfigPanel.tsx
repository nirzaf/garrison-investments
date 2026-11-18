import { useEffect, useRef, useState } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import { buttonClass, formatObserved, panelCardClass, statusLabel } from './supportPanelUtils';

type ConfigStatus = components['schemas']['SupportConfigStatusRead'];

export function SupportConfigPanel({ onExpired }: { onExpired: () => void }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<ConfigStatus | null>(null);
  const active = useRef<AbortController | null>(null);

  useEffect(() => () => active.current?.abort(), []);

  async function load() {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setPending(true);
    setError('');
    try {
      const response = await supportRequest('/config/status', { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (response.status === 403) {
        setError('Runtime configuration status is unavailable to your operator account.');
        return;
      }
      if (!response.ok) throw new Error();
      const payload = (await response.json()) as ConfigStatus;
      if (!controller.signal.aborted) setData(payload);
    } catch {
      if (!controller.signal.aborted) {
        setData(null);
        setError('Configuration status could not be loaded.');
      }
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  return (
    <section aria-label="Safe runtime configuration status" className={panelCardClass}>
      <h2 className="font-semibold">Safe runtime configuration status</h2>
      <button type="button" className={buttonClass} disabled={pending} onClick={() => void load()}>
        {pending ? 'Checking…' : 'Check configuration posture'}
      </button>
      {error && <p role="alert" className="text-sm">{error}</p>}
      {data && (
        <div className="space-y-2 text-xs">
          <dl className="grid gap-2 sm:grid-cols-2">
            <div><dt className="text-theme-text-secondary">Environment</dt><dd>{data.app_env}</dd></div>
            <div><dt className="text-theme-text-secondary">Commit SHA</dt><dd className="font-mono">{data.source_sha}</dd></div>
            <div><dt className="text-theme-text-secondary">Currency / Timezone</dt><dd>{data.business_currency} · {data.business_timezone}</dd></div>
            <div><dt className="text-theme-text-secondary">Audit purge disabled</dt><dd>{data.audit_purge_disabled ? 'Enforced' : 'Disabled'}</dd></div>
            <div><dt className="text-theme-text-secondary">Mail transport</dt><dd>{data.mail_configured ? 'Configured' : 'Not configured'}</dd></div>
            <div><dt className="text-theme-text-secondary">Support recovery delivery</dt><dd>{data.support_recovery_delivery_enabled ? 'Enabled' : 'Disabled'}</dd></div>
            <div><dt className="text-theme-text-secondary">Support custody mode</dt><dd>{data.support_custody_mode === 'single_owner' ? 'Single-owner' : data.support_custody_mode === 'paired' ? 'Paired custodian' : 'Unknown'}</dd></div>
            <div><dt className="text-theme-text-secondary">Technical OTP config</dt><dd>{data.support_email_otp_configured ? `Ready (${data.support_otp_recipient_count} recipients)` : 'Unconfigured'}</dd></div>
            <div><dt className="text-theme-text-secondary">TLS certificate</dt><dd>{statusLabel(data.tls_status)}{data.tls_not_after ? ` (expires ${formatObserved(data.tls_not_after)})` : ''}</dd></div>
          </dl>
          <p className="text-theme-text-secondary">
            Change control: <code>{data.change_control_reference}</code> · Observed{' '}
            <time dateTime={data.observed_at}>{formatObserved(data.observed_at)}</time>
          </p>
        </div>
      )}
    </section>
  );
}
