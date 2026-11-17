import { useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPasskey, supportPost } from '../../api/support';
import { SupportOtpForm } from './SupportOtpForm';

export function SupportCliLoginPanel({ reference }: { reference: string }) {
  const [pending, setPending] = useState(false);
  const [approved, setApproved] = useState(false);
  const [otp, setOtp] = useState<{ reference: string; pairingCode: string } | null>(null);
  const [abandoned, setAbandoned] = useState(false);
  const [error, setError] = useState('');

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || approved) return;
    const form = event.currentTarget;
    const pairingCode = String(new FormData(form).get('pairing_code')).trim().toLowerCase();
    setPending(true);
    setError('');
    try {
      const options = await supportPost('/auth/cli/options', {
        challenge_id: reference, pairing_code: pairingCode
      });
      if (!options.ok) throw new Error();
      const assertion = await supportPasskey(
        await options.json() as components['schemas']['SupportLoginOptions']
      );
      const response = await supportPost('/auth/cli/verify', {
        ...assertion, pairing_code: pairingCode
      });
      if (response.status === 202) {
        const verification = await response.json() as components['schemas']['SupportOtpRequired'];
        setOtp({ reference: verification.otp_reference, pairingCode });
      } else if (response.status === 204) {
        finish();
      } else {
        throw new Error();
      }
    } catch {
      setError('CLI sign-in could not be approved. Check the code or start a new request.');
    } finally {
      form.reset();
      setPending(false);
    }
  }

  function finish() {
    window.history.replaceState(null, '', window.location.pathname);
    setOtp(null);
    setApproved(true);
  }

  return (
    <section aria-label="Approve CLI sign-in" className="space-y-3">
      <h2 className="font-semibold">Approve CLI sign-in</h2>
      {approved ? <p role="status">CLI sign-in approved. Return to your terminal.</p> : abandoned ? (
        <p role="status">Return to your terminal and start a new CLI sign-in.</p>
      ) : otp ? (
        <SupportOtpForm reference={otp.reference} pairingCode={otp.pairingCode}
          onVerified={finish} onRestart={() => {
            setOtp(null);
            setAbandoned(true);
          }} />
      ) : (
        <form onSubmit={(event) => void confirm(event)} className="space-y-3">
          <p>Enter the pairing code from the terminal where you started this sign-in.</p>
          <label className="block">
            Terminal pairing code
            <input name="pairing_code" autoComplete="off" type="password"
              minLength={12} maxLength={12} pattern="[a-fA-F0-9]{12}" required
              className="block w-full rounded border p-2" />
          </label>
          <button type="submit" disabled={pending}>Approve CLI sign-in with passkey</button>
          {error && <p role="alert">{error}</p>}
        </form>
      )}
    </section>
  );
}
