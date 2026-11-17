import { useEffect, useRef, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';

type Challenge = components['schemas']['SuperAdminChallenge'];
type Session = components['schemas']['SuperAdminToken'];
type Overview = components['schemas']['SuperAdminOverview'];

function portalRequest(path: string, options: RequestInit = {}) {
  return fetch('/api/v1/super-admin' + path, {
    ...options, credentials: 'omit', cache: 'no-store', redirect: 'error',
  });
}

function authenticate(path: string, body: object) {
  return portalRequest('/auth/' + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function SuperAdminPage() {
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [overviewFailure, setOverviewFailure] = useState(false);
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!challenge) return;
    const timer = window.setTimeout(() => {
      setChallenge(null);
      setError('The code expired. Sign in to request another code.');
    }, Math.max(0, Date.parse(challenge.expires_at) - Date.now()));
    return () => window.clearTimeout(timer);
  }, [challenge]);

  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSession(null);
      setOverview(null);
      setError('Your session expired. Sign in again.');
    }, Math.max(0, Date.parse(session.expires_at) - Date.now()));
    void portalRequest('/overview', {
      headers: { Authorization: 'Bearer ' + session.access_token },
      signal: controller.signal,
    }).then(async (response) => {
      if (response.status === 401 && !controller.signal.aborted) {
        setSession(null);
        setError('Your session ended. Sign in again.');
        return;
      }
      if (!response.ok) throw new Error();
      const result = await response.json() as Overview;
      if (!controller.signal.aborted) setOverview(result);
    }).catch(() => {
      if (!controller.signal.aborted) setOverviewFailure(true);
    });
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [session]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    busy.current = true;
    setPending(true);
    setError('');
    try {
      const response = await (challenge
        ? authenticate('verify-otp', { challenge_id: challenge.challenge_id, otp: fields.get('otp') })
        : authenticate('login', { email: fields.get('email'), password: fields.get('password') }));
      if (response.status === 429) {
        setError('Too many attempts. Wait before trying again.');
      } else if (response.status === 401) {
        setError(challenge
          ? 'The verification code could not be accepted.'
          : 'Check your credentials and try again.');
      } else if (!response.ok) {
        setError('Super Admin sign-in is unavailable.');
      } else if (challenge) {
        const result = await response.json() as Session;
        setChallenge(null);
        setOverviewFailure(false);
        setSession(result);
      } else {
        setChallenge(await response.json() as Challenge);
      }
    } catch {
      setError('Super Admin sign-in is unavailable.');
    } finally {
      form.reset();
      busy.current = false;
      setPending(false);
    }
  }

  async function signOut() {
    if (!session || busy.current) return;
    busy.current = true;
    setPending(true);
    try {
      const response = await portalRequest('/auth/logout', {
        method: 'POST', headers: { Authorization: 'Bearer ' + session.access_token },
      });
      if (!response.ok && response.status !== 401) throw new Error();
      setError('');
    } catch {
      setError('Signed out on this device. Server session revocation could not be confirmed.');
    } finally {
      setSession(null);
      setOverview(null);
      busy.current = false;
      setPending(false);
    }
  }

  const inputClass = 'mt-1 w-full rounded-md border border-theme-border bg-theme-card px-3 py-2';
  const buttonClass = 'rounded-md bg-brand-600 px-4 py-2 font-medium text-white disabled:opacity-50';

  return (
    <main className="flex min-h-screen items-center justify-center bg-theme-main px-4">
      <section className="w-full max-w-md space-y-5 rounded-lg border border-theme-border bg-theme-card p-6">
        <h1 className="text-2xl font-semibold">Garrisons Super Admin</h1>
        {error && <p role="alert">{error}</p>}
        {session ? (
          <>
            {overviewFailure && <p role="alert">The administration overview is unavailable.</p>}
            {!overview && !overviewFailure && <p role="status">Checking the administration API…</p>}
            {overview && (
              <dl>
                <dt>Administration API</dt>
                <dd>Available</dd>
                <dt>Last checked</dt>
                <dd><time dateTime={overview.observed_at}>{new Date(overview.observed_at).toLocaleString()}</time></dd>
              </dl>
            )}
            <button className={buttonClass} disabled={pending} onClick={() => void signOut()}>Sign out</button>
          </>
        ) : (
          <form className="space-y-4" key={challenge?.challenge_id ?? 'login'} onSubmit={(event) => void signIn(event)}>
            <fieldset className="space-y-4 disabled:opacity-70" disabled={pending}>
              {challenge ? (
                <>
                  <p>Enter the six-digit code sent to your operator mailbox.</p>
                  <label className="block">
                    Verification code
                    <input className={inputClass} name="otp" autoComplete="one-time-code"
                      required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} />
                  </label>
                </>
              ) : (
                <>
                  <label className="block">
                    Operator email
                    <input className={inputClass} name="email" type="email" required autoComplete="username" />
                  </label>
                  <label className="block">
                    Password
                    <input className={inputClass} name="password" type="password"
                      required autoComplete="current-password" />
                  </label>
                </>
              )}
              <button className={buttonClass} disabled={pending}>
                {challenge ? 'Verify code' : 'Send verification code'}
              </button>
              {challenge && (
                <button className="ml-3 underline" type="button" onClick={() => {
                  setError('');
                  setChallenge(null);
                }}>Start over</button>
              )}
            </fieldset>
          </form>
        )}
      </section>
    </main>
  );
}
