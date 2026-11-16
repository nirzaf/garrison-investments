import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { getHrDocumentDownloadUrl, listHrDocuments } from '../../api/hr';

export type ContractVersion = {
  documentId: string;
  version: number;
  title: string;
  expires: string;
  active: boolean;
};

export function HRContractVersionLink({
  documentId,
  version,
  label
}: {
  documentId: string;
  version: number;
  label: string;
}) {
  const download = useMutation({
    mutationFn: () => getHrDocumentDownloadUrl(documentId, version),
    onSuccess: ({ download_url }) => window.location.assign(download_url)
  });
  return (
    <p>
      <button type="button" className="text-brand-600 underline" disabled={download.isPending}
        onClick={() => download.mutate()}>{label} · version {version}</button>
      {download.isError && <span role="alert">{formatApiError(download.error, 'Could not download this contract.')}</span>}
    </p>
  );
}

const pageSize = 20;
const keyOf = (value?: ContractVersion) => value ? `${value.documentId}:${value.version}` : '';

export function HRContractRenewal({
  employeeId,
  current,
  renewal,
  onChange
}: {
  employeeId: string;
  current?: ContractVersion;
  renewal?: ContractVersion;
  onChange: (kind: 'current' | 'renewal', value?: ContractVersion) => void;
}) {
  const [offset, setOffset] = useState(0);
  const documents = useQuery({
    queryKey: ['hr', 'contract-evidence', employeeId, offset],
    queryFn: () => listHrDocuments({ employee_id: employeeId, document_type: 'contract', limit: pageSize, offset })
  });
  const options = (documents.data?.items ?? []).flatMap((doc) => {
    const expires = doc.expiry_date;
    if (doc.status !== 'active' || !expires || doc.candidate_id) return [];
    return (doc.versions ?? [])
      .filter((version) => ['active', 'superseded'].includes(version.status))
      .map((version) => ({
        documentId: doc.id,
        version: version.version_number,
        title: doc.title,
        expires,
        active: version.status === 'active'
      }));
  });

  function select(kind: 'current' | 'renewal', selected?: ContractVersion) {
    const eligible = options.filter((option) => kind === 'current' || option.active);
    if (selected && !eligible.some((option) => keyOf(option) === keyOf(selected))) eligible.push(selected);
    return (
      <div>
        <label className="block">
          {kind === 'current' ? 'Current contract version' : 'Renewal contract version'}
          <select required value={keyOf(selected)}
            className="block rounded border border-theme-border bg-theme-input px-2 py-1"
            onChange={(event) => onChange(kind, eligible.find((item) => keyOf(item) === event.target.value))}>
            <option value="">Select an approved contract</option>
            {eligible.map((option) => (
              <option key={keyOf(option)} value={keyOf(option)}>
                {option.title} · v{option.version} · ends {option.expires}
                {!option.active && ' · superseded'}
              </option>
            ))}
          </select>
        </label>
        {selected && <HRContractVersionLink documentId={selected.documentId} version={selected.version}
          label={kind === 'current' ? 'Open current evidence' : 'Open renewal evidence'} />}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {documents.isPending && <p role="status">Loading contract documents…</p>}
      {documents.isError && (
        <p role="alert">
          {formatApiError(documents.error, 'Could not load contract documents.')}{' '}
          <button type="button" onClick={() => void documents.refetch()}>Retry</button>
        </p>
      )}
      {documents.isSuccess && !options.length && <p>No approved contracts with expiry dates on this page.</p>}
      {select('current', current)}
      {select('renewal', renewal)}
      {renewal && <p>Renewed contract ends {renewal.expires}</p>}
      {documents.data && documents.data.total > pageSize && (
        <div className="flex gap-2">
          <button type="button" disabled={!offset} onClick={() => setOffset(offset - pageSize)}>Previous contracts</button>
          <button type="button" disabled={offset + pageSize >= documents.data.total}
            onClick={() => setOffset(offset + pageSize)}>Next contracts</button>
        </div>
      )}
    </div>
  );
}
