import { useState, type FormEvent } from 'react';

import { supportPost } from '../../api/support';

interface SupportOtpFormProps {
  reference: string;
  pairingCode?: string;
  onVerified: () => void | Promise<void>;
  onRestart: () => void;
}

export function SupportOtpForm({ reference, pairingCode, onVerified, onRestart }: SupportOtpFormProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const otp = new FormData(form).get('otp');
    setPending(true);
    setError('');
    try {
      const response = await supportPost('/auth/verify-otp', {
        otp_reference: reference, otp, pairing_code: pairingCode
      });
      if (response.status !== (pairingCode ? 204 : 200)) throw new Error();
      await onVerified();
    } catch {
      setError('The code could not be verified. Try again or start a new sign-in.');
    } finally {
      form.reset();
      setPending(false);
    }
  }

  return (
    <form className="space-y-3" onSubmit={(event) => void confirm(event)}>
      <p role="status">Check your registered Super Admin mailbox for a six-digit code.</p>
      <label className="block">
        Email verification code
        <input name="otp" autoComplete="one-time-code" inputMode="numeric"
          pattern="[0-9]{6}" maxLength={6} required disabled={pending}
          className="block w-full rounded border p-2" />
      </label>
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={pending}>Verify email code</button>
      <button type="button" disabled={pending} onClick={onRestart}>Start a new sign-in</button>
    </form>
  );
}
