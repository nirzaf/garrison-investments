import { describe, expect, it } from 'vitest';

import {
  isNotificationActionable,
  notificationWorkflowLink,
  workflowLink
} from './workflowLinks';

const origin = 'https://garrison.example';

function notificationBody(url: string) {
  return `A workflow update.\n\nOpen request: ${url}`;
}

describe('workflow notification links', () => {
  it.each(['/reports/supervisor-update?updateId=123', '/hr/site-attendance?attendanceId=456'])(
    'allows the exact in-app route %s',
    (path) => {
      expect(workflowLink(notificationBody(`${origin}${path}`), origin)?.to).toBe(path);
    }
  );

  it.each([
    'https://outside.example/hr/site-attendance',
    '//garrison.example/hr/site-attendance',
    `${origin}/hr/site-attendance-evil`,
    `${origin}/reports/supervisor-update/archive`
  ])('rejects non-allowlisted link %s', (url) => {
    expect(workflowLink(notificationBody(url), origin)).toBeNull();
  });

  it('hides a pending leave link when the live route is no longer actionable', () => {
    const notification = {
      body: notificationBody(`${origin}/hr`),
      is_actionable: false,
      superseded_at: null
    };

    expect(isNotificationActionable(notification)).toBe(false);
    expect(notificationWorkflowLink(notification, origin)).toBeNull();
  });

  it('keeps legacy and current notifications actionable until superseded', () => {
    expect(isNotificationActionable({})).toBe(true);
    expect(isNotificationActionable({ is_actionable: true, superseded_at: null })).toBe(true);
    expect(isNotificationActionable({ superseded_at: '2026-11-27T00:00:00Z' })).toBe(false);
  });
});
