import { useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPasskey, supportPost } from '../../api/support';

type Proof = components['schemas']['SupportCliProofOptions'];

function fromBase64Url(value: string) {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(base64), (character) => character.charCodeAt(0));
}

async function sealAssertion(reference: string, options: Proof, assertion: object) {
  const encoder = new TextEncoder();
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const rawKey = crypto.getRandomValues(new Uint8Array(32));
  const publicKey = await crypto.subtle.importKey(
    'spki', fromBase64Url(options.encryption_key),
    { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['encrypt']
  );
  const key = await crypto.subtle.importKey('raw', rawKey, 'AES-GCM', false, ['encrypt']);
  const wrapped = new Uint8Array(await crypto.subtle.encrypt('RSA-OAEP', publicKey, rawKey));
  rawKey.fill(0);
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: nonce, additionalData: encoder.encode(reference) },
    key, encoder.encode(JSON.stringify(assertion))
  ));
  const envelope = new Uint8Array(wrapped.length + nonce.length + ciphertext.length);
  envelope.set(wrapped);
  envelope.set(nonce, wrapped.length);
  envelope.set(ciphertext, wrapped.length + nonce.length);
  return btoa(Array.from(envelope, (byte) => String.fromCharCode(byte)).join(''))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function SupportCliProofPanel({ reference }: { reference: string }) {
  const [prepared, setPrepared] = useState<{ options: Proof; code: string }>();
  const [pending, setPending] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState('');

  async function load(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const code = String(new FormData(form).get('pairing_code')).trim().toLowerCase();
    setPending(true);
    setError('');
    try {
      const response = await supportPost('/auth/cli-proof/options', { reference, pairing_code: code });
      if (!response.ok) throw new Error();
      setPrepared({ options: await response.json() as Proof, code });
    } catch {
      setError('This approval is unavailable. Check the pairing code or start again.');
    } finally {
      form.reset();
      setPending(false);
    }
  }

  async function approve() {
    if (!prepared || pending) return;
    const { options, code } = prepared;
    setPending(true);
    setError('');
    try {
      const assertion = await supportPasskey(options);
      const sealed = await sealAssertion(reference, options, assertion);
      const response = await supportPost('/auth/cli-proof/submit', {
        reference, pairing_code: code, sealed
      });
      if (response.status !== 204) throw new Error();
      window.history.replaceState(null, '', window.location.pathname);
      setComplete(true);
      setPrepared(undefined);
    } catch {
      setError('The passkey proof could not be sent. Start a new approval if the request expired.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Approve CLI action" className="space-y-3">
      <h2 className="font-semibold">Approve CLI action</h2>
      {complete ? <p role="status">Passkey proof sent. Return to your terminal.</p> : prepared ? (
        <>
          <p>Compare this action with the one you verified in the terminal.</p>
          <p>{prepared.options.stage} · {prepared.options.operation.replace(/_/g, ' ')}</p>
          <p className="break-all">Action {prepared.options.action_id}</p>
          <button type="button" disabled={pending} onClick={() => void approve()}>
            Approve CLI action with passkey
          </button>
        </>
      ) : (
        <form onSubmit={(event) => void load(event)} className="space-y-3">
          <p>Enter the pairing code from the terminal where you started this action.</p>
          <label className="block">
            Action pairing code
            <input name="pairing_code" autoComplete="off" type="password"
              minLength={12} maxLength={12} pattern="[a-fA-F0-9]{12}" required
              className="block w-full rounded border p-2" />
          </label>
          <button type="submit" disabled={pending}>Load CLI action</button>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
