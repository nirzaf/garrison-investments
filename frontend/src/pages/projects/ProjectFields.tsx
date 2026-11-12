import {
  useId,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes
} from 'react';

const fieldClass =
  'w-full rounded-md border border-theme-border bg-theme-card px-3 py-2 text-sm text-theme-text-primary';

export const projectActionClass =
  'rounded-md border border-theme-border px-3 py-2 text-sm font-medium text-theme-text-primary disabled:opacity-50';
export const projectSubmitClass =
  'rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50';

export function ProjectInput({
  label,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="block space-y-1 text-sm">
      <span>{label}</span>
      <input className={fieldClass} {...props} />
    </label>
  );
}

export function ProjectSelect({
  label,
  id,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  return (
    <div className="space-y-1 text-sm">
      <label className="block" htmlFor={controlId}>
        {label}
      </label>
      <select id={controlId} className={fieldClass} {...props} />
    </div>
  );
}

export function ProjectTextArea({
  label,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string }) {
  return (
    <label className="block space-y-1 text-sm">
      <span>{label}</span>
      <textarea className={fieldClass} {...props} />
    </label>
  );
}
