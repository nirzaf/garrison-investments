import { isAxiosError } from 'axios';

export function formatApiError(error: unknown, fallback: string): string {
  if (!isAxiosError<{ detail?: unknown; error_code?: string; errors?: unknown }>(error)) return fallback;
  const data = error.response?.data;
  const detail = data?.detail;
  if (
    data?.error_code === 'DAILY_REPORT_MATERIAL_CONSUMPTION_FAILED' &&
    Array.isArray(data.errors)
  ) {
    const consumptionMessages: Record<string, string> = {
      item_not_found: 'inventory item could not be matched.',
      item_ambiguous: 'inventory item name or code matches multiple items.',
      item_not_consumable: 'item is inactive or is not consumable.',
      unit_mismatch: 'unit does not match the inventory item.',
      quantity_invalid: 'quantity must be greater than zero.',
      project_stock_missing: 'no active stock is recorded at this project.',
      insufficient_project_stock: 'available project stock is insufficient.',
    };
    const lineMessages = data.errors.flatMap((entry: unknown) => {
      if (typeof entry !== 'object' || entry === null || !('field' in entry) || !('message' in entry)) {
        return [];
      }
      if (
        typeof entry.field !== 'string' ||
        typeof entry.message !== 'string' ||
        !/^material_consumption\[\d+\]$/.test(entry.field)
      ) {
        return [];
      }
      const reason = consumptionMessages[entry.message];
      const index = Number(entry.field.match(/\d+/)?.[0]);
      return reason && Number.isInteger(index) ? [`Material line ${index + 1}: ${reason}`] : [];
    });
    if (lineMessages.length > 0) return lineMessages.join(' ');
  }
  const validationIssues = data?.error_code === 'VALIDATION_ERROR' ? data.errors : undefined;

  const entries = Array.isArray(validationIssues)
    ? validationIssues
    : Array.isArray(detail) ? detail : [detail];
  const messages = entries.flatMap((entry: unknown) => {
    if (typeof entry !== 'object' || entry === null || !('msg' in entry)) return [];
    if (typeof entry.msg !== 'string' || !entry.msg.trim()) return [];
    const path =
      'loc' in entry && Array.isArray(entry.loc)
        ? entry.loc.filter((part: unknown) => typeof part === 'string' || typeof part === 'number')
        : [];
    const field = path.filter((part) => part !== 'body').join('.');
    return [field ? `${field}: ${entry.msg}` : entry.msg];
  });
  return messages.join(' ') || (typeof detail === 'string' ? detail.trim() : '') || fallback;
}
