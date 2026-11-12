import { useEffect, useState } from 'react';

export function useDebouncedSearch(search: string) {
  const [debouncedSearch, setDebouncedSearch] = useState(() => search.trim());

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  return debouncedSearch;
}
