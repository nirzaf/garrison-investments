import { useCallback, useEffect, useState } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import { SupportAdminActionDialog } from './SupportAdminActionDialog';
import { buttonClass, formatObserved, panelCardClass } from './supportPanelUtils';

type SafeSettingsRead = components['schemas']['SupportSafeSettingsRead'];
type SafeSettingItem = components['schemas']['SupportSafeSettingItem'];

export function SupportSafeSettingsPanel({
  canManage,
  onExpired,
  onUpdated
}: {
  canManage: boolean;
  onExpired: () => void;
  onUpdated?: () => void;
}) {
  const [data, setData] = useState<SafeSettingsRead | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<SafeSettingItem | null>(null);
  const [draftValue, setDraftValue] = useState('');
  const [reason, setReason] = useState('');

  const load = useCallback(async () => {
    setPending(true);
    setError('');
    try {
      const response = await supportRequest('/company/settings');
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (!response.ok) {
        setError('Allowlisted operational settings could not be loaded.');
        return;
      }
      setData((await response.json()) as SafeSettingsRead);
    } catch {
      setError('Allowlisted operational settings could not be loaded.');
    } finally {
      setPending(false);
    }
  }, [onExpired]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section aria-label="Allowlisted operational settings" className={panelCardClass}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-semibold">Allowlisted non-secret operational settings</h3>
          <p className="text-xs text-theme-text-secondary">
            Only registered display and paging settings can be edited. Security, secret, TLS, and
            audit retention parameters are permanently locked.
          </p>
        </div>
        <button
          type="button"
          className={buttonClass}
          disabled={pending}
          onClick={() => void load()}
        >
          {pending ? 'Loading…' : 'Refresh settings'}
        </button>
      </div>

      {error && (
        <p role="alert" className="text-xs text-red-700">
          {error}
        </p>
      )}

      {editing && canManage && (
        <div className="space-y-2 rounded border border-theme-border p-3 text-xs">
          <label className="block font-medium">
            {editing.label} ({editing.key}) · Current revision {editing.revision}
            <input
              type={editing.value_type === 'integer' ? 'number' : 'text'}
              aria-label={`New value for ${editing.key}`}
              value={draftValue}
              onChange={(e) => setDraftValue(e.target.value)}
              className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
            />
          </label>
          <label className="block font-medium">
            Operational reason (10–300 chars)
            <input
              type="text"
              aria-label="Setting change reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              minLength={10}
              maxLength={300}
              className="mt-1 block w-full rounded border border-theme-border bg-theme-card px-2 py-1"
            />
          </label>
          <SupportAdminActionDialog
            title={`Update ${editing.label}`}
            description={`Effect: ${editing.effect.replace(/_/g, ' ')}.`}
            onExpired={onExpired}
            onCancel={() => setEditing(null)}
            onCompleted={() => {
              setEditing(null);
              void load();
              onUpdated?.();
            }}
            buildRequest={() => {
              if (reason.trim().length < 10) return null;
              const val =
                editing.value_type === 'integer' ? Number.parseInt(draftValue, 10) : draftValue;
              if (editing.value_type === 'integer' && Number.isNaN(val)) return null;
              return {
                command_kind: 'update_safe_setting',
                setting_key: editing.key,
                expected_revision: editing.revision,
                value: val,
                reason_code: 'operational_configuration',
                reason: reason.trim()
              };
            }}
          />
        </div>
      )}

      {data && (
        <div className="space-y-3 text-xs">
          <ul className="space-y-2">
            {data.items.map((item) => (
              <li
                key={item.key}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-theme-border p-2"
              >
                <div>
                  <p className="font-medium">
                    {item.label} <code className="font-mono text-[11px]">({item.key})</code>
                  </p>
                  <p className="text-theme-text-secondary">{item.description}</p>
                  <p className="mt-0.5 font-mono text-[11px]">
                    Value: <strong>{String(item.current_value || '(empty)')}</strong> · Rev{' '}
                    {item.revision} · Effect: {item.effect}
                    {item.updated_at ? ` · Updated ${formatObserved(item.updated_at)}` : ''}
                  </p>
                </div>
                {canManage && (
                  <button
                    type="button"
                    className={buttonClass}
                    onClick={() => {
                      setEditing(item);
                      setDraftValue(String(item.current_value));
                      setReason('');
                    }}
                  >
                    Edit setting
                  </button>
                )}
              </li>
            ))}
          </ul>

          <div className="rounded border border-theme-border p-2">
            <p className="font-semibold">Permanently locked security & domain controls</p>
            <ul className="mt-1 list-disc pl-5 space-y-0.5 text-theme-text-secondary">
              {data.permanently_locked_controls.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}
