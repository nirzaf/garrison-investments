import { describe, expect, it } from 'vitest';

import { formatApiError } from './errors';

describe('formatApiError', () => {
  const fallback = 'Unable to save.';
  const apiError = (detail: unknown) => ({ isAxiosError: true, response: { data: { detail } } });

  it('shows the API message without changing the wording', () => {
    expect(formatApiError(apiError('Payment exceeds the outstanding balance.'), fallback)).toBe(
      'Payment exceeds the outstanding balance.'
    );
  });

  it('shows validation field names and messages without including submitted values', () => {
    const detail = [{ loc: ['body', 'entries', 0, 'count'], msg: 'Must be positive', input: -2 }];
    expect(formatApiError(apiError(detail), fallback)).toBe('entries.0.count: Must be positive');
  });

  it('falls back when the response has no usable validation message', () => {
    expect(formatApiError(apiError([{ ctx: {} }]), fallback)).toBe(fallback);
    expect(formatApiError(new Error('network'), fallback)).toBe(fallback);
  });
});
