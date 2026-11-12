import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { formatApiError } from '../../api/errors';
import { listUsers } from '../../api/users';
import { useDebouncedSearch } from '../../useDebouncedSearch';
import { ProjectInput, ProjectSelect, projectActionClass } from './ProjectFields';

const pageSize = 15;

export function ProjectUserPicker({
  label,
  value,
  selectedName,
  required,
  onChange
}: {
  label: string;
  value: string;
  selectedName?: string;
  required?: boolean;
  onChange: (id: string) => void;
}) {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [chosenName, setChosenName] = useState(selectedName);
  const query = useDebouncedSearch(search);
  const users = useQuery({
    queryKey: ['users', 'project-picker', query, page],
    queryFn: () =>
      listUsers({
        active: true,
        search: query || undefined,
        offset: page * pageSize,
        limit: pageSize
      })
  });
  const items = users.data?.items ?? [];

  return (
    <div className="space-y-2">
      <ProjectInput
        label={`Search ${label.toLowerCase()} options`}
        type="search"
        maxLength={100}
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
          setPage(0);
        }}
      />
      <ProjectSelect
        label={label}
        value={value}
        required={required}
        onChange={(event) => {
          const user = items.find((item) => item.id === event.target.value);
          setChosenName(user?.full_name);
          onChange(event.target.value);
        }}
      >
        <option value="">{required ? 'Select an active user' : 'Unassigned'}</option>
        {value && !items.some((item) => item.id === value) && (
          <option value={value}>{chosenName || 'Selected user'}</option>
        )}
        {items.map((item) => (
          <option key={item.id} value={item.id}>
            {item.full_name} ({item.email})
          </option>
        ))}
      </ProjectSelect>
      {users.isPending && (
        <p role="status" className="text-sm">
          Loading users…
        </p>
      )}
      {users.isError && (
        <div role="alert" className="text-sm">
          <p>{formatApiError(users.error, 'Unable to load active users.')}</p>
          <button className={projectActionClass} type="button" onClick={() => void users.refetch()}>
            Retry users
          </button>
        </div>
      )}
      {users.isSuccess && !items.length && <p className="text-sm">No active users match.</p>}
      <div className="flex flex-wrap gap-2">
        <button
          className={projectActionClass}
          type="button"
          disabled={page === 0 || users.isFetching}
          onClick={() => setPage(page - 1)}
        >
          Previous users
        </button>
        <button
          className={projectActionClass}
          type="button"
          disabled={!users.data || (page + 1) * pageSize >= users.data.total || users.isFetching}
          onClick={() => setPage(page + 1)}
        >
          Next users
        </button>
      </div>
    </div>
  );
}
