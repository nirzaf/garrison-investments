import { useCallback, useEffect, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportCsrf, supportPasskey, supportPost, supportRequest } from '../../api/support';
import { SupportAccountPanel } from '../support/SupportAccountPanel';
import { SupportBackupsPanel } from '../support/SupportBackupsPanel';
import { SupportBusinessActionReview } from '../support/SupportBusinessActionsPanel';
import { SupportConfigPanel } from '../support/SupportConfigPanel';
import { SupportIncidentsPanel } from '../support/SupportIncidentsPanel';
import { SupportJobsPanel } from '../support/SupportJobsPanel';
import { SupportOverviewPanel } from '../support/SupportOverviewPanel';
import { SupportPolicyExplainPanel } from '../support/SupportPolicyExplainPanel';
import { SupportRecoveryStatusPanel } from '../support/SupportRecoveryStatusPanel';
import { SupportPermissionViewPanel } from '../support/SupportPermissionViewPanel';
import { SupportCliProofPanel } from '../support/SupportCliProofPanel';
import { SupportCliLoginPanel } from '../support/SupportCliLoginPanel';
import { SupportCaseAuditPanel } from '../support/SupportCaseAuditPanel';
import { SupportCaseReview } from '../support/SupportCaseActionsPanel';
import { SupportCasesPanel } from '../support/SupportCasesPanel';
import { SupportEvidenceExportPanel } from '../support/SupportEvidenceExportPanel';
import { SupportCustodyPanel } from '../support/SupportCustodyPanel';
import { SupportLogs } from '../support/SupportLogs';
import { SupportHealthPanel } from '../support/SupportHealthPanel';
import { SupportOtpForm } from '../support/SupportOtpForm';
import { SupportRegistrationPanel } from '../support/SupportRegistrationPanel';

type LoginOptions = components['schemas']['SupportLoginOptions'];
type Session = components['schemas']['SupportProfile'];

function readCliReference() {
  if (typeof window === 'undefined') return null;
  if (window.location.hash === '#register') return ['', 'register', ''];
  return /^#(cli|proof)=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/
    .exec(window.location.hash);
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
          const mode = await modeResponse.json() as { otp_only_login?: boolean };
          if (!controller.signal.aborted) setOtpOnlyLogin(Boolean(mode.otp_only_login));
        }
        if (meResponse.ok) {
          const identity = await meResponse.json() as Session;
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
        const signInResult = await result.json() as components['schemas']['SupportOtpRequired'];
        setOtpReference(signInResult.otp_reference);
        return;
      }
      const optionsResponse = await supportPost('/auth/options', { operator_id: operatorId });
      if (!optionsResponse.ok) throw new Error();
      const options = await optionsResponse.json() as LoginOptions;
      const result = await supportPost('/auth/verify', await supportPasskey(options));
      if (result.status === 503) {
        setMessage('Verification email is unavailable. Start a new sign-in and try again.');
        return;
      }
      if (!result.ok) throw new Error();
      const signInResult = await result.json() as
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
    setSession(await profile.json() as Session);
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
          cliReference[1] === 'register'
            ? <SupportRegistrationPanel fromCli />
            : cliReference[1] === 'proof'
            ? <SupportCliProofPanel key={cliReference[2]} reference={cliReference[2]} />
            : <SupportCliLoginPanel key={cliReference[2]} reference={cliReference[2]} />
        ) : session ? (
          <div key={session.operator_id} className="space-y-4">
            <p>Technical session active</p>
            <SupportOverviewPanel capabilities={session.capabilities} onExpired={handleExpiry} />
            {session.capabilities.includes('jobs.read') && (
              <SupportJobsPanel onExpired={handleExpiry} />
            )}
            {session.capabilities.includes('backups.read') && (
              <SupportBackupsPanel onExpired={handleExpiry} />
            )}
            {session.capabilities.includes('config.read') && (
              <SupportConfigPanel onExpired={handleExpiry} />
            )}
            {session.capabilities.includes('incidents.read') && (
              <SupportIncidentsPanel onExpired={handleExpiry} />
            )}
            {session.capabilities.includes('cases.manage') && (
              <SupportCasesPanel onExpired={handleExpiry} operatorId={session.operator_id}
                canReadDirectory={session.capabilities.includes('directory.read')}
                canReviewProjectScope={session.capabilities.includes('simulation.start')}
                canReadTimeline={session.capabilities.includes('logs.runtime')} />
            )}
            {session.capabilities.includes('operator.manage') && (
              <SupportCustodyPanel onExpired={handleExpiry} />
            )}
            {(session.capabilities.includes('operator.manage') || (
              session.capabilities.includes('cases.manage') && (
                session.capabilities.includes('logs.runtime') || session.capabilities.includes('directory.read')
              )
            )) && <SupportCaseReview onExpired={handleExpiry} />}
            {session.capabilities.includes('directory.read') && (
              <SupportAccountPanel onExpired={handleExpiry}
                canRequest={session.capabilities.includes('account.request')}
                canExplain={session.capabilities.includes('simulation.start')} />
            )}
            {(session.capabilities.includes('account.request') || session.capabilities.includes('simulation.start')) && (
              <SupportBusinessActionReview onExpired={handleExpiry} canRecordContact={
                session.capabilities.includes('operator.manage') && session.capabilities.includes('account.request')
              } />
            )}
            {session.capabilities.includes('simulation.start') && (
              <>
                <SupportPermissionViewPanel key={session.operator_id} onExpired={handleExpiry} />
                <SupportPolicyExplainPanel onExpired={handleExpiry} />
              </>
            )}
            {session.capabilities.includes('account.request') && (
              <SupportRecoveryStatusPanel key={'recovery-status:' + session.operator_id} onExpired={handleExpiry} />
            )}
            {session.capabilities.includes('logs.audit') && (
              <SupportCaseAuditPanel onExpired={handleExpiry} />
            )}
            {session.capabilities.includes('health.read') && (
              <SupportHealthPanel onExpired={handleExpiry} />
            )}
            {session.capabilities.includes('logs.runtime') && (
              <SupportLogs onExpired={handleExpiry}
                canFollow={session.capabilities.includes('logs.stream')} />
            )}
            {session.capabilities.includes('logs.runtime') && session.capabilities.includes('logs.export') && (
              <SupportEvidenceExportPanel onExpired={handleExpiry} />
            )}
            <button disabled={pending} onClick={() => void signOut()} type="button">Sign out</button>
          </div>
        ) : otpReference ? (
          <SupportOtpForm reference={otpReference} onVerified={loadProfile}
            onRestart={() => setOtpReference(null)} />
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
