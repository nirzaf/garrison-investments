import { useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPasskey, supportPost } from '../../api/support';

type Grant = components['schemas']['GrantChangeRequest'];
type SuspensionOptions = components['schemas']['SuspensionOptions'];
type GrantOptions = components['schemas']['GrantChangeOptions'];
type RegistrationOptions = components['schemas']['RegistrationProofOptions'];
type ProposalKind = 'suspensions' | 'grant-changes' | 'enroll' | 'recover';
type Stage = 'review' | 'execute';

const labels: Record<Grant['capability'], string> = {
  'cases.manage': 'Manage support cases',
  'logs.runtime': 'Read assigned runtime evidence',
  'logs.stream': 'Follow approved live evidence',
  'logs.export': 'Request and review case evidence exports',
  'health.read': 'Read service health',
  'directory.read': 'Read approved case account',
  'account.request': 'Request and review business account actions',
  'logs.audit': 'Read redacted assigned-case audit',
  'simulation.start': 'Open reviewed permission explanations',
  'overview.company.read': 'Read company oversight summary',
  'overview.projects.read': 'Read construction projects oversight',
  'overview.workforce.read': 'Read suppressed workforce overview',
  'overview.inventory.read': 'Read inventory and material oversight',
  'overview.suppliers.read': 'Read supplier compliance oversight',
  'overview.documents.read': 'Read document governance overview',
  'overview.finance.read': 'Read finance counts overview (no amounts)',
  'overview.approvals.read': 'Read approval queue overview',
  'jobs.read': 'Read job and scheduler monitor',
  'backups.read': 'Read backup and restore provenance',
  'config.read': 'Read allowlisted configuration status',
  'incidents.read': 'Read sanitized security incident summary',
  'company.directory.read': 'Read company-wide people directory and User 360 profile',
  'company.accounts.manage': 'Manage business account creation, state, locks, and recovery',
  'company.access.assign': 'Assign business roles and project memberships',
  'company.sessions.read': 'Read business user session inventory metadata',
  'company.sessions.revoke': 'Revoke selected or all business sessions',
  'company.settings.manage': 'Update allowlisted safe operational settings',
  'company.jobs.retry': 'Retry allowlisted terminal failed jobs',
  'company.data.inspect': 'Read registered non-sensitive data inspector entities'
};
const descriptions = {
  suspensions: 'Suspend operator',
  'grant-changes': 'Change capability',
  enroll: 'Enroll pending operator',
  recover: 'Recover suspended operator'
};
const uuidPattern = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';

