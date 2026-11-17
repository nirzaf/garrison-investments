import { useEffect, useRef, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportRequest } from '../../api/support';
import { buttonClass, formatObserved, inputClass, panelCardClass, uuidPattern } from './supportPanelUtils';

type PolicyExplain = components['schemas']['SupportPolicyExplainRead'];

const ROLE_OPTIONS = [
  ['managing_director', 'Managing Director'],
  ['operations_director', 'Operations Director'],
  ['group_project_manager', 'Group Project Manager'],
  ['mep_project_manager', 'MEP Project Manager'],
  ['quantity_surveyor', 'Quantity Surveyor'],
  ['senior_site_supervisor', 'Senior Site Supervisor'],
  ['site_supervisor', 'Site Supervisor'],
  ['hr_manager', 'HR Manager'],
  ['hr_executive_reader', 'HR Executive'],
  ['administrative_executive', 'Administrative Executive'],
  ['super_admin', 'Super Admin (reserved test role)']
] as const;

export function SupportPolicyExplainPanel({ onExpired }: { onExpired: () => void }) {
  const [roleKey, setRoleKey] = useState<string>('hr_executive_reader');
  const [permissionKey, setPermissionKey] = useState('reports:view');
  const [caseId, setCaseId] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<PolicyExplain | null>(null);
  const active = useRef<AbortController | null>(null);

  useEffect(() => () => active.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setPending(true);
    setError('');
    setResult(null);
    try {
      const params = new URLSearchParams({
        role_key: roleKey,
        permission_key: permissionKey.trim()
      });
      if (caseId.trim()) params.set('case_id', caseId.trim());
      const response = await supportRequest(`/policy/explain?${params}`, {
        signal: controller.signal
      });
      if (controller.signal.aborted) return;
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (response.status === 422) {
        setError('Specify a valid canonical role key and permission key.');
        return;
      }
      if (response.status === 403 || response.status === 404) {
        setError('Static policy explanation is unavailable for this scope.');
        return;
      }
      if (!response.ok) throw new Error();
      const payload = (await response.json()) as PolicyExplain;
      if (!controller.signal.aborted) setResult(payload);
    } catch {
      if (!controller.signal.aborted) setError('Policy explanation could not be loaded.');
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  return (
    <section aria-label="Role policy explainer" className={panelCardClass}>
      <h2 className="font-semibold">Role policy explainer</h2>
      <form onSubmit={(event) => void submit(event)} className="grid gap-2 sm:grid-cols-3">
        <label className="text-xs">
          Role
          <select
            value={roleKey}
            disabled={pending}
            onChange={(event) => {
              setRoleKey(event.target.value);
              setResult(null);
            }}
            className={inputClass}
          >
            {ROLE_OPTIONS.map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          Permission key
          <input
            value={permissionKey}
            required
            disabled={pending}
            onChange={(event) => {
              setPermissionKey(event.target.value);
              setResult(null);
            }}
            placeholder="e.g. financial:view"
            className={inputClass}
          />
        </label>
        <label className="text-xs">
          Optional case ID
          <input
            value={caseId}
            pattern={uuidPattern}
            disabled={pending}
            onChange={(event) => {
              setCaseId(event.target.value);
              setResult(null);
            }}
            placeholder="Optional audit scope"
            className={inputClass}
          />
        </label>
        <div className="sm:col-span-3">
          <button type="submit" className={buttonClass} disabled={pending}>
            {pending ? 'Evaluating…' : 'Explain policy rule'}
          </button>
        </div>
      </form>
      {error && <p role="alert" className="text-sm">{error}</p>}
      {result && (
        <div role="status" className="space-y-1 text-sm">
          <p className="font-medium">
            {result.role_label} ({result.permission_key}): {result.allowed ? 'Allowed' : 'Denied'}
          </p>
          <p className="text-xs text-theme-text-secondary">{result.reason}</p>
          <p className="text-xs text-theme-text-secondary">
            Observed <time dateTime={result.observed_at}>{formatObserved(result.observed_at)}</time>
          </p>
        </div>
      )}
    </section>
  );
}
