import { useCallback, useEffect, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportCsrf, supportPasskey, supportPost, supportRequest } from '../../api/support';
import { SupportCliLoginPanel } from '../support/SupportCliLoginPanel';
import { SupportCliProofPanel } from '../support/SupportCliProofPanel';
import { SupportOtpForm } from '../support/SupportOtpForm';
import { SupportRegistrationPanel } from '../support/SupportRegistrationPanel';
import { SupportShell } from '../support/SupportShell';

type LoginOptions = components['schemas']['SupportLoginOptions'];
type Session = components['schemas']['SupportProfile'];

function readCliReference() {
  if (typeof window === 'undefined') return null;
  if (window.location.hash === '#register') return ['', 'register', ''];
  return /^#(cli|proof)=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/.exec(
    window.location.hash
  );
}

export function SupportLoginPage() {
  const [cliReference, setCliReference] = useState(readCliReference);
  const [session, setSession] = useState<Session | null>(null);
  const [otpReference, setOtpReference] = useState<string | null>(null);
  const [otpOnlyLogin, setOtpOnlyLogin] = useState(false);
  const [pending, setPending] = useState(true);
  const [message, setMessage] = useState('');

  useEffect(() => {
    const change = () => setCliReference(readCliReference());
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);

  useEffect(() => {
    if (cliReference) return;
    const controller = new AbortController();
    void Promise.all([
      supportRequest('/me', { signal: controller.signal }),
      supportRequest('/auth/mode', { signal: controller.signal }).catch(() => null)
    ])
      .then(async ([meResponse, modeResponse]) => {
        if (modeResponse?.ok) {
          const mode = (await modeResponse.json()) as { otp_only_login?: boolean };
          if (!controller.signal.aborted) setOtpOnlyLogin(Boolean(mode.otp_only_login));
        }
        if (meResponse.ok) {
          const identity = (await meResponse.json()) as Session;
          if (!controller.signal.aborted) setSession(identity);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setMessage('Support sign-in is unavailable.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setPending(false);
      });
    return () => controller.abort();
  }, [cliReference]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const operatorId = new FormData(event.currentTarget).get('operator_id');
    setPending(true);
    setMessage('');
    try {
      if (otpOnlyLogin) {
        const result = await supportPost('/auth/request-otp', { operator_id: operatorId });
        if (result.status === 503) {
          setMessage('Verification email is unavailable. Start a new sign-in and try again.');
          return;
        }
        if (!result.ok) throw new Error();
        const signInResult = (await result.json()) as components['schemas']['SupportOtpRequired'];
        setOtpReference(signInResult.otp_reference);
        return;
      }
      const optionsResponse = await supportPost('/auth/options', { operator_id: operatorId });
      if (!optionsResponse.ok) throw new Error();
      const options = (await optionsResponse.json()) as LoginOptions;
      const result = await supportPost('/auth/verify', await supportPasskey(options));
      if (result.status === 503) {
        setMessage('Verification email is unavailable. Start a new sign-in and try again.');
        return;
      }
      if (!result.ok) throw new Error();
      const signInResult = (await result.json()) as
        components['schemas']['SupportSessionRead'] | components['schemas']['SupportOtpRequired'];
      if ('otp_reference' in signInResult) {
        setOtpReference(signInResult.otp_reference);
      } else {
        await loadProfile();
      }
    } catch {
      setMessage(
        otpOnlyLogin
          ? 'Sign-in code could not be sent. Check the operator reference and try again.'
          : 'The passkey could not be verified. Check the operator reference and try again.'
      );
    } finally {
      setPending(false);
    }
  }

  async function loadProfile() {
    const profile = await supportRequest('/me');
    if (!profile.ok) throw new Error();
    setSession((await profile.json()) as Session);
    setOtpReference(null);
  }

  async function signOut() {
    if (pending) return;
    setPending(true);
    setMessage('');
    try {
      const csrf = supportCsrf();
      const response = await supportRequest('/auth/logout', {
        method: 'POST',
        headers: csrf ? { 'X-Support-CSRF': csrf } : {}
      });
      if (!response.ok && response.status !== 401) throw new Error();
      setSession(null);
    } catch {
      setMessage('The server could not confirm sign-out. Try again.');
    } finally {
      setPending(false);
    }
  }

  const handleExpiry = useCallback(() => {
    setSession(null);
    setMessage('Your support session expired. Sign in again.');
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center bg-theme-main px-4 py-6">
      <section
        className={
          session
            ? 'w-full max-w-5xl space-y-4 rounded-lg border border-theme-border bg-theme-card p-6'
            : 'w-full max-w-md space-y-4 rounded-lg border border-theme-border bg-theme-card p-6'
        }
      >
        <h1 className="text-2xl font-semibold">Garrisons Super Admin</h1>
        {message && <p role="alert">{message}</p>}
        {cliReference ? (
          cliReference[1] === 'register' ? (
            <SupportRegistrationPanel fromCli />
          ) : cliReference[1] === 'proof' ? (
            <SupportCliProofPanel key={cliReference[2]} reference={cliReference[2]} />
          ) : (
            <SupportCliLoginPanel key={cliReference[2]} reference={cliReference[2]} />
          )
        ) : session ? (
          <SupportShell
            session={session}
            pending={pending}
            onSignOut={() => void signOut()}
            onExpired={handleExpiry}
          />
        ) : otpReference ? (
          <SupportOtpForm
            reference={otpReference}
            onVerified={loadProfile}
            onRestart={() => setOtpReference(null)}
          />
        ) : (
          <>
            <form className="space-y-3" onSubmit={(event) => void signIn(event)}>
              <label className="block">
                Operator reference
                <input
                  autoComplete="off"
                  className="mt-1 w-full rounded-md border border-theme-border bg-theme-card px-3 py-2"
                  maxLength={36}
                  name="operator_id"
                  required
                />
              </label>
              <button
                className="rounded-md bg-brand-600 px-4 py-2 font-medium text-white"
                disabled={pending}
                type="submit"
              >
                {otpOnlyLogin ? 'Send sign-in code' : 'Sign in with a passkey'}
              </button>
            </form>
            {!otpOnlyLogin && <SupportRegistrationPanel />}
          </>
        )}
      </section>
    </main>
  );
}
