import { FormEvent, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { confirmPasswordReset, requestPasswordReset } from '../../api/auth';

function validatePasswordPolicy(password: string): string | null {
  if (password.length < 8) return 'Password must be at least 8 characters.';
  if (!/[A-Z]/.test(password)) return 'Password must include an uppercase letter.';
  if (!/[a-z]/.test(password)) return 'Password must include a lowercase letter.';
  if (!/\d/.test(password)) return 'Password must include a number.';
  if (!/[^A-Za-z0-9]/.test(password)) return 'Password must include a symbol.';
  return null;
}

export function PasswordResetPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [devOtp, setDevOtp] = useState<string | null | undefined>(null);
  const [otp, setOtp] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setIsSubmitting(true);

    try {
      if (!challengeId) {
        const challenge = await requestPasswordReset(email);
        setChallengeId(challenge.challenge_id ?? null);
        setDevOtp(challenge.dev_otp);
        setNotice(challenge.message);
        return;
      }

      const policyError = validatePasswordPolicy(newPassword);
      if (policyError) {
        setError(policyError);
        return;
      }
      if (newPassword !== confirmPassword) {
        setError('New password and confirmation must match.');
        return;
      }

      await confirmPasswordReset(challengeId, otp, newPassword);
      navigate('/login', {
        state: { notice: 'Password reset complete. You can sign in with your new password.' }
      });
    } catch {
      setError('Unable to reset password. Check the code and try again.');
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
        <p className="mt-5 text-sm font-medium text-brand-600">Account Security</p>
        <h1 className="mt-2 text-2xl font-semibold text-theme-text-primary">Reset password</h1>
        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <label className="block">
            <span className="text-sm font-medium text-theme-text-secondary">Email</span>
            <input
              className="mt-1 w-full rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
              disabled={Boolean(challengeId) || isSubmitting}
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>

          {challengeId ? (
            <>
              <label className="block">
                <span className="text-sm font-medium text-theme-text-secondary">
                  Verification code
                </span>
                <input
                  className="mt-1 w-full rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm tracking-widest text-theme-text-primary"
                  disabled={isSubmitting}
                  inputMode="numeric"
                  maxLength={6}
                  onChange={(event) => setOtp(event.target.value)}
                  pattern="[0-9]{6}"
                  required
                  value={otp}
                />
              </label>
              <PasswordField label="New password" onChange={setNewPassword} value={newPassword} />
              <PasswordField
                label="Confirm new password"
                onChange={setConfirmPassword}
                value={confirmPassword}
              />
            </>
          ) : null}

          {devOtp ? (
            <p className="alert-warning rounded-md border border-[var(--status-warning-border)] px-3 py-2 text-sm">
              Development code: <span className="font-semibold tracking-widest">{devOtp}</span>
            </p>
          ) : null}
          {notice ? <p className="alert-success rounded-md px-3 py-2 text-sm">{notice}</p> : null}
          {error ? (
            <p className="text-sm font-medium text-[var(--status-error-text)]">{error}</p>
          ) : null}
          <button
            className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-70"
            disabled={isSubmitting}
            type="submit"
          >
            {challengeId ? 'Reset password' : 'Send reset code'}
          </button>
        </form>
        <Link
          className="mt-4 inline-flex text-sm font-medium text-brand-700 hover:text-brand-800"
          to="/login"
        >
          Back to sign in
        </Link>
      </section>
    </main>
  );
}

function PasswordField({
  label,
  onChange,
  value
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-theme-text-secondary">{label}</span>
      <input
        className="mt-1 w-full rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary"
        minLength={8}
        onChange={(event) => onChange(event.target.value)}
        required
        type="password"
        value={value}
      />
    </label>
  );
}
