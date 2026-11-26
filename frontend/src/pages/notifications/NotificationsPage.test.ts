import { describe, expect, it } from 'vitest';

import { workflowLink } from './workflowLinks';

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
});
