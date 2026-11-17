import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '../../context/useAuth';

function validatePasswordPolicy(password: string): string | null {
  if (password.length < 8) return 'Password must be at least 8 characters.';
  if (!/[A-Z]/.test(password)) return 'Password must include an uppercase letter.';
  if (!/[a-z]/.test(password)) return 'Password must include a lowercase letter.';
  if (!/\d/.test(password)) return 'Password must include a number.';
  if (!/[^A-Za-z0-9]/.test(password)) return 'Password must include a symbol.';
  return null;
}

function getApiErrorDetail(error: unknown): string | null {
  if (typeof error !== 'object' || error === null) return null;
  const data = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
  if (typeof data === 'string') return data;
  if (Array.isArray(data) && data.length > 0) {
    const first = data[0] as { message?: string; msg?: string };
    return first.message ?? first.msg ?? null;
  }
  return null;
}

export function ChangePasswordPage() {
  const { changePassword } = useAuth();
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const policyError = validatePasswordPolicy(newPassword);
    if (policyError) {
      setError(policyError);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation must match.');
      return;
    }

    setIsSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      navigate('/login', { replace: true });
    } catch (err: unknown) {
      const detail = getApiErrorDetail(err);
      setError(detail ?? 'Unable to update password. Check the current password and try again.');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="mx-auto max-w-xl rounded-lg border border-theme-border bg-theme-card p-6 shadow-xs">
      <p className="text-sm font-medium text-brand-600">Account Security</p>
      <h1 className="mt-2 text-2xl font-semibold text-theme-text-primary">Change password</h1>
      <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
        <PasswordField
          label="Current password"
          onChange={setCurrentPassword}
          value={currentPassword}
        />
        <PasswordField label="New password" onChange={setNewPassword} value={newPassword} />
        <PasswordField
          label="Confirm new password"
          onChange={setConfirmPassword}
          value={confirmPassword}
        />
        {error ? (
          <p className="text-sm font-medium text-[var(--status-error-text)]">{error}</p>
        ) : null}
        <button
          className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-70"
          disabled={isSubmitting}
          type="submit"
        >
          Update password
        </button>
      </form>
    </section>
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
