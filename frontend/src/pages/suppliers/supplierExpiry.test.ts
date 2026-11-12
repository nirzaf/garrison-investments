import { expect, it } from 'vitest';

import { supplierExpiry } from './supplierExpiry';

it('distinguishes expired evidence from the due date and warning window', () => {
  expect([-1, 0, 1, 30, 31, null].map(supplierExpiry)).toEqual([
    'Expired',
    'Expires today',
    'Expires in 1 day',
    'Expires in 30 days',
    'Current',
    'No expiry date'
  ]);
});
