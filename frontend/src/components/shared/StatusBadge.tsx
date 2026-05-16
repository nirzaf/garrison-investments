const toneClassNames = {
  neutral: 'bg-theme-card-elevated text-theme-text-secondary',
  success: 'bg-[var(--status-success-bg)] text-[var(--status-success-text)]',
  warning: 'bg-[var(--status-warning-bg)] text-[var(--status-warning-text)]',
  danger: 'bg-[var(--status-error-bg)] text-[var(--status-error-text)]',
  info: 'bg-[var(--status-info-bg)] text-[var(--status-info-text)]'
};

export function StatusBadge({
  children,
  tone = 'neutral'
}: {
  children: string;
  tone?: keyof typeof toneClassNames;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-semibold ${toneClassNames[tone]}`}
    >
      {children}
    </span>
  );
}
