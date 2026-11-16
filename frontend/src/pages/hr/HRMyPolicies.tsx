import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { formatApiError } from '../../api/errors';
import {
  acknowledgeMyPolicy,
  downloadMyPolicy,
  listMyPolicies,
  type HrSchemas
} from '../../api/hr';
import { hrButtonClass } from './HRAccessForms';

const policyKey = ['hr', 'me', 'policies'];

export function HRMyPolicies() {
  const client = useQueryClient();
  const policies = useQuery({ queryKey: policyKey, queryFn: listMyPolicies });
  const acknowledge = useMutation({
    mutationFn: (policy: HrSchemas['MyPolicyResponse']) =>
      acknowledgeMyPolicy(policy.id, {
        expected_version: policy.version,
        expected_document_version: policy.document_version_number
      }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: policyKey });
    }
  });
  const download = useMutation({
    mutationFn: downloadMyPolicy,
    onSuccess: (file) => window.location.assign(file.download_url)
  });
  const pending = acknowledge.isPending || download.isPending;

  return (
    <section className="space-y-2" aria-label="Published policies">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-theme-text-primary">Published Policies</h3>
        <button
          type="button"
          className={hrButtonClass}
          disabled={pending || policies.isFetching}
          onClick={() => void policies.refetch()}
        >
          Reload policies
        </button>
      </div>
      {policies.isPending && <p role="status">Loading policies…</p>}
      {policies.isSuccess && policies.data.items.length === 0 && <p>No published policies.</p>}
      {policies.isError && (
        <p role="alert">{formatApiError(policies.error, 'Could not load policies.')}</p>
      )}
      {acknowledge.isError && (
        <p role="alert">
          {formatApiError(
            acknowledge.error,
            'Could not acknowledge this edition. Reload policies and try again.'
          )}
        </p>
      )}
      {download.isError && (
        <p role="alert">
          {formatApiError(download.error, 'Could not download this policy edition.')}
        </p>
      )}
      {policies.data?.items.map((policy) => (
        <article
          key={policy.id}
          className="space-y-2 rounded border border-theme-border px-3 py-2 text-sm"
        >
          <h4 className="font-medium">
            {policy.title} v{policy.version}
            {!policy.is_current && ' · Previous edition'}
          </h4>
          <p>{policy.content_summary}</p>
          {policy.acknowledged_at && (
            <p>Acknowledged {new Date(policy.acknowledged_at).toLocaleDateString()}</p>
          )}
          {policy.document_id && !policy.document_version_number && (
            <p>HR review required to confirm this edition’s file.</p>
          )}
          <div className="flex flex-wrap gap-2">
            {policy.document_version_number && (
              <button
                type="button"
                className={hrButtonClass}
                disabled={pending}
                onClick={() => {
                  acknowledge.reset();
                  download.mutate(policy.id);
                }}
              >
                Download policy file v{policy.document_version_number}
              </button>
            )}
            {policy.is_current &&
              policy.requires_acknowledgement &&
              !policy.acknowledged_at &&
              (!policy.document_id || policy.document_version_number) && (
                <button
                  type="button"
                  className={hrButtonClass}
                  disabled={pending}
                  onClick={() => {
                    download.reset();
                    acknowledge.mutate(policy);
                  }}
                >
                  Acknowledge policy edition
                </button>
              )}
          </div>
        </article>
      ))}
    </section>
  );
}
