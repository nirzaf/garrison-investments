import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { FrozenPayrollInputs, PayrollInputResult } from './HRPayrollInputs';

function visibleText(html: string): string {
  return html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, '');
}

describe('HRPayrollInputs result rendering', () => {
  it('hides checksum and download button when source issues are present', () => {
    const html = renderToString(
      <PayrollInputResult
        title="leave"
        disabled={false}
        onDownload={vi.fn()}
        data={{
          payroll_period_id: '11111111-1111-1111-1111-111111111111',
          period_start: '2026-11-01',
          period_end: '2026-11-30',
          employee_count: 1,
          approved_request_count: 0,
          paid_days: '0.00',
          unpaid_days: '0.00',
          csv_sha256: null,
          issues: [
            {
              code: 'pending_leave',
              employee_id: 'emp-1',
              request_id: 'req-1'
            }
          ]
        }}
      />
    );
    const text = visibleText(html);
    expect(text).toContain('1 source issues. Resolve them before exporting leave inputs.');
    expect(text).toContain('pending leave');
    expect(text).not.toContain('Download verified leave CSV');
    expect(html).not.toContain('leave input checksum');
  });

  it('renders checksum and enabled download button when leave preview has zero issues', () => {
    const digest = 'a'.repeat(64);
    const html = renderToString(
      <PayrollInputResult
        title="leave"
        disabled={false}
        onDownload={vi.fn()}
        data={{
          payroll_period_id: '11111111-1111-1111-1111-111111111111',
          period_start: '2026-11-01',
          period_end: '2026-11-30',
          employee_count: 1,
          approved_request_count: 1,
          paid_days: '1.00',
          unpaid_days: '0.00',
          csv_sha256: digest,
          issues: []
        }}
      />
    );
    const text = visibleText(html);
    expect(text).toContain('Paid leave days 1.00');
    expect(text).toContain('Unpaid leave days 0.00');
    expect(text).toContain(digest);
    expect(text).toContain('Download verified leave CSV');
  });

  it('renders frozen time and leave checksums and download controls independently', () => {
    const html = renderToString(
      <FrozenPayrollInputs
        runId="run-1"
        evidence={{
          regular_hours: '40.00',
          overtime_hours: '2.50',
          paid_days: '1.00',
          unpaid_days: '0.00',
          time_sha256: '1'.repeat(64),
          leave_sha256: '2'.repeat(64)
        }}
      />
    );
    const text = visibleText(html);
    expect(text).toContain('Download frozen time CSV');
    expect(text).toContain('Download frozen leave CSV');
    expect(text).toContain('1'.repeat(64));
    expect(text).toContain('2'.repeat(64));
  });
});
