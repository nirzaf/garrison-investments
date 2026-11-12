import { isAxiosError } from 'axios';

import type { components } from './schema';

type CreateRequest = components['schemas']['ProjectCreateRequest'];
export type MilestoneDraft = components['schemas']['MilestoneCreateRequest'] & { rowId: string };
export type BoqDraft = Omit<
  components['schemas']['BoqItemCreateRequest'],
  'milestone_name' | 'planned_quantity' | 'unit_rate'
> & { rowId: string; milestoneId: string; planned_quantity: string; unit_rate: string };
export type ProjectSetupDraft = Omit<CreateRequest, 'milestones' | 'boq_items'> & {
  milestones: MilestoneDraft[];
  boq_items: BoqDraft[];
};

type FieldIssue = { field: string; message: string };

class ProjectSetupError extends Error {
  constructor(readonly issues: FieldIssue[]) {
    super('Check the highlighted project fields.');
  }
}

export function projectSetupIssues(error: unknown): FieldIssue[] {
  if (error instanceof ProjectSetupError) return error.issues;
  if (!isAxiosError<{ errors?: unknown }>(error)) return [];
  const errors = error.response?.data?.errors;
  if (!Array.isArray(errors)) return [];
  return errors.flatMap((issue: unknown) => {
    if (typeof issue !== 'object' || issue === null) return [];
    if (
      'field' in issue &&
      typeof issue.field === 'string' &&
      'message' in issue &&
      typeof issue.message === 'string'
    ) {
      return [{ field: issue.field, message: issue.message }];
    }
    if (
      'loc' in issue &&
      Array.isArray(issue.loc) &&
      'msg' in issue &&
      typeof issue.msg === 'string'
    ) {
      return [
        {
          field: issue.loc.filter((part: unknown) => part !== 'body').join('.'),
          message: issue.msg
        }
      ];
    }
    return [];
  });
}

const optionalText = (value?: string | null) => value?.trim() || null;

function scaledDecimal(value: string, wholeDigits: number, scale: number): bigint | undefined {
  const match = /^(\d*)(?:\.(\d*))?$/.exec(value.trim());
  if (!match || (!match[1] && !match[2])) return undefined;
  const whole = match[1].replace(/^0+(?=\d)/, '');
  const fraction = match[2] ?? '';
  if (whole.length > wholeDigits || fraction.length > scale) return undefined;
  return BigInt(`${whole || '0'}${fraction.padEnd(scale, '0')}`);
}

export function plannedBoqTotal(rows: BoqDraft[]): string | null {
  let totalCents = 0n;
  for (const row of rows) {
    const quantity = scaledDecimal(row.planned_quantity, 11, 3);
    const rate = scaledDecimal(row.unit_rate, 12, 2);
    if (quantity === undefined || quantity === 0n || rate === undefined) return null;
    totalCents += (quantity * rate + 500n) / 1000n;
  }
  return `${totalCents / 100n}.${String(totalCents % 100n).padStart(2, '0')}`;
}

export function normalizeProjectCreate(input: ProjectSetupDraft): CreateRequest {
  const issues: FieldIssue[] = [];
  const projectName = input.name.trim();
  const scope = input.scope_of_work.trim();
  const targetDate = input.target_end_date.trim();
  const startDate = optionalText(input.start_date);
  if (projectName.length < 2) issues.push({ field: 'name', message: 'Enter a project name.' });
  if (!scope) issues.push({ field: 'scope_of_work', message: 'Enter the scope of work.' });
  if (!targetDate) issues.push({ field: 'target_end_date', message: 'Enter a target end date.' });
  if (startDate && targetDate && targetDate < startDate) {
    issues.push({ field: 'target_end_date', message: 'Target end date precedes the start date.' });
  }
  const names = new Map<string, string>();
  const normalizedNames = new Set<string>();
  const milestones = input.milestones.map(({ rowId, ...row }, index) => {
    const name = row.name.trim();
    const start = optionalText(row.planned_start_date);
    const end = optionalText(row.planned_end_date);
    if (!name || normalizedNames.has(name.toLowerCase())) {
      issues.push({ field: `milestones.${index}.name`, message: 'Enter a unique milestone name.' });
    }
    names.set(rowId, name);
    normalizedNames.add(name.toLowerCase());
    if (start && end && end < start) {
      issues.push({
        field: `milestones.${index}.planned_end_date`,
        message: 'End date precedes the start date.'
      });
    }
    return {
      ...row,
      name,
      discipline: optionalText(row.discipline),
      planned_start_date: start,
      planned_end_date: end
    };
  });
  const codes = new Set<string>();
  const boqItems = input.boq_items.map((row, index) => {
    const { milestoneId } = row;
    const field = (name: string) => `boq_items.${index}.${name}`;
    const itemCode = row.item_code.trim();
    const description = row.description.trim();
    const unit = row.unit.trim();
    const milestoneName = milestoneId ? names.get(milestoneId) : null;
    const quantity = scaledDecimal(row.planned_quantity, 11, 3);
    const rate = scaledDecimal(row.unit_rate, 12, 2);
    if (!itemCode || codes.has(itemCode.toLowerCase())) {
      issues.push({ field: field('item_code'), message: 'Enter a unique item code.' });
    }
    codes.add(itemCode.toLowerCase());
    if (!description)
      issues.push({ field: field('description'), message: 'Enter a BOQ description.' });
    if (!unit) issues.push({ field: field('unit'), message: 'Enter a unit.' });
    if (quantity === undefined || quantity === 0n) {
      issues.push({
        field: field('planned_quantity'),
        message: 'Enter a positive quantity with up to three decimal places.'
      });
    }
    if (rate === undefined) {
      issues.push({
        field: field('unit_rate'),
        message: 'Enter a nonnegative rate with up to two decimal places.'
      });
    }
    if (milestoneId && !milestoneName) {
      issues.push({
        field: field('milestone_name'),
        message: 'Select a milestone included in this project.'
      });
    }
    return {
      item_code: itemCode,
      description,
      unit,
      discipline: optionalText(row.discipline),
      phase: optionalText(row.phase),
      milestone_name: milestoneName,
      planned_quantity: row.planned_quantity.trim(),
      unit_rate: row.unit_rate.trim()
    };
  });
  if (!boqItems.length) issues.push({ field: 'boq_items', message: 'Add at least one BOQ item.' });
  if (issues.length) throw new ProjectSetupError(issues);
  return {
    ...input,
    name: projectName,
    scope_of_work: scope,
    start_date: startDate,
    target_end_date: targetDate,
    location: optionalText(input.location),
    description: optionalText(input.description),
    client_name: optionalText(input.client_name),
    contract_number: optionalText(input.contract_number),
    budget_amount:
      typeof input.budget_amount === 'string'
        ? optionalText(input.budget_amount)
        : input.budget_amount,
    milestones,
    boq_items: boqItems
  };
}
