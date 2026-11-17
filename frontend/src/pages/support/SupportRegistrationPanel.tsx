import { useState, type ChangeEvent, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPost } from '../../api/support';

const operatorReference = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const invitationValue = /^[A-Za-z0-9_-]{43}$/;

export function SupportRegistrationPanel({ fromCli = false }: { fromCli?: boolean }) {
  const [invitation, setInvitation] = useState('');
  const [operator, setOperator] = useState('');
  const [readingFile, setReadingFile] = useState(false);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  async function loadInvitation(event: ChangeEvent<HTMLInputElement>) {
    const field = event.currentTarget;
    const file = field.files?.[0];
    setInvitation('');
    setOperator('');
    setError('');
    setMessage('');
    if (!file) return;
    setReadingFile(true);
    try {
      if (file.size > 1024) throw new Error();
      const value = JSON.parse(await file.text());
      if (!value || value.version !== 1 || Object.keys(value).length !== 3
        || typeof value.invitation !== 'string' || !invitationValue.test(value.invitation)
        || typeof value.operator_reference !== 'string' || !operatorReference.test(value.operator_reference)) {
        throw new Error();
      }
      setInvitation(value.invitation);
      setOperator(value.operator_reference);
    } catch {
      setError('Select the private single-device invitation file.');
    } finally {
      field.value = '';
      setReadingFile(false);
    }
  }

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || readingFile || !invitation) return;
    setPending(true);
    setMessage('');
    setError('');
    try {
      const options = await supportPost('/registration/options', { invitation });
      if (!options.ok) throw new Error();
      const { public_key } = await options.json() as components['schemas']['RegistrationCreationOptions'];
      if (fromCli && public_key.user.name !== operator) throw new Error();
      const result = await navigator.credentials.create({
        publicKey: PublicKeyCredential.parseCreationOptionsFromJSON(public_key)
      });
      if (!(result instanceof PublicKeyCredential)) throw new Error();
      const { id, rawId, type, response } = result.toJSON() as
        components['schemas']['RegistrationAttestation'];
      const verified = await supportPost('/registration/verify', {
        invitation,
        credential: {
          id, rawId, type,
          response: {
            attestationObject: response.attestationObject,
            clientDataJSON: response.clientDataJSON
          }
        }
      });
      if (!verified.ok) throw new Error();
      const state = await verified.json() as components['schemas']['RegistrationResult'];
      setInvitation('');
      setOperator('');
      setMessage(state.activated
        ? 'Both passkeys are registered. You can now sign in.'
        : state.awaiting_other_custodian
          ? 'Both passkeys are registered. Sign-in opens after the other custodian finishes.'
          : 'Passkey registered. Use the second invitation on the other device.');
    } catch {
      setError('The passkey could not be registered. Check the invitation and use a device-bound passkey.');
    } finally {
      setPending(false);
    }
  }

  return (
    <details className="space-y-3" open={fromCli || undefined}>
      <summary className="cursor-pointer font-medium">Register a passkey</summary>
      <form className="space-y-2" onSubmit={(event) => void register(event)}>
        {fromCli ? <label className="block">
          Single-device invitation file
          <input className="mt-1 block w-full rounded border p-2" type="file"
            accept=".json,application/json" disabled={pending || readingFile}
            onChange={(event) => void loadInvitation(event)} />
          {invitation && <span className="block text-sm">Invitation loaded.</span>}
        </label> : <label className="block">
          Registration invitation
          <input
            className="mt-1 block w-full rounded border p-2" type="password"
            value={invitation} onChange={(event) => setInvitation(event.target.value)}
            autoComplete="off" pattern="[A-Za-z0-9_\-]{43}" maxLength={43} required
          />
        </label>}
        <button type="submit" disabled={pending || readingFile || (fromCli && !invitation)}>
          Register this device
        </button>
      </form>
      {pending && <p role="status">Registering passkey…</p>}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
    </details>
  );
}
