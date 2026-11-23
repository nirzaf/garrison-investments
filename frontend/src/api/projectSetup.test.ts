import { describe, expect, it } from 'vitest';

import {
  normalizeProjectCreate,
  plannedBoqTotal,
  projectSetupIssues,
  type ProjectSetupDraft
} from './projectSetup';

function draft(): ProjectSetupDraft {
  return {
    name: ' Project ',
    scope_of_work: ' Scope ',
    status: 'planning',
    target_end_date: '2027-01-01',
    start_date: '',
    milestones: [
      {
        rowId: 'first',
        name: ' Renamed milestone ',
        sort_order: 1,
        planned_start_date: '',
        planned_end_date: null
      },
      {
        rowId: 'second',
        name: 'Scheduled',
        sort_order: 2,
        planned_start_date: '2026-12-03',
        planned_end_date: '2026-12-04'
      }
    ],
    boq_items: [
      {
        rowId: 'item-1',
        item_code: ' B-1 ',
        description: ' Slab ',
        unit: ' m2 ',
        milestoneId: 'first',
        planned_quantity: ' 1.105 ',
        unit_rate: '4.60'
      }
    ]
  };
}

describe('project setup payload', () => {
  it('normalizes an empty BOQ and does not mutate the project draft', () => {
    const input = draft();
    input.boq_items = [];
    const original = structuredClone(input);
    const payload = normalizeProjectCreate(input);

    expect(payload.boq_items).toEqual([]);
    expect(plannedBoqTotal([])).toBe('0.00');
    expect(input).toEqual(original);
  });

  it('resolves the current milestone name, normalizes dates and preserves decimals without mutating the draft', () => {
    const input = draft();
    const original = structuredClone(input);
    input.milestones.reverse();
    const payload = normalizeProjectCreate(input);
    expect(payload).toMatchObject({
      name: 'Project',
      start_date: null,
      target_end_date: '2027-01-01',
      milestones: [
        { name: 'Scheduled', planned_start_date: '2026-12-03', planned_end_date: '2026-12-04' },
        { name: 'Renamed milestone', planned_start_date: null, planned_end_date: null }
      ],
      boq_items: [
        {
          item_code: 'B-1',
          description: 'Slab',
          unit: 'm2',
          milestone_name: 'Renamed milestone',
          planned_quantity: '1.105',
          unit_rate: '4.60'
        }
      ]
    });
    expect(payload.milestones?.[0]).not.toHaveProperty('rowId');
    expect(payload.boq_items[0]).not.toHaveProperty('rowId');
    expect(input).toEqual({ ...original, milestones: [...original.milestones].reverse() });
  });

  it('reports row fields for a missing milestone, invalid quantity and reversed dates', () => {
    const input = draft();
    input.milestones[1].planned_start_date = '2026-12-05';
    input.boq_items[0].milestoneId = 'removed';
    input.boq_items[0].planned_quantity = '0';
    expect.assertions(1);
    try {
      normalizeProjectCreate(input);
    } catch (error) {
      expect(projectSetupIssues(error).map((issue) => issue.field)).toEqual([
        'milestones.1.planned_end_date',
        'boq_items.0.planned_quantity',
        'boq_items.0.milestone_name'
      ]);
    }
  });

  it('sums each rounded line total using decimal digits', () => {
    const input = draft();
    input.boq_items[0].planned_quantity = '1.005';
    input.boq_items[0].unit_rate = '1.00';
    const row = input.boq_items[0];
    expect(plannedBoqTotal([row, { ...row, rowId: 'item-2' }])).toBe('2.02');
    expect(plannedBoqTotal([{ ...row, unit_rate: '-1' }])).toBeNull();
  });
});
