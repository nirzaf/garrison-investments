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
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <section className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-sm font-medium text-brand-700">Construction Internal Portal</p>
        <h1 className="mt-2 text-2xl font-semibold text-slate-950">Sign in</h1>
        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Email</span>
            <input
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
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
              <span className="text-sm font-medium text-slate-700">Password</span>
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
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
              <span className="text-sm font-medium text-slate-700">Verification code</span>
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm tracking-widest"
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
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              Development code: <span className="font-semibold tracking-widest">{devOtp}</span>
            </p>
          ) : null}
          {error ? <p className="text-sm font-medium text-red-700">{error}</p> : null}
          <button
            className="w-full rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-70"
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
