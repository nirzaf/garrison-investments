import { describe, expect, it } from 'vitest';

import { businessDate } from './businessDate';

describe('businessDate', () => {
  it('uses the requested business day without modifying the source instant', () => {
    const instant = new Date('2026-05-30T22:15:00Z');
    expect(businessDate(instant, 'Asia/Qatar')).toBe('2026-05-31');
    expect(businessDate(instant, 'Etc/UTC')).toBe('2026-05-30');
    expect(instant.toISOString()).toBe('2026-05-30T22:15:00.000Z');
  });
});
