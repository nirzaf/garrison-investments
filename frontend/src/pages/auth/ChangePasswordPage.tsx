import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '../../context/useAuth';

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

    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation must match.');
      return;
    }

    setIsSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      navigate('/dashboard', { replace: true });
    } catch {
      setError('Unable to update password. Check the current password and try again.');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="mx-auto max-w-xl rounded-lg border border-theme-border bg-theme-card p-6 shadow-sm">
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
