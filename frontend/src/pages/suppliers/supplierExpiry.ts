export function supplierExpiry(days: number | null): string {
  if (days === null) return 'No expiry date';
  if (days < 0) return 'Expired';
  if (days === 0) return 'Expires today';
  if (days <= 30) return `Expires in ${days} ${days === 1 ? 'day' : 'days'}`;
  return 'Current';
}
