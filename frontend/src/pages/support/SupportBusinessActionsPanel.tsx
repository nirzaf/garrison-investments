import { useRef, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPasskey, supportPost } from '../../api/support';

type Account = components['schemas']['SupportAccountRead'];
type Request = components['schemas']['BusinessActionCreate'];
type Receipt = components['schemas']['BusinessActionRead'];
type Proof = components['schemas']['BusinessActionProofOptions'];
type Stage = 'review' | 'execute';

const actions: Record<Request['kind'], string> = {
  revoke_sessions: 'Revoke sessions and pending sign-in challenges',
  unlock: 'Clear failed sign-in lock',
  disable: 'Disable business sign-in',
  reactivate: 'Reactivate business sign-in',
  recover: 'Queue account recovery',
  permission_view: 'Explain a role permission',
  navigation_view: 'Inspect portal navigation',
  project_list: 'Inspect masked project list',
  project_detail: 'Inspect masked project detail',
  portal_preview: 'View as User (read-only)',
  request_summary: 'Summarize a linked request'
};
const viewKinds = new Set<Request['kind']>([
  'permission_view', 'navigation_view', 'request_summary', 'project_list', 'project_detail', 'portal_preview'
]);
const uuidPattern = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';

function actionError(status: number) {
  if (status === 403 || status === 404) return 'This action is unavailable to your operator account.';
  if (status === 409) return 'The action is stale or lacks the required independent approvals.';
  return 'The business account action could not be completed.';
}

