const toneClassNames = {
  neutral: 'bg-theme-card-elevated text-theme-text-secondary',
  success: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400',
  warning: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400',
  danger: 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400',
  info: 'bg-sky-50 text-sky-700 dark:bg-sky-900/20 dark:text-sky-400'
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
