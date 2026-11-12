import { expect, it } from 'vitest';

import type { ProjectTaskRecord } from '../../api/projects';
import { buildSchedule, dateRange } from './projectSchedule';

function task(overrides: Partial<ProjectTaskRecord> = {}): ProjectTaskRecord {
  return {
    id: 'task-id',
    project_id: 'project-id',
    milestone_id: null,
    dependency_task_id: null,
    owner_id: null,
    name: 'Test task',
    baseline_start_date: null,
    baseline_end_date: null,
    planned_start_date: null,
    planned_end_date: null,
    actual_start_date: null,
    actual_end_date: null,
    status: 'not_started',
    progress_percentage: '0',
    delay_reason: null,
    sort_order: 0,
    revision: 1,
    created_at: '2026-11-12T00:00:00Z',
    ...overrides
  };
}

it('allocates one full day for an actual same-day task and excludes incomplete ranges', () => {
  const chart = buildSchedule([
    task({ actual_start_date: '2026-11-01', actual_end_date: '2026-11-01' }),
    task({ id: 'incomplete', planned_start_date: '2026-11-01' }),
    task({ id: 'invalid', actual_start_date: '2026-11-31', actual_end_date: '2026-12-01' })
  ]);
  expect(chart.scheduled).toHaveLength(1);
  const [range] = chart.scheduled[0].ranges;
  expect(range.kind).toBe('actual');
  expect(chart.bars(range)).toEqual({ left: '0%', width: '100%' });
  expect(chart.ticks[0].date).toBe('2026-11-01');
  expect(chart.incomplete.map((item) => item.id)).toEqual(['incomplete', 'invalid']);
  expect(dateRange('2026-11-01', null)).toBe('Starts 2026-11-01');
});

it('keeps date-only ranges distinct and bounds the axis for a long span', () => {
  const chart = buildSchedule([
    task({
      baseline_start_date: '2025-03-08',
      baseline_end_date: '2025-03-09',
      planned_start_date: '2025-03-10',
      planned_end_date: '2025-03-11',
      actual_start_date: '2027-03-10',
      actual_end_date: '2027-03-11'
    })
  ]);
  expect(chart.width).toBe(1400);
  expect(chart.ticks).toHaveLength(8);
  expect(chart.ticks[0].date).toBe('2025-03-08');
  expect(chart.ticks[chart.ticks.length - 1].date).toBe('2027-03-11');
  expect(chart.scheduled[0].ranges.map((range) => range.kind)).toEqual([
    'baseline',
    'planned',
    'actual'
  ]);
});
