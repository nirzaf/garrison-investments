import { afterEach, describe, expect, it, vi } from 'vitest';

import { clearBrowserSession, getBrowserSession, startBrowserSession } from './browserSession';
import { recentFeedbackRequests, rememberFeedbackRequest } from './feedbackDiagnostics';

const scope = { namespace: 'feedback-test', ownerUserId: 'reporter', generation: 'initial' };

afterEach(() => {
  vi.useRealTimers();
  clearBrowserSession();
});

describe('feedback diagnostics', () => {
  it('remembers only the latest eight valid distinct references and expires them', () => {
    vi.useFakeTimers();
    startBrowserSession(scope, 'synthetic');
    const active = getBrowserSession()!;
    const ids = Array.from({ length: 10 }, (_, index) => index.toString(16).padStart(32, '0'));
    for (const id of ids) rememberFeedbackRequest(active, id);
    rememberFeedbackRequest(active, ids[8]);
    rememberFeedbackRequest(active, 'bearer-secret');
    expect(recentFeedbackRequests()).toEqual([ids[8], ids[9], ...ids.slice(2, 8).reverse()]);
    vi.advanceTimersByTime(30 * 60_000);
    expect(recentFeedbackRequests()).toEqual([]);
  });

  it('isolates references across account changes and new sign-ins by the same user', () => {
    startBrowserSession(scope, 'synthetic');
    rememberFeedbackRequest(getBrowserSession()!, 'a'.repeat(32));
    startBrowserSession(scope, 'refreshed-synthetic');
    expect(recentFeedbackRequests()).toEqual(['a'.repeat(32)]);
    startBrowserSession({ ...scope, ownerUserId: 'second-user' }, 'second-synthetic');
    expect(recentFeedbackRequests()).toEqual([]);
    startBrowserSession({ ...scope, generation: 'next' }, 'new-synthetic');
    expect(recentFeedbackRequests()).toEqual([]);
  });
});
