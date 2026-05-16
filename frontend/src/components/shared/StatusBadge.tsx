const toneClassNames = {
  neutral: 'bg-slate-100 text-slate-700',
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-800',
  danger: 'bg-red-50 text-red-700',
  info: 'bg-sky-50 text-sky-700'
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
