import { useQuery } from '@tanstack/react-query';
import { useId, useState } from 'react';

import { formatApiError } from '../../api/errors';
import { listInvoiceSupplierOptions } from '../../api/finance';
import { listProjects } from '../../api/projects';
import { useDebouncedSearch } from '../../useDebouncedSearch';

const pageSize = 20;

export function FinancePicker({
  kind,
  label,
  value,
  selectedName,
  required,
  onChange
}: {
  kind: 'project' | 'supplier';
  label: string;
  value: string;
  selectedName?: string | null;
  required?: boolean;
  onChange: (id: string) => void;
}) {
  const id = useId();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [name, setName] = useState<string>();
  const query = useDebouncedSearch(search);
  const options = useQuery({
    queryKey:
      kind === 'supplier'
        ? ['finance-supplier-options', query, page]
        : ['projects', 'finance-picker', query, page],
    queryFn: async () => {
      const params = { search: query || undefined, limit: pageSize, offset: page * pageSize };
      const result =
        kind === 'supplier' ? await listInvoiceSupplierOptions(params) : await listProjects(params);
      return { items: result.items.map(({ id, name }) => ({ id, name })), total: result.total };
    }
  });
  const items = options.data?.items ?? [];

  return (
    <div className="space-y-2">
      <label className="block text-sm">
        Search {label.toLowerCase()} options
        <input
          type="search"
          maxLength={100}
          className="form-field mt-1 w-full"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(0);
          }}
        />
      </label>
      <label htmlFor={id} className="block text-sm">
        {label}
      </label>
      <select
        id={id}
        className="form-field w-full"
        value={value}
        required={required}
        onChange={(event) => {
          setName(items.find((option) => option.id === event.target.value)?.name);
          onChange(event.target.value);
        }}
      >
        <option value="">
          {required ? 'Choose a project' : kind === 'supplier' ? 'No supplier' : 'All projects'}
        </option>
        {value && !items.some((option) => option.id === value) && (
          <option value={value}>{name || selectedName || 'Selected record'}</option>
        )}
        {items.map((option) => (
          <option key={option.id} value={option.id}>
            {option.name}
          </option>
        ))}
      </select>
      {options.isPending && (
        <p role="status" className="text-xs">
          Loading options…
        </p>
      )}
      {options.isError && (
        <div role="alert" className="text-xs">
          <p>{formatApiError(options.error, 'Unable to load options.')}</p>
          <button className="underline" type="button" onClick={() => void options.refetch()}>
            Retry options
          </button>
        </div>
      )}
      {options.isSuccess && !items.length && (
        <p className="text-xs">No options match this search.</p>
      )}
      {Boolean(page || (options.data?.total ?? 0) > pageSize) && (
        <div className="flex flex-wrap gap-3 text-xs">
          <button
            type="button"
            className="underline disabled:opacity-50"
            disabled={!page || options.isFetching}
            onClick={() => setPage(page - 1)}
          >
            Previous options
          </button>
          <button
            type="button"
            className="underline disabled:opacity-50"
            disabled={
              !options.data || (page + 1) * pageSize >= options.data.total || options.isFetching
            }
            onClick={() => setPage(page + 1)}
          >
            Next options
          </button>
        </div>
      )}
    </div>
  );
}