export function SupportCustodyPanel({ onExpired }: { onExpired: () => void }) {
  const [kind, setKind] = useState<ProposalKind>('suspensions');
  const [proposal, setProposal] = useState('');
  const [stage, setStage] = useState<Stage>('review');
  const [preview, setPreview] = useState<{
    path: string;
    stage: Stage;
    options: SuspensionOptions | GrantOptions | RegistrationOptions;
  } | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [invitations, setInvitations] = useState<[string, string] | null>(null);
  const registration = kind === 'enroll' || kind === 'recover';

  function check(response: Response) {
    if (response.status === 401) {
      onExpired();
      return false;
    }
    if (response.status === 409) {
      setError('This proposal is no longer actionable. Check its stage or prepare a fresh proof.');
      return false;
    }
    if (response.status === 403) {
      setError('Your account cannot perform this action or the passkey proof was rejected.');
      return false;
    }
    if (!response.ok) throw new Error();
    return true;
  }

  async function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const fields = new FormData(event.currentTarget);
    setPending(true);
    setError('');
    setStatus('');
    setInvitations(null);
    setPreview(null);
    try {
      const target_id = String(fields.get('target'));
      const payload = registration
        ? { target_id, kind }
        : kind === 'suspensions'
          ? { target_id }
          : {
              target_id,
              capability: String(fields.get('capability')) as Grant['capability'],
              enable: fields.get('enable') === 'add'
            };
      const response = await supportPost(
        '/custody/' + (registration ? 'registrations' : kind),
        payload
      );
      if (!check(response)) return;
      const result = (await response.json()) as
        | components['schemas']['SuspensionRead']
        | components['schemas']['GrantChangeRead']
        | components['schemas']['RegistrationProposalRead'];
      if ('proposal_id' in result) setProposal(result.proposal_id);
      else setProposal('suspension_id' in result ? result.suspension_id : result.grant_change_id);
      setStatus('Proposal created. A different eligible custodian must review it.');
    } catch {
      setError('The proposal could not be created.');
    } finally {
      setPending(false);
    }
  }

  async function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError('');
    setStatus('');
    setInvitations(null);
    setPreview(null);
    const base = registration ? '/custody/registrations/' + kind : '/custody/' + kind;
    const path = base + '/' + encodeURIComponent(proposal) + '/' + stage;
    try {
      const response = await supportPost(path + '/options', {});
      if (!check(response)) return;
      setPreview({
        path,
        stage,
        options: (await response.json()) as SuspensionOptions | GrantOptions | RegistrationOptions
      });
    } catch {
      setError('The passkey proof could not be prepared.');
    } finally {
      setPending(false);
    }
  }

  async function confirm() {
    if (!preview || pending) return;
    setPending(true);
    setError('');
    const { path, stage: decision, options } = preview;
    setPreview(null);
    try {
      const response = await supportPost(path, await supportPasskey(options));
      if (!check(response)) return;
      if ('kind' in options) {
        const result = (await response.json()) as components['schemas']['RegistrationDecision'];
        if (result.invitations) setInvitations(result.invitations);
      }
      setStatus(
        decision === 'review' ? 'Independent review recorded.' : 'Custody decision applied.'
      );
    } catch {
      setError('The decision could not be confirmed. Prepare a new passkey proof.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Operator custody" className="space-y-4">
      <h2 className="font-semibold">Operator custody</h2>
      <label className="block">
        Custody action
        <select
          className="block rounded border p-2"
          value={kind}
          disabled={pending}
          onChange={(event) => {
            setKind(event.target.value as ProposalKind);
            setProposal('');
            setInvitations(null);
            setPreview(null);
            setError('');
            setStatus('');
          }}
        >
          <option value="suspensions">{descriptions.suspensions}</option>
          <option value="grant-changes">{descriptions['grant-changes']}</option>
          <option value="enroll">{descriptions.enroll}</option>
          <option value="recover">{descriptions.recover}</option>
        </select>
      </label>
      <form className="space-y-2" onSubmit={(event) => void propose(event)}>
        <label className="block">
          Target operator reference
          <input
            name="target"
            required
            pattern={uuidPattern}
            className="block w-full rounded border p-2"
          />
        </label>
        {kind === 'grant-changes' && (
          <>
            <label className="block">
              Capability
              <select name="capability" className="block rounded border p-2">
                {Object.entries(labels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              Grant change
              <select name="enable" className="block rounded border p-2">
                <option value="add">Grant until revoked</option>
                <option value="remove">Revoke</option>
              </select>
            </label>
          </>
        )}
        <button type="submit" disabled={pending}>
          Create custody proposal
        </button>
      </form>
      <form className="space-y-2" onSubmit={(event) => void prepare(event)}>
        <label className="block">
          Proposal reference
          <input
            className="block w-full rounded border p-2"
            value={proposal}
            required
            pattern={uuidPattern}
            onChange={(event) => {
              setProposal(event.target.value);
              setPreview(null);
            }}
          />
        </label>
        <label className="block">
          Decision
          <select
            className="block rounded border p-2"
            value={stage}
            onChange={(event) => {
              setStage(event.target.value as Stage);
              setPreview(null);
            }}
          >
            <option value="review">Review proposal</option>
            <option value="execute">Execute approved proposal</option>
          </select>
        </label>
        <button type="submit" disabled={pending}>
          Prepare passkey proof
        </button>
      </form>
      {preview && (
        <section aria-label="Confirm custody decision" className="space-y-2 border-t pt-3">
          <p className="break-all">Target operator {preview.options.target_id}</p>
          {'capability' in preview.options ? (
            <p>
              {preview.options.enable ? 'Grant until revoked' : 'Revoke'} ·{' '}
              {labels[preview.options.capability]}
            </p>
          ) : 'kind' in preview.options ? (
            <p>{descriptions[preview.options.kind]}. Issue two one-use passkey invitations.</p>
          ) : (
            <p>Suspend operator and revoke their passkeys and sessions.</p>
          )}
          <button type="button" disabled={pending} onClick={() => void confirm()}>
            {preview.stage === 'review' ? 'Approve with passkey' : 'Execute with passkey'}
          </button>
        </section>
      )}
      {invitations && (
        <section aria-label="One-use registration invitations" className="space-y-2 border-t pt-3">
          <p>
            Deliver one invitation per verified device through the approved private channel. They
            expire in 10 minutes.
          </p>
          {invitations.map((invitation, index) => (
            <div key={index} className="flex gap-2">
              <input
                aria-label={'Invitation ' + (index + 1)}
                className="min-w-0 flex-1 rounded border p-2"
                type="password"
                readOnly
                value={invitation}
              />
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard
                    .writeText(invitation)
                    .then(() => setStatus('Invitation copied.'))
                    .catch(() =>
                      setError('Clipboard unavailable. Select the invitation to copy it.')
                    );
                }}
              >
                Copy invitation {index + 1}
              </button>
            </div>
          ))}
          <button type="button" onClick={() => setInvitations(null)}>
            Hide invitations
          </button>
        </section>
      )}
      {pending && <p role="status">Working…</p>}
      {status && <p role="status">{status}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
