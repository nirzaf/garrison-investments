import { FormEvent, useEffect, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';

import { OfflineStorageUpgradeBlockedError } from '../../api/offlineDb';
import { useAuth } from '../../context/useAuth';

export function LoginPage() {
  const { isAuthenticated, login, verifyOtp } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const successNotice = (location.state as { notice?: string } | null)?.notice ?? null;
  const [email, setEmail] = useState('admin@garrisons.qa');
  const [password, setPassword] = useState('');
  const [otp, setOtp] = useState('');
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [devOtp, setDevOtp] = useState<string | null | undefined>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const passwordInput = useRef<HTMLInputElement>(null);
  const codeInput = useRef<HTMLInputElement>(null);
  const restarting = useRef(false);

  useEffect(() => {
    if (challengeId) codeInput.current?.focus();
    if (!challengeId && restarting.current) {
      restarting.current = false;
      passwordInput.current?.focus();
    }
  }, [challengeId]);

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      if (!challengeId) {
        const challenge = await login(email, password);
        setPassword('');
        setChallengeId(challenge.challengeId);
        setDevOtp(challenge.devOtp);
      } else {
        await verifyOtp(challengeId, otp);
        navigate('/dashboard', { replace: true });
      }
    } catch (failure) {
      if (failure instanceof OfflineStorageUpgradeBlockedError) {
        setError(failure.message);
      } else {
        setError(challengeId
          ? 'Sign in failed. Check the code or request a new one.'
          : 'Sign in failed. Check your details and try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-theme-main px-4">
      <section className="w-full max-w-md rounded-lg border border-theme-border bg-theme-card p-6 shadow-xs">
        <img
          alt="Garrisons Investments Pvt Ltd"
          className="h-auto w-full rounded-md border border-theme-border object-cover"
          src="/brand/logo-full.jpg"
        />
        <p className="mt-5 text-sm font-medium text-brand-600">Construction Internal Portal</p>
        <h1 className="mt-2 text-2xl font-semibold text-theme-text-primary">Sign in</h1>
        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <label className="block">
            <span className="text-sm font-medium text-theme-text-secondary">Email</span>
            <input
              className="mt-1 w-full rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              disabled={Boolean(challengeId) || isSubmitting}
              autoComplete="username"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@company.com"
              required
              type="email"
              value={email}
            />
          </label>
          {!challengeId ? (
            <label className="block">
              <span className="text-sm font-medium text-theme-text-secondary">Password</span>
              <input
                className="mt-1 w-full rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
                disabled={isSubmitting}
                autoComplete="current-password"
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Password"
                ref={passwordInput}
                required
                type="password"
                value={password}
              />
            </label>
          ) : (
            <label className="block">
              <span className="text-sm font-medium text-theme-text-secondary">
                Verification code
              </span>
              <input
                className="mt-1 w-full rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm tracking-widest text-theme-text-primary"
                disabled={isSubmitting}
                autoComplete="one-time-code"
                inputMode="numeric"
                maxLength={6}
                onChange={(event) => setOtp(event.target.value)}
                pattern="[0-9]{6}"
                placeholder="000000"
                ref={codeInput}
                required
                value={otp}
              />
            </label>
          )}
          {devOtp ? (
            <p className="alert-warning rounded-md border border-[var(--status-warning-border)] px-3 py-2 text-sm">
              Development code: <span className="font-semibold tracking-widest">{devOtp}</span>
            </p>
          ) : null}
          {successNotice ? (
            <p className="rounded-md border border-[var(--status-success-border)] bg-[var(--status-success-bg)] px-3 py-2 text-sm text-[var(--status-success-text)]">
              {successNotice}
            </p>
          ) : null}
          {error ? (
            <p className="text-sm font-medium text-[var(--status-error-text)]" role="alert">
              {error}
            </p>
          ) : null}
          <button
            className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-70"
            disabled={isSubmitting}
            type="submit"
          >
            {challengeId ? 'Verify and sign in' : 'Continue'}
          </button>
        </form>
        {challengeId ? (
          <button
            className="mt-4 inline-flex text-sm font-medium text-brand-700 hover:text-brand-800 disabled:opacity-70"
            disabled={isSubmitting}
            onClick={() => {
              restarting.current = true;
              setChallengeId(null);
              setOtp('');
              setDevOtp(null);
              setError(null);
            }}
            type="button"
          >
            Request a new code
          </button>
        ) : (
          <Link
            className="mt-4 inline-flex text-sm font-medium text-brand-700 hover:text-brand-800"
            to="/password-reset"
          >
            Forgot password?
          </Link>
        )}
      </section>
    </main>
  );
}
