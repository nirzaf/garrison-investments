import type { components } from '../../api/schema';

export type Metric = components['schemas']['OversightMetric'];

export function formatObserved(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function formatMetricValue(metric: Metric): string {
  if (metric.state === 'suppressed') return 'Suppressed (< 5 threshold)';
  if (metric.state === 'unavailable') return 'Unavailable';
  if (metric.state === 'unknown') return 'Unknown';
  if (metric.state === 'not_configured') return 'Not configured';
  return metric.value === null ? 'Unavailable' : String(metric.value);
}

export function statusLabel(value: string): string {
  return value.replace(/_/g, ' ');
}

export const panelCardClass = 'space-y-3 rounded-lg border border-theme-border p-4';
export const inputClass = 'mt-1 block w-full rounded border border-theme-border bg-theme-card px-2.5 py-1.5 text-sm';
export const buttonClass = 'rounded bg-brand-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50';
export const uuidPattern = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
