export function businessDate() {
  const now = new Date();
  const timeZone = import.meta.env.VITE_BUSINESS_TIMEZONE || 'Asia/Qatar';
  try {
    return now.toLocaleDateString('en-CA', { timeZone });
  } catch (error) {
    if (!(error instanceof RangeError)) throw error;
    return now.toISOString().slice(0, 10);
  }
}
