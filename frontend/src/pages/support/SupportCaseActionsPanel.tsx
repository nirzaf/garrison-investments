import { useId, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPasskey, supportPost } from '../../api/support';

type Case = components['schemas']['SupportCaseRead'];
type Proposal = components['schemas']['CaseActionRead'];
type Prepare = components['schemas']['CaseActionOptions'];
type Kind = Proposal['kind'];

const uuidPattern = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const labels: Record<Kind, string> = {
  member_add: 'Add case member',
  member_remove: 'Remove case member',
  evidence_link: 'Link request evidence',
  verify: 'Verify resolution',
  close: 'Close verified case',
  subject_set: 'Set reviewed case account',
  subject_remove: 'Remove reviewed case account',
  project_add: 'Add project to case scope',
  project_remove: 'Remove project from case scope'
};

function caseActionMessage(status: number) {
  if (status === 409) return 'The case or action changed. Reload the case or prepare a new proof.';
  if (status === 403 || status === 404) return 'This action is unavailable to your operator account.';
  return 'The case action could not be completed.';
}

export function SupportCaseProposal({ selected, onExpired, disabled, canReadDirectory, canReviewProjectScope }: {
  selected: Case; onExpired: () => void; disabled: boolean; canReadDirectory: boolean;
  canReviewProjectScope: boolean;
}) {
  const kinds: Kind[] = selected.status === 'verified' ? ['close']
    : selected.status === 'mitigated' ? ['member_add', 'member_remove', 'evidence_link', 'verify']
    : ['member_add', 'member_remove', 'evidence_link',
      ...(canReadDirectory ? (['subject_set', 'subject_remove'] as const) : []),
      ...(canReviewProjectScope ? (['project_add', 'project_remove'] as const) : [])];
  const actionSelectId = useId();
  const [requested, setRequested] = useState<Kind>(kinds[0]);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const kind = kinds.includes(requested) ? requested : kinds[0];
  const memberAction = kind === 'member_add' || kind === 'member_remove';
  const projectAction = kind === 'project_add' || kind === 'project_remove';
  const needsReference = kind !== 'close' && kind !== 'subject_remove';

  async function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const fields = new FormData(event.currentTarget);
    setPending(true);
    setMessage('');
    setProposal(null);
    try {
      const ref = String(fields.get('action_reference') ?? '');
      const payload = memberAction ? { kind, member_id: ref } : !needsReference ? { kind }
        : kind === 'subject_set' ? { kind, subject_user_id: ref }
        : projectAction ? { kind, project_id: ref } : { kind, source_event_id: ref };
      const response = await supportPost('/cases/' + selected.id + '/actions', payload, {
        headers: { 'If-Match': '"' + selected.revision + '"' }
      });
      if (response.status === 401) onExpired();
      else if (!response.ok) setMessage(caseActionMessage(response.status));
      else setProposal(await response.json() as Proposal);
    } catch {
      setMessage('The case action could not be proposed.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Propose case action" className="space-y-2 border-t pt-3">
      <h4 className="font-semibold">Propose case action</h4>
      <form className="space-y-2" onSubmit={(event) => void propose(event)}>
        <div>
          <label className="block" htmlFor={actionSelectId}>Case action</label>
          <select id={actionSelectId} className="block rounded border p-2" value={kind}
            disabled={disabled || pending} onChange={(event) => setRequested(event.target.value as Kind)}>
            {kinds.map((value) => <option key={value} value={value}>{labels[value]}</option>)}
          </select>
        </div>
        {needsReference && (
          <label className="block">
            {memberAction ? 'Member operator reference' : kind === 'subject_set' ? 'Account reference'
              : projectAction ? 'Project reference' : 'Source event reference'}
            <input key={kind} name="action_reference"
              className="block w-full rounded border p-2" pattern={uuidPattern} required />
          </label>
        )}
        <button type="submit" disabled={disabled || pending}>Prepare case decision</button>
      </form>
      {message && <p role="alert">{message}</p>}
      {proposal && <p role="status" className="break-all">
        Case {proposal.case_id}, proposal <code aria-label="Case proposal ID">{proposal.id}</code>.
        {proposal.authorization_mode === 'single_owner'
          ? ' Confirm this action with your registered passkey.'
          : ' Share these references with the independent case reviewer.'}
      </p>}
    </section>
  );
}

export function SupportCaseReview({ onExpired }: { onExpired: () => void }) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [success, setSuccess] = useState('');
  const [review, setReview] = useState<Prepare | null>(null);

  async function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const values = new FormData(event.currentTarget);
    setPending(true);
    setReview(null);
    setMessage('');
    setSuccess('');
    try {
      const caseId = encodeURIComponent(String(values.get('review_case')));
      const actionId = encodeURIComponent(String(values.get('review_action')));
      const response = await supportPost('/cases/' + caseId + '/actions/' + actionId + '/options', {});
      if (response.status === 401) onExpired();
      else if (!response.ok) setMessage(caseActionMessage(response.status));
      else setReview(await response.json() as Prepare);
    } catch {
      setMessage('The case action could not be loaded.');
    } finally {
      setPending(false);
    }
  }

  async function apply() {
    if (!review || pending) return;
    setPending(true);
    setMessage('');
    setReview(null);
    try {
      const { case_id, id } = review.proposal;
      const proof = await supportPasskey(review);
      const response = await supportPost('/cases/' + case_id + '/actions/' + id + '/apply', proof);
      if (response.status === 401) onExpired();
      else if (!response.ok) setMessage(caseActionMessage(response.status));
      else setSuccess('Case action applied.');
    } catch {
      setMessage('The case action could not be confirmed. Prepare a new passkey proof.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Review case action" className="space-y-2 border-t pt-3">
      <h2 className="font-semibold">Review case action</h2>
      <form className="space-y-2" onSubmit={(event) => void prepare(event)}
        onChange={() => setReview(null)}>
        <label className="block">
          Case ID for review
          <input name="review_case" pattern={uuidPattern} required
            className="block w-full rounded border p-2" />
        </label>
        <label className="block">
          Case proposal reference
          <input name="review_action" pattern={uuidPattern} required
            className="block w-full rounded border p-2" />
        </label>
        <button type="submit" disabled={pending}>Load case proposal</button>
      </form>
      {review && (
        <section aria-label="Confirm case action" className="space-y-2">
          <h3 className="font-semibold">{labels[review.proposal.kind]}</h3>
          <p className="break-all">Case {review.proposal.case_id} · Revision {review.proposal.case_revision}</p>
          {review.proposal.member_id && <p className="break-all">Member {review.proposal.member_id}</p>}
          {review.proposal.subject_user_id && (
            <p className="break-all">Business account {review.proposal.subject_user_id}</p>
          )}
          {review.proposal.project_id && (
            <p className="break-all">Project {review.proposal.project_id}</p>
          )}
          {review.proposal.source_event_id && (
            <p className="break-all">Source event {review.proposal.source_event_id}</p>
          )}
          {review.proposal.source_request_id && (
            <p className="break-all">
              Request {review.proposal.source_request_id} · HTTP {review.proposal.source_status ?? 'Unknown'}
            </p>
          )}
          <button type="button" disabled={pending} onClick={() => void apply()}>
            {review.proposal.authorization_mode === 'single_owner'
              ? 'Confirm case action as owner' : 'Approve case action with passkey'}
          </button>
        </section>
      )}
      {message && <p role="alert">{message}</p>}
      {success && <p role="status">{success}</p>}
    </section>
  );
}
