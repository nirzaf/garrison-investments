import { FormEvent, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';

import { useAuth } from '../../context/useAuth';

export function LoginPage() {
  const { isAuthenticated, login, verifyOtp } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('admin@garrisons.qa');
  const [password, setPassword] = useState('');
  const [otp, setOtp] = useState('');
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [devOtp, setDevOtp] = useState<string | null | undefined>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

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
        setChallengeId(challenge.challengeId);
        setDevOtp(challenge.devOtp);
      } else {
        await verifyOtp(challengeId, otp);
        navigate('/dashboard', { replace: true });
      }
    } catch {
      setError('Sign in failed. Check your details and try again.');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-theme-main px-4">
      <section className="w-full max-w-md rounded-lg border border-theme-border bg-theme-card p-6 shadow-sm">
        <p className="text-sm font-medium text-brand-600">Construction Internal Portal</p>
        <h1 className="mt-2 text-2xl font-semibold text-theme-text-primary">Sign in</h1>
        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <label className="block">
            <span className="text-sm font-medium text-theme-text-secondary">Email</span>
            <input
              className="mt-1 w-full rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              disabled={Boolean(challengeId) || isSubmitting}
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
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Password"
                required
                type="password"
                value={password}
              />
            </label>
          ) : (
            <label className="block">
              <span className="text-sm font-medium text-theme-text-secondary">Verification code</span>
              <input
                className="mt-1 w-full rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm tracking-widest text-theme-text-primary"
                disabled={isSubmitting}
                inputMode="numeric"
                maxLength={6}
                onChange={(event) => setOtp(event.target.value)}
                pattern="[0-9]{6}"
                placeholder="000000"
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
          {error ? <p className="text-sm font-medium text-[var(--status-error-text)]">{error}</p> : null}
          <button
            className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-70"
            disabled={isSubmitting}
            type="submit"
          >
            {challengeId ? 'Verify and sign in' : 'Continue'}
          </button>
        </form>
      </section>
    </main>
  );
}
