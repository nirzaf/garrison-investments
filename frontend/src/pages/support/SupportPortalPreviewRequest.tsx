import { useRef, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPost } from '../../api/support';
import { SupportBusinessActionReview } from './SupportBusinessActionsPanel';
import { buttonClass, inputClass, panelCardClass } from './supportPanelUtils';

type Profile = components['schemas']['SupportCompanyUserProfileRead'];
type Case = components['schemas']['SupportLinkedCaseSummary'];
type Action = components['schemas']['BusinessActionRead'];

export function SupportPortalPreviewRequest({
  profile,
  canLinkCase,
  onExpired,
  onPortalPreview
}: {
  profile: Profile;
  canLinkCase: boolean;
  onExpired: () => void;
  onPortalPreview: (viewId: string) => void;
}) {
  const [linked, setLinked] = useState<Case | null>(null);
  const cases = profile.linked_cases.filter(
    (item) => item.case_id !== linked?.case_id && ['open', 'investigating'].includes(item.status)
  );
  if (linked) cases.push(linked);
  const [caseId, setCaseId] = useState(cases[0]?.case_id ?? '');
  const [reason, setReason] = useState('');
  const [action, setAction] = useState<Action | null>(null);
  const [isPending, setPending] = useState(false);
  const [error, setError] = useState('');
  const attempt = useRef<{ body: string; key: string } | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isPending || reason.trim().length < 10) return;
    setError('');
    setPending(true);
    try {
      let chosen = cases.find((item) => item.case_id === caseId);
      if (!chosen && canLinkCase && !caseId) {
        const linkedResponse = await supportPost(
          `/company/users/${profile.user_id}/diagnose-case`,
          { reason: reason.trim() }
        );
        if (linkedResponse.status === 401) return onExpired();
        if (!linkedResponse.ok) {
          const detail: { detail?: string } | null = await linkedResponse.json().catch(() => null);
          setError(
            detail?.detail ?? 'A support case could not be opened or linked for this account.'
          );
          return;
        }
        const data =
          (await linkedResponse.json()) as components['schemas']['SupportDiagnoseCaseRead'];
        chosen = { ...data, severity: null, reason_code: null };
        setLinked(chosen);
        setCaseId(chosen.case_id);
      }
      if (!chosen) {
        setError('Select an open or investigating case for this account.');
        return;
      }
      const payload: components['schemas']['BusinessActionCreate'] = {
        kind: 'portal_preview',
        reason_code: 'permission_triage',
        reason: reason.trim(),
        user_id: profile.user_id,
        user_revision: profile.access_revision,
        case_revision: chosen.revision
      };
      const body = JSON.stringify(payload);
      const key = attempt.current?.body === body ? attempt.current.key : crypto.randomUUID();
      attempt.current = { body, key };
      const response = await supportPost(`/cases/${chosen.case_id}/account-actions`, payload, {
        headers: { 'Idempotency-Key': key }
      });
      if (response.status === 401) return onExpired();
      if (!response.ok) {
        const detail: { detail?: string } | null = await response.json().catch(() => null);
        setError(detail?.detail ?? 'The preview request could not be created.');
        return;
      }
      setAction((await response.json()) as Action);
    } catch {
      setError('The preview request could not be sent. Try again.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Request read-only portal preview" className={panelCardClass}>
      <h3 className="font-semibold">View as {profile.full_name}</h3>
      <p className="text-sm text-theme-text-secondary">
        {profile.role_label} · Read-only, case-scoped access. Audit records identify you as the
        operator.
      </p>
      {!action ? (
        <form className="space-y-3" onSubmit={(event) => void submit(event)}>
          <label className="block text-sm">
            Support case
            <select
              className={inputClass}
              disabled={isPending}
              value={caseId}
              onChange={(event) => setCaseId(event.target.value)}
            >
              <option value="">
                {canLinkCase ? 'Open or link a support case' : 'Select a linked case'}
              </option>
              {cases.map((item) => (
                <option value={item.case_id} key={item.case_id}>
                  {item.external_ref ?? item.case_id}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            Investigation reason
            <textarea
              className={inputClass}
              required
              minLength={10}
              maxLength={300}
              value={reason}
              disabled={isPending}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <button
            type="submit"
            className={buttonClass}
            disabled={isPending || (!caseId && !canLinkCase)}
          >
            {isPending ? 'Requesting…' : 'Request reviewed preview'}
          </button>
        </form>
      ) : (
        <>
          <p role="status" className="text-sm">
            {action.authorization_mode === 'single_owner'
              ? 'Awaiting your passkey confirmation.'
              : 'An independent operator must review this request in Support & Audit.'}
          </p>
          <p className="break-all text-xs">
            Case <code>{action.case_id}</code> · Authorization <code>{action.id}</code>
          </p>
          <SupportBusinessActionReview
            canRecordContact={false}
            onExpired={onExpired}
            onPortalPreview={onPortalPreview}
            portalRequest={{ caseId: action.case_id, actionId: action.id }}
          />
        </>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}
    </section>
  );
}
