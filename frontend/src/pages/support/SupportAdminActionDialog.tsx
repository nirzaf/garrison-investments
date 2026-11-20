import { useRef, useState } from 'react';

import type { components, paths } from '../../api/schema';
import { supportPasskey, supportPost, supportRequest } from '../../api/support';
import { buttonClass, panelCardClass } from './supportPanelUtils';

type PlanRequest =
  paths['/api/v1/support/company/commands/plan']['post']['requestBody']['content']['application/json'];
type CommandRead = components['schemas']['SupportAdminCommandRead'];
type ProofOptions = components['schemas']['SupportAdminCommandProofOptions'];

function describeCommandError(status: number, fallback: string) {
  if (status === 401) return 'Your technical session expired. Sign in again.';
  if (status === 403)
    return 'This operation is denied by technical capability or protected-target policy.';
  if (status === 404) return 'The requested target or resource could not be found.';
  if (status === 409)
    return 'The target changed, the proof expired, or an anti-lockout rule blocked this change.';
  if (status === 422) return 'Check the required fields and policy constraints before continuing.';
  return fallback;
}

export function SupportAdminActionDialog({
  title,
  description,
  buildRequest,
  onExpired,
  onCompleted,
  onCancel
}: {
  title: string;
  description: string;
  buildRequest: () => PlanRequest | null;
  onExpired: () => void;
  onCompleted: (receipt: CommandRead) => void;
  onCancel: () => void;
}) {
  const [planned, setPlanned] = useState<CommandRead | null>(null);
  const [receipt, setReceipt] = useState<CommandRead | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const planKeyRef = useRef<{ payload: string; key: string } | null>(null);

  async function requestPreview() {
    if (pending) return;
    const payload = buildRequest();
    if (!payload) {
      setError(
        'Complete all required fields and provide an operational reason (at least 10 characters).'
      );
      return;
    }
    const serialized = JSON.stringify(payload);
    const idempotencyKey =
      planKeyRef.current?.payload === serialized ? planKeyRef.current.key : crypto.randomUUID();
    planKeyRef.current = { payload: serialized, key: idempotencyKey };
    setPending(true);
    setError('');
    try {
      const response = await supportPost('/company/commands/plan', payload, {
        headers: { 'Idempotency-Key': idempotencyKey }
      });
      if (response.status === 401) {
        onExpired();
        return;
      }
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        setError(
          body?.detail ||
            describeCommandError(response.status, 'Command preview could not be created.')
        );
        return;
      }
      const command = (await response.json()) as CommandRead;
      setPlanned(command);
    } catch {
      setError('The server could not prepare the command preview. Try again.');
    } finally {
      setPending(false);
    }
  }

  async function confirmAndExecute() {
    if (!planned || pending) return;
    setPending(true);
    setError('');
    try {
      const optionsResp = await supportPost(
        `/company/commands/${planned.command_id}/proof/options`,
        {}
      );
      if (optionsResp.status === 401) {
        onExpired();
        return;
      }
      if (!optionsResp.ok) {
        const body = (await optionsResp.json().catch(() => null)) as { detail?: string } | null;
        setError(
          body?.detail ||
            describeCommandError(optionsResp.status, 'Passkey challenge could not be prepared.')
        );
        return;
      }
      const proofOptions = (await optionsResp.json()) as ProofOptions;
      const assertion = await supportPasskey(proofOptions);
      const execResp = await supportPost(`/company/commands/${planned.command_id}/execute`, {
        ...assertion,
        expected_plan_sha256: planned.plan_sha256
      });
      if (execResp.status === 401) {
        onExpired();
        return;
      }
      if (!execResp.ok) {
        const body = (await execResp.json().catch(() => null)) as { detail?: string } | null;
        setError(
          body?.detail ||
            describeCommandError(execResp.status, 'Command execution could not be completed.')
        );
        return;
      }
      const finished = (await execResp.json()) as CommandRead;
      setReceipt(finished);
      onCompleted(finished);
    } catch {
      // Reconcile receipt if response was lost after commit (V-30).
      try {
        const checkResp = await supportRequest(`/company/commands/${planned.command_id}`);
        if (checkResp.ok) {
          const current = (await checkResp.json()) as CommandRead;
          if (current.status !== 'planned') {
            setReceipt(current);
            onCompleted(current);
            return;
          }
        }
      } catch {
        // Ignore secondary fetch error and prompt operator.
      }
      setError(
        'Passkey verification or command execution was interrupted. Check the command status or try again.'
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label={title} className={`${panelCardClass} border-brand-600/40`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold">{title}</h3>
          <p className="text-xs text-theme-text-secondary">{description}</p>
        </div>
        <button type="button" className={buttonClass} disabled={pending} onClick={onCancel}>
          Close
        </button>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded border border-red-500/40 bg-red-500/10 p-2 text-xs text-red-700"
        >
          {error}
        </p>
      )}

      {receipt ? (
        <div
          role="status"
          aria-label="Command execution receipt"
          className="space-y-2 rounded border border-theme-border p-3 text-xs"
        >
          <p className="font-semibold">
            Outcome: <span className="uppercase">{receipt.status.replace(/_/g, ' ')}</span>
          </p>
          <p>
            Command ID: <code className="font-mono">{receipt.command_id}</code>
          </p>
          <p>
            Plan SHA-256: <code className="font-mono break-all">{receipt.plan_sha256}</code>
          </p>
          {receipt.result && (
            <div className="space-y-1">
              <p className="font-medium">Recorded result details:</p>
              <pre className="overflow-x-auto rounded bg-theme-main p-2 font-mono text-[11px]">
                {JSON.stringify(receipt.result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      ) : planned ? (
        <div
          aria-label="Command preview"
          className="space-y-3 rounded border border-theme-border p-3 text-xs"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-semibold">Review planned change before passkey confirmation</span>
            <span className="font-mono text-[11px] text-theme-text-secondary">
              Policy {planned.policy_version} · Mode: {planned.authorization_mode}
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded border border-theme-border p-2">
              <p className="font-medium text-theme-text-secondary">Current state (Before)</p>
              <pre className="mt-1 overflow-x-auto font-mono text-[11px]">
                {JSON.stringify(planned.before, null, 2)}
              </pre>
            </div>
            <div className="rounded border border-theme-border p-2">
              <p className="font-medium text-theme-text-secondary">Proposed state (After)</p>
              <pre className="mt-1 overflow-x-auto font-mono text-[11px]">
                {JSON.stringify(planned.after, null, 2)}
              </pre>
            </div>
          </div>
          <div>
            <p className="font-medium">Consequences & boundaries:</p>
            <ul className="mt-1 list-disc pl-5 space-y-0.5">
              {planned.effects.map((effect) => (
                <li key={effect}>{effect.replace(/_/g, ' ')}</li>
              ))}
              {planned.denied_conditions.map((cond) => (
                <li key={cond} className="text-theme-text-secondary">
                  {cond}
                </li>
              ))}
            </ul>
          </div>
          <p className="font-mono text-[11px] text-theme-text-secondary break-all">
            Plan digest: {planned.plan_sha256}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded bg-brand-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              disabled={pending}
              onClick={() => void confirmAndExecute()}
            >
              {pending ? 'Verifying passkey…' : 'Confirm and execute with passkey'}
            </button>
            <button
              type="button"
              className={buttonClass}
              disabled={pending}
              onClick={() => setPlanned(null)}
            >
              Edit parameters
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded bg-brand-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
            disabled={pending}
            onClick={() => void requestPreview()}
          >
            {pending ? 'Preparing preview…' : 'Preview administrative change'}
          </button>
        </div>
      )}
    </section>
  );
}
