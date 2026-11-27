import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import type { HrSchemas } from '../../api/hr';
import { LeaveAccrualPlan } from './HRLeaveAccrual';

type Period = HrSchemas['LeaveAccrualResponse'];
type Plan = HrSchemas['LeaveAccrualCatchUpResponse'];

function period(values: Partial<Period> = {}): Period {
  return {
    employee_id: '11111111-1111-1111-1111-111111111111',
    leave_type_id: '22222222-2222-2222-2222-222222222222',
    policy_id: '33333333-3333-3333-3333-333333333333',
    period_start: '2026-01-01',
    period_end: '2026-12-31',
    days: '1.00',
    digest: null,
    ledger_entry_id: null,
    due_date: null,
    service_year_band: null,
    outcome: null,
    ...values
  };
}

function plan(
  periods: Period[],
  pending_days = '0.00',
  digest: string | null = 'a'.repeat(64)
): Plan {
  return { periods, pending_days, digest };
}

function renderPlan(value: Plan): string {
  return renderToStaticMarkup(
    <LeaveAccrualPlan plan={value} pending={false} onConfirm={vi.fn()} />
  );
}

function visibleText(html: string): string {
  return html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, '');
}

describe('leave accrual outcome projection', () => {
  it.each([
    [period({ outcome: 'not_due', days: '0.00' }), 'Not due'],
    [period({ outcome: 'baseline_recognized', days: '0.00' }), 'Recognized in reviewed baseline'],
    [
      period({ outcome: 'posted', ledger_entry_id: 'receipt-posted' }),
      'Posted. Ledger reference receipt-posted'
    ],
    [
      period({ outcome: 'already_posted', ledger_entry_id: 'receipt-existing' }),
      'Posted. Ledger reference receipt-existing'
    ],
    [period({ outcome: 'reconciliation_required' }), 'Reconciliation required'],
    [period({ outcome: 'preview', digest: 'b'.repeat(64) }), 'Ready for confirmation'],
    [period({ outcome: null }), 'Legacy preview']
  ])('labels %s accurately', (accrual, label) => {
    const text = visibleText(renderPlan(plan([accrual])));
    expect(text).toContain(label);
  });

  it('shows due date and service-year band returned by the server', () => {
    const accrual = period({
      outcome: 'preview',
      digest: 'b'.repeat(64),
      due_date: '2026-01-01',
      service_year_band: 3
    });
    const text = visibleText(renderPlan(plan([accrual], '1.00')));
    expect(text).toContain('Due 2026-01-01');
    expect(text).toContain('Service year 3');
  });

  it('counts only actionable catch-up days when outcomes are mixed', () => {
    const mixed = plan(
      [
        period({ outcome: 'already_posted', days: '5.00', ledger_entry_id: 'receipt-existing' }),
        period({ period_start: '2026-02-01', outcome: 'baseline_recognized', days: '0.00' }),
        period({ period_start: '2026-03-01', outcome: 'reconciliation_required', days: '4.00' }),
        period({ period_start: '2026-04-01', outcome: 'not_due', days: '0.00' }),
        period({
          period_start: '2026-05-01',
          outcome: 'preview',
          days: '0.50',
          digest: 'c'.repeat(64)
        })
      ],
      '0.50'
    );
    const text = visibleText(renderPlan(mixed));
    expect(text).toContain('Posted. Ledger reference receipt-existing');
    expect(text).toContain('Reconciliation required');
    expect(text).toContain('Days to credit: 0.50');
    expect(text).toContain('Confirm and post accrual');
    expect(text).not.toContain('Pending');
  });

  it('never offers confirmation without a digest or actionable positive days', () => {
    const noDigest = renderPlan(plan([period({ outcome: 'preview', days: '0.50' })], '0.50', null));
    expect(visibleText(noDigest)).toContain('Days to credit: 0.50');
    expect(noDigest).not.toContain('Confirm and post accrual');

    const zero = renderPlan(
      plan([period({ outcome: 'preview', days: '0.00', digest: 'b'.repeat(64) })], '0.00')
    );
    expect(visibleText(zero)).not.toContain('Days to credit');
    expect(zero).not.toContain('Confirm and post accrual');

    const reconciled = renderPlan(
      plan([period({ outcome: 'reconciliation_required', days: '4.00' })], '4.00')
    );
    expect(visibleText(reconciled)).not.toContain('Days to credit');
    expect(reconciled).not.toContain('Confirm and post accrual');
  });

  it('does not show an already posted credit as pending', () => {
    const html = renderPlan(
      plan(
        [period({ outcome: 'already_posted', days: '5.00', ledger_entry_id: 'receipt-existing' })],
        '0.00',
        null
      )
    );
    const text = visibleText(html);
    expect(text).toContain('Posted. Ledger reference receipt-existing');
    expect(text).not.toContain('Days to credit');
    expect(text).not.toContain('Pending');
    expect(html).not.toContain('Confirm and post accrual');
  });
});
