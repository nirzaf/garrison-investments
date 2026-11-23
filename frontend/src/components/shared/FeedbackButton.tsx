import { MessageSquare } from 'lucide-react';
import { useRef, useState, type FormEvent } from 'react';

import { apiClient } from '../../api/client';
import { formatApiError } from '../../api/errors';
import { recentFeedbackRequests } from '../../api/feedbackDiagnostics';
import type { components } from '../../api/schema';

type FeedbackCreate = components['schemas']['FeedbackCreate'];
type Receipt = components['schemas']['FeedbackReceipt'];

const fieldClass =
  'mt-1 block w-full rounded-md border border-theme-border bg-theme-card px-3 py-2';

export function FeedbackButton({ screen }: { screen: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const request = useRef<FeedbackCreate | null>(null);
  const submitting = useRef(false);
  const [category, setCategory] = useState<FeedbackCreate['category']>('bug');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [includeDiagnostics, setIncludeDiagnostics] = useState(false);
  const [references, setReferences] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [receipt, setReceipt] = useState<Receipt | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    if (title.trim().length < 3 || description.trim().length < 10) {
      setError('Enter a summary and at least 10 characters of detail.');
      return;
    }
    submitting.current = true;
    setPending(true);
    setError('');
    try {
      request.current ??= {
        submission_id: crypto.randomUUID(),
        category,
        title,
        description,
        request_ids: includeDiagnostics ? references : []
      };
      const response = await apiClient.post<Receipt>('/feedback', request.current);
      setReceipt(response.data);
      setTitle('');
      setDescription('');
      setCategory('bug');
      setIncludeDiagnostics(false);
      request.current = null;
    } catch (err) {
      setError(formatApiError(err, 'Feedback could not be sent. Your report is still here.'));
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label="Send feedback"
        className="inline-flex min-h-10 items-center gap-2 rounded-md border border-theme-border px-2.5 text-sm text-theme-text-secondary hover:bg-theme-card-elevated focus-visible:outline-2 focus-visible:outline-brand-600"
        onClick={() => {
          if (!request.current) setReferences(recentFeedbackRequests());
          dialog.current?.showModal();
        }}
      >
        <MessageSquare className="size-4" aria-hidden="true" />
        <span className="hidden sm:inline">Feedback</span>
      </button>

      <dialog
        ref={dialog}
        aria-labelledby="feedback-heading"
        onCancel={(event) => {
          if (submitting.current) event.preventDefault();
        }}
        onClose={() => {
          setReceipt(null);
          trigger.current?.focus();
        }}
        className="fixed inset-0 m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg overflow-auto rounded-xl border border-theme-border bg-theme-card p-5 text-theme-text-primary shadow-xl backdrop:bg-black/50 sm:p-6"
      >
        <h2 id="feedback-heading" className="text-lg font-semibold">
          Send feedback
        </h2>
        {receipt ? (
          <div className="mt-3 space-y-4">
            <div role="status" className="space-y-1 text-sm">
              <p className="font-medium">Feedback received.</p>
              <p>
                Reference <code className="break-all">{receipt.id}</code>
              </p>
              <p>
                {receipt.attached_diagnostics} failed request{' '}
                {receipt.attached_diagnostics === 1 ? 'summary' : 'summaries'} attached.
              </p>
            </div>
            <button
              type="button"
              className="min-h-10 rounded-md border border-theme-border px-3"
              onClick={() => dialog.current?.close()}
            >
              Done
            </button>
          </div>
        ) : (
          <form className="mt-3 space-y-4 text-sm" onSubmit={(event) => void submit(event)}>
            <p className="text-theme-text-secondary">
              Report a problem or suggest an improvement. Leave out passwords, codes, and private
              records.
            </p>
            <fieldset
              className="space-y-3"
              disabled={pending}
              onChange={() => {
                request.current = null;
              }}
            >
              <label className="block">
                Type
                <select
                  className={fieldClass}
                  value={category}
                  onChange={(event) =>
                    setCategory(event.target.value as FeedbackCreate['category'])
                  }
                >
                  <option value="bug">Bug report</option>
                  <option value="suggestion">Suggestion</option>
                  <option value="other">Other feedback</option>
                </select>
              </label>
              <label className="block">
                Summary
                <input
                  required
                  minLength={3}
                  maxLength={140}
                  className={fieldClass}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              <label className="block">
                Details
                <textarea
                  required
                  minLength={10}
                  maxLength={4000}
                  rows={4}
                  className={fieldClass}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder={`What happened on ${screen}? What did you expect?`}
                />
              </label>
              <label className="flex items-start gap-2">
                <input
                  className="mt-0.5 size-4 shrink-0"
                  type="checkbox"
                  checked={includeDiagnostics}
                  onChange={(event) => setIncludeDiagnostics(event.target.checked)}
                />
                <span>
                  Include recent failed request summaries
                  <span className="block text-xs text-theme-text-secondary">
                    {references.length
                      ? `${references.length} available from the last 30 minutes. Includes references, times, areas, methods, and status codes.`
                      : 'No failed request summaries are available from the last 30 minutes.'}
                  </span>
                </span>
              </label>
            </fieldset>
            {error && (
              <p role="alert" className="text-red-700 dark:text-red-300">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                disabled={pending}
                className="min-h-10 rounded-md border border-theme-border px-3 disabled:opacity-50"
                onClick={() => dialog.current?.close()}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={pending}
                className="min-h-10 rounded-md bg-brand-600 px-3 font-medium text-white disabled:opacity-50"
              >
                {pending ? 'Sending…' : 'Send report'}
              </button>
            </div>
          </form>
        )}
      </dialog>
    </>
  );
}
