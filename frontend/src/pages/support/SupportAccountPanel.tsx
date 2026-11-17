import { useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPost, supportRequest } from '../../api/support';
import { SupportBusinessActionRequest } from './SupportBusinessActionsPanel';

type Account = components['schemas']['SupportAccountRead'];

export function SupportAccountPanel({ onExpired, canRequest, canExplain }: {
  onExpired: () => void; canRequest: boolean; canExplain: boolean;
}) {
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [selector, setSelector] = useState('reference');

  async function lookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const values = new FormData(event.currentTarget);
    const caseId = encodeURIComponent(String(values.get('account_case')));
    const value = String(values.get('account_selector_value')).trim();
    const path = '/cases/' + caseId + '/accounts';
    setAccount(null);
    setError('');
    setPending(true);
    try {
      const response = selector === 'reference'
        ? await supportRequest(value ? path + '/' + encodeURIComponent(value) : path)
        : await supportPost(path + '/search', { field: selector, value });
      if (response.status === 401) onExpired();
      else if (!response.ok) setError('The approved case account could not be loaded.');
      else setAccount(await response.json() as Account);
    } catch {
      setError('The approved case account could not be loaded.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Case account" className="space-y-2 border-t pt-3">
      <h2 className="font-semibold">Case account</h2>
      <form className="space-y-2" onSubmit={(event) => void lookup(event)} onChange={() => setAccount(null)}>
        <label className="block">
          Case ID for account lookup
          <input name="account_case" maxLength={36} required disabled={pending}
            className="block w-full rounded border p-2" />
        </label>
        <label className="block">
          Match approved account by
          <select value={selector} onChange={(event) => setSelector(event.target.value)} disabled={pending}
            className="block w-full rounded border p-2">
            <option value="reference">Account reference</option>
            <option value="email">Verified email</option>
            <option value="employee_code">Employee code</option>
            <option value="name">Name</option>
            <option value="role">Business role key</option>
          </select>
        </label>
        <label className="block">
          {selector === 'reference' ? 'Approved account reference (optional)' : 'Account search value'}
          <input key={selector} name="account_selector_value" maxLength={selector === 'reference' ? 36 : 254}
            minLength={selector === 'name' ? 3 : undefined} required={selector !== 'reference'}
            disabled={pending} autoComplete="off"
            className="block w-full rounded border p-2" />
        </label>
        <button type="submit" disabled={pending}>Look up case account</button>
      </form>
      {error && <p role="alert">{error}</p>}
      {pending && <p role="status">Looking up account…</p>}
      {account && (
        <section aria-label="Masked account details">
          <h3 className="font-semibold">{account.display_name}</h3>
          <p>{account.email_masked}</p>
          {account.employee_code && <p>Employee code {account.employee_code}</p>}
          <p>{account.role.replace(/_/g, ' ')} · {account.deleted ? 'Deleted' : account.active ? 'Active' : 'Inactive'}</p>
          {account.locked && <p>Sign-in locked</p>}
          {typeof account.recovery_destination_verified === 'boolean' && (
            <p>
              {account.recovery_destination_verified
                ? 'Recovery destination verified' : 'No verified recovery destination'}
            </p>
          )}
          <p>Access revision {account.access_revision}</p>
          {account.membership_ids.length > 0 && (
            <details>
              <summary>Approved case project memberships</summary>
              <ul>{account.membership_ids.map((membership) => <li key={membership}>{membership}</li>)}</ul>
            </details>
          )}
          {account.permissions.length > 0 && (
            <details>
              <summary>Role permissions</summary>
              <ul>{account.permissions.map((permission) => <li key={permission}>{permission}</li>)}</ul>
            </details>
          )}
          <h4 className="mt-2 font-medium">Recent authentication events</h4>
          {account.recent_auth_events.length === 0 ? <p>No recent events.</p> : (
            <ul>{account.recent_auth_events.map((event) => (
              <li key={event.id}>
                <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString()}</time>
                {' · '}{event.category.replace(/_/g, ' ')}
              </li>
            ))}</ul>
          )}
          {(canRequest || canExplain) && <SupportBusinessActionRequest
            key={JSON.stringify([account.user_id, account.case_revision, account.access_revision, canRequest, canExplain])}
            account={account} onExpired={onExpired} canChangeAccount={canRequest} canExplain={canExplain} />}
        </section>
      )}
    </section>
  );
}
