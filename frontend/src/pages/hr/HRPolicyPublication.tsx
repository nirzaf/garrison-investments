import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { createPolicy, listHrDocuments, type PolicyDocumentRecord } from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

const pageSize = 20;

export function HRPolicyPublication({
  policies,
  canPublish,
  refresh
}: {
  policies: PolicyDocumentRecord[];
  canPublish: boolean;
  refresh: () => Promise<void>;
}) {
  const [includeFile, setIncludeFile] = useState(false);
  const [offset, setOffset] = useState(0);
  const docs = useQuery({
    queryKey: ['hr', 'policy-publication-docs', offset],
    queryFn: () =>
      listHrDocuments({
        document_type: 'policy',
        category: 'ordinary',
        limit: pageSize,
        offset
      }),
    enabled: includeFile
  });
  const pub = useMutation({
    mutationFn: createPolicy,
    onSuccess: async () => {
      await refresh();
    }
  });
  const replacedIds = new Set(policies.flatMap((row) => row.supersedes_policy_id ?? []));
  const eligibleDocs =
    docs.data?.items.filter(
      (row) =>
        row.status === 'active' && row.current_version > 0 && !row.employee_id && !row.candidate_id
    ) ?? [];

  return (
    <section className="rounded-lg border border-theme-border bg-theme-card p-5 space-y-3">
      <h3 className="text-base font-semibold">HR Policies ({policies.length})</h3>
      {canPublish && (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (pub.isPending) return;
            const form = event.currentTarget;
            const fields = new FormData(form);
            const field = (key: string) => String(fields.get(key) ?? '').trim();
            const [documentId, version] = field('file_version').split(':');
            pub.mutate(
              {
                code: field('code'),
                title: field('title'),
                version: field('version'),
                effective_date: field('effective'),
                content_summary: field('summary'),
                document_id: includeFile ? documentId : null,
                document_version_number: includeFile ? Number(version) : null,
                supersedes_policy_id: field('predecessor') || null,
                requires_acknowledgement: fields.has('acknowledge')
              },
              {
                onSuccess: () => {
                  form.reset();
                  setIncludeFile(false);
                  setOffset(0);
                }
              }
            );
          }}
        >
          <fieldset className="grid gap-2 sm:grid-cols-2" disabled={pub.isPending}>
            <label>
              Policy code
              <input className={hrInputClass} name="code" required maxLength={40} />
            </label>
            <label>
              Policy title
              <input className={hrInputClass} name="title" required minLength={2} maxLength={200} />
            </label>
            <label>
              Policy edition
              <input
                className={hrInputClass}
                name="version"
                defaultValue="1.0"
                required
                maxLength={20}
              />
            </label>
            <label>
              Policy effective date
              <input className={hrInputClass} name="effective" type="date" required />
            </label>
            <label className="sm:col-span-2">
              Replaces policy edition
              <select className={hrInputClass} name="predecessor" defaultValue="">
                <option value="">New policy</option>
                {policies
                  .filter((row) => !replacedIds.has(row.id))
                  .map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.title} v{row.version} ({row.code})
                    </option>
                  ))}
              </select>
            </label>
            <label className="sm:col-span-2">
              Policy summary
              <textarea className={hrInputClass} name="summary" minLength={5} required rows={2} />
            </label>
            <label className="sm:col-span-2">
              <input type="checkbox" name="acknowledge" defaultChecked /> Require acknowledgement
            </label>
            <label className="sm:col-span-2">
              <input
                type="checkbox"
                checked={includeFile}
                onChange={(event) => setIncludeFile(event.target.checked)}
              />{' '}
              Attach approved company policy file
            </label>
            {includeFile && (
              <div className="space-y-2 sm:col-span-2">
                <label>
                  Policy file version
                  <select
                    className={hrInputClass}
                    name="file_version"
                    required
                    key={offset}
                    defaultValue=""
                  >
                    <option value="">Choose the approved version</option>
                    {eligibleDocs.map((row) => (
                      <option key={row.id} value={`${row.id}:${row.current_version}`}>
                        {row.title} · v{row.current_version}
                      </option>
                    ))}
                  </select>
                </label>
                {docs.isPending && <p role="status">Loading approved policy files…</p>}
                {docs.isSuccess && !eligibleDocs.length && (
                  <p>No approved policy files on this page.</p>
                )}
                {docs.isError && (
                  <p role="alert">{formatApiError(docs.error, 'Could not load policy files.')}</p>
                )}
                {offset > 0 && (
                  <button
                    className={hrButtonClass}
                    type="button"
                    onClick={() => setOffset(offset - pageSize)}
                  >
                    Previous policy files
                  </button>
                )}
                {offset + pageSize < (docs.data?.total ?? 0) && (
                  <button
                    className={hrButtonClass}
                    type="button"
                    onClick={() => setOffset(offset + pageSize)}
                  >
                    Next policy files
                  </button>
                )}
              </div>
            )}
            <button type="submit" className={hrButtonClass}>
              {pub.isPending ? 'Publishing…' : 'Publish policy'}
            </button>
          </fieldset>
        </form>
      )}
      {pub.isError && <p role="alert">{formatApiError(pub.error, 'Policy publish failed.')}</p>}
      {pub.isSuccess && <p role="status">Policy edition published.</p>}
      <ul className="space-y-1 text-sm">
        {policies.map((row) => (
          <li key={row.id}>
            {row.title} v{row.version} · {row.effective_date}
            {row.document_version_number ? ` · File v${row.document_version_number}` : ''}
          </li>
        ))}
      </ul>
    </section>
  );
}
