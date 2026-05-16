import type { ReactNode } from 'react';

export function EmptyState({
  title,
  description,
  action
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-theme-border bg-theme-card px-4 py-10 text-center">
      <h3 className="text-base font-semibold text-theme-text-primary">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-sm text-theme-text-secondary">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
