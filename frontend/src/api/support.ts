import type { components } from './schema';

export function supportRequest(path: string, options: RequestInit = {}) {
  return fetch('/api/v1/support' + path, {
    ...options,
    credentials: 'same-origin',
    cache: 'no-store',
    redirect: 'error'
  });
}

export function supportCsrf() {
  const prefix = '__Host-garrison-support-csrf=';
  return document.cookie.split('; ').find((entry) => entry.startsWith(prefix))?.slice(prefix.length);
}

export function supportPost(path: string, payload: object, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  headers.set('Content-Type', 'application/json');
  const csrf = supportCsrf();
  if (csrf) headers.set('X-Support-CSRF', csrf);
  return supportRequest(path, { ...options, method: 'POST', headers, body: JSON.stringify(payload) });
}

type SupportLogFrame =
  | { kind: 'evidence'; event: components['schemas']['SupportRequestEvent'] }
  | { kind: 'closed'; reason: string };

export async function* readSupportLogStream(response: Response): AsyncGenerator<SupportLogFrame> {
  if (!response.body || response.headers.get('content-type')?.split(';')[0] !== 'text/event-stream') {
    throw new Error('Invalid evidence stream');
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += value;
      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (frame.length > 16_384) throw new Error('Invalid evidence frame');
        const lines = frame.split('\n');
        const data = lines.find((line) => line.startsWith('data: '));
        if (data) {
          const parsed: unknown = JSON.parse(data.slice(6));
          yield lines.includes('event: closed')
            ? { kind: 'closed', reason: (parsed as { reason: string }).reason }
            : { kind: 'evidence', event: parsed as components['schemas']['SupportRequestEvent'] };
        }
        boundary = buffer.indexOf('\n\n');
      }
      if (buffer.length > 16_384) throw new Error('Invalid evidence frame');
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export async function supportPasskey(options: components['schemas']['SupportLoginOptions']) {
  const credential = await navigator.credentials.get({
    publicKey: PublicKeyCredential.parseRequestOptionsFromJSON({
      challenge: options.public_key.challenge,
      rpId: options.public_key.rpId,
      timeout: options.public_key.timeout,
      userVerification: options.public_key.userVerification
    })
  });
  if (!(credential instanceof PublicKeyCredential)) throw new Error();
  const { id, rawId, type, response } = credential.toJSON() as
    components['schemas']['SupportAssertion'];
  return {
    challenge_id: options.challenge_id,
    credential: {
      id, rawId, type,
      response: {
        authenticatorData: response.authenticatorData,
        clientDataJSON: response.clientDataJSON,
        signature: response.signature,
        userHandle: response.userHandle
      }
    }
  };
}