export function SupportBusinessActionRequest({ account, onExpired, canChangeAccount, canExplain }: {
  account: Account; onExpired: () => void; canChangeAccount: boolean; canExplain: boolean;
}) {
  const [kind, setKind] = useState<Request['kind']>(canChangeAccount ? 'revoke_sessions' : 'permission_view');
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const submission = useRef<{ body: string; key: string } | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const fields = new FormData(event.currentTarget);
    const request: Request = {
      kind,
      reason_code: kind === 'request_summary' ? 'request_triage'
        : viewKinds.has(kind) ? 'permission_triage'
        : String(fields.get('business_reason_code')) as Request['reason_code'],
      ...(kind === 'permission_view' ? { permission_key: String(fields.get('permission_key')).trim() } : {}),
      ...(kind === 'request_summary' ? { source_event_id: String(fields.get('source_event_id')).trim() } : {}),
      ...(kind === 'project_detail' ? { project_id: String(fields.get('project_id')).trim() } : {}),
      reason: String(fields.get('business_reason')),
      case_revision: account.case_revision,
      user_revision: account.access_revision,
      user_id: account.user_id
    };
    const body = JSON.stringify(request);
    const key = submission.current?.body === body ? submission.current.key : crypto.randomUUID();
    submission.current = { body, key };
    setPending(true);
    setError('');
    setReceipt(null);
    try {
      const response = await supportPost('/cases/' + account.case_id + '/account-actions', request, {
        headers: { 'Idempotency-Key': key }
      });
      if (response.status === 401) onExpired();
      else if (!response.ok) setError(actionError(response.status));
      else setReceipt(await response.json() as Receipt);
    } catch {
      setError('The account action could not be requested. Try the same request again.');
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="space-y-2 border-t pt-3" aria-label="Request account action"
      onSubmit={(event) => void submit(event)}>
      <h4 className="font-semibold">Request account action</h4>
      <label className="block">
        Business account action
        <select name="business_action" className="block rounded border p-2" value={kind} disabled={pending}
          onChange={(event) => {
            setKind(event.target.value as Request['kind']);
            setReceipt(null);
            setError('');
          }}>
          {Object.entries(actions)
            .filter(([value]) => viewKinds.has(value as Request['kind']) ? canExplain
              : canChangeAccount && (value !== 'recover' || account.recovery_destination_verified))
            .map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      {kind === 'permission_view' ? (
        <label className="block">
          Business permission key
          <input name="permission_key" required maxLength={64} className="block w-full rounded border p-2" />
        </label>
      ) : kind === 'request_summary' ? (
        <label className="block">
          Reviewed request event reference
          <input name="source_event_id" required pattern={uuidPattern}
            className="block w-full rounded border p-2" />
        </label>
      ) : kind === 'project_detail' ? (
        <label className="block">
          Approved case project reference
          <input name="project_id" required pattern={uuidPattern} className="block w-full rounded border p-2" />
        </label>
      ) : !viewKinds.has(kind) && <label className="block">
        Reason category
        <select name="business_reason_code" className="block rounded border p-2">
          <option value="suspected_access">Suspected access</option>
          <option value="verified_user_report">Verified user report</option>
          <option value="failed_sign_in">Failed sign-in</option>
        </select>
      </label>}
      <label className="block">
        Operational reason
        <textarea name="business_reason" required minLength={10} maxLength={300}
          className="block w-full rounded border p-2" />
      </label>
      <button type="submit" disabled={pending}>Request reviewed account action</button>
      {error && <p role="alert">{error}</p>}
      {receipt && <p role="status" className="break-all">
        Account action reference <code aria-label="New account action reference">{receipt.id}</code>
      </p>}
    </form>
  );
}

export function SupportBusinessActionReview({
  onExpired, canRecordContact, portalRequest, onPortalPreview
}: {
  onExpired: () => void;
  canRecordContact: boolean;
  portalRequest?: { caseId: string; actionId: string };
  onPortalPreview?: (viewId: string) => void;
}) {
  const [preview, setPreview] = useState<{ path: string; stage: Stage; proof: Proof } | null>(null);
  const [error, setError] = useState('');
  const [result, setResult] = useState('');
  const [pending, setPending] = useState(false);

  async function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const fields = new FormData(event.currentTarget);
    const caseId = encodeURIComponent(String(fields.get('business_case_id')));
    const actionId = encodeURIComponent(String(fields.get('business_action_id')));
    const stage = String(fields.get('business_stage')) as Stage;
    const contactRef = String(fields.get('offline_contact_ref') ?? '').trim();
    const path = '/cases/' + caseId + '/account-actions/' + actionId + '/' + stage;
    setPending(true);
    setError('');
    setResult('');
    setPreview(null);
    try {
      const response = await supportPost(path + '/options', contactRef ? { contact_ref: contactRef } : {});
      if (response.status === 401) onExpired();
      else if (!response.ok) setError(actionError(response.status));
      else {
        const proof = await response.json() as Proof;
        if (portalRequest && proof.proposal.kind !== 'portal_preview') {
          setError('This authorization does not cover a portal preview.');
        } else {
          setPreview({ path, stage, proof });
        }
      }
    } catch {
      setError('The account action could not be prepared.');
    } finally {
      setPending(false);
    }
  }

  async function confirm() {
    if (!preview || pending) return;
    setPending(true);
    setError('');
    setPreview(null);
    try {
      const response = await supportPost(preview.path, {
        ...await supportPasskey(preview.proof),
        expected_digest: preview.proof.proposal.digest,
        expected_contact_ref: preview.proof.contact_ref ?? null
      });
      if (response.status === 401) onExpired();
      else if (!response.ok) setError(actionError(response.status));
      else if (preview.stage === 'review') setResult('Independent account review recorded.');
      else if (preview.proof.proposal.kind === 'portal_preview') {
        onPortalPreview?.(preview.proof.proposal.id);
        setResult('Portal preview authorized.');
      } else if (preview.proof.proposal.kind === 'recover') setResult('Recovery queued. Delivery is pending.');
      else setResult('Account action applied.');
    } catch {
      setError('The account action could not be confirmed. Prepare a fresh proof.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Review account action" className="space-y-2 border-t pt-3">
      <h2 className="font-semibold">Review account action</h2>
      <form className="space-y-2" onSubmit={(event) => void prepare(event)} onChange={() => setPreview(null)}>
        <label className="block">
          Case ID for account action
          <input name="business_case_id" readOnly={Boolean(portalRequest)} defaultValue={portalRequest?.caseId} required maxLength={36} className="block w-full rounded border p-2" />
        </label>
        <label className="block">
          Account action reference
          <input name="business_action_id" readOnly={Boolean(portalRequest)} defaultValue={portalRequest?.actionId} required maxLength={36} className="block w-full rounded border p-2" />
        </label>
        <label className="block">
          Account action stage
          <select name="business_stage" className="block rounded border p-2">
            {!portalRequest && <option value="review">Independently review</option>}
            <option value="execute">Execute approved or owner-authorized action</option>
          </select>
        </label>
        {canRecordContact && <label className="block">
          Verified offline owner-contact reference (protected review only)
          <input name="offline_contact_ref" maxLength={36}
            pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
            className="block w-full rounded border p-2" />
        </label>}
        <button type="submit" disabled={pending}>Load account action</button>
      </form>
      {preview && (
        <section aria-label="Confirm account action" className="space-y-2 border-t pt-3">
          <h3 className="font-semibold">{actions[preview.proof.proposal.kind]}</h3>
          <p className="break-all">Account {preview.proof.proposal.user_id}</p>
          {preview.proof.proposal.permission_key && (
            <p>Permission <code>{preview.proof.proposal.permission_key}</code></p>
          )}
          {preview.proof.proposal.source_event_id && (
            <p className="break-all">Request event {preview.proof.proposal.source_event_id}</p>
          )}
          {preview.proof.proposal.project_id && (
            <p className="break-all">Approved case project {preview.proof.proposal.project_id}</p>
          )}
          <p>{preview.proof.proposal.reason}</p>
          {preview.proof.proposal.authorization_mode === 'single_owner'
            ? <p>Confirm this action with your passkey in the session that proposed it.</p>
            : <p>Required independent reviews {preview.proof.required_reviews}</p>}
          {preview.proof.contact_ref && (
            <p className="break-all">
              Your approval attests that you verified offline owner contact under reference{' '}
              <code>{preview.proof.contact_ref}</code>.
            </p>
          )}
          <button type="button" disabled={pending} onClick={() => void confirm()}>
            {preview.stage === 'review' ? 'Approve account action with passkey' : 'Execute account action with passkey'}
          </button>
        </section>
      )}
      {error && <p role="alert">{error}</p>}
      {result && <p role="status">{result}</p>}
    </section>
  );
}
