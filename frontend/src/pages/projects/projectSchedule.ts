import type { ProjectTaskRecord } from '../../api/projects';

const DAY_MS = 86_400_000;

export const scheduleTypes = ['baseline', 'planned', 'actual'] as const;
export type ScheduleType = (typeof scheduleTypes)[number];

function dayIndex(date: string | null): number | null {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const timestamp = Date.parse(`${date}T00:00:00Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === date
    ? timestamp / DAY_MS
    : null;
}

export function dateRange(start: string | null, end: string | null): string {
  if (!start && !end) return 'Unscheduled';
  if (!start) return `Ends ${end}`;
  if (!end) return `Starts ${start}`;
  return `${start} to ${end}`;
}

export function buildSchedule(tasks: ProjectTaskRecord[]) {
  const scheduled = [];
  const incomplete: ProjectTaskRecord[] = [];
  let firstDay = Infinity;
  let lastDay = -Infinity;
  for (const task of tasks) {
    const ranges = scheduleTypes.flatMap((kind) => {
      const startDate = task[`${kind}_start_date`];
      const endDate = task[`${kind}_end_date`];
      const start = dayIndex(startDate);
      const end = dayIndex(endDate);
      if (start === null || end === null || end < start) return [];
      firstDay = Math.min(firstDay, start);
      lastDay = Math.max(lastDay, end);
      return [{ kind, start, end, label: dateRange(startDate, endDate) }];
    });
    if (ranges.length) scheduled.push({ task, ranges });
    else incomplete.push(task);
  }
  const totalDays = scheduled.length ? lastDay - firstDay + 1 : 0;
  const width = Math.min(1400, Math.max(660, totalDays * 14));
  const tickCount = Math.min(totalDays, 8, Math.floor(width / 112));
  const ticks = Array.from({ length: tickCount }, (_, index) => {
    const offset = Math.floor((index * (totalDays - 1)) / Math.max(tickCount - 1, 1));
    return {
      date: new Date((firstDay + offset) * DAY_MS).toISOString().slice(0, 10),
      position: (offset / totalDays) * 100
    };
  });
  return {
    scheduled,
    incomplete,
    ticks,
    width,
    bars: (range: { start: number; end: number }) => ({
      left: `${((range.start - firstDay) / totalDays) * 100}%`,
      width: `${((range.end - range.start + 1) / totalDays) * 100}%`
    })
  };
}
