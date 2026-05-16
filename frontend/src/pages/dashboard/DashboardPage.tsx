import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../api/client';

type ApiRoot = {
  name: string;
  version: string;
  status: string;
};

async function fetchApiRoot() {
  const response = await apiClient.get<ApiRoot>('/');
  return response.data;
}

export function DashboardPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['api-root'],
    queryFn: fetchApiRoot,
    retry: 1
  });

  return (
    <section className="space-y-8">
      <div className="max-w-3xl">
        <p className="text-sm font-medium text-brand-700">Operational overview</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-normal text-slate-950 sm:text-3xl">
          Portal workspace
        </h2>
        <p className="mt-3 text-base leading-7 text-slate-600">
          Use the navigation to reach the modules available to your role. This dashboard will be
          expanded with project, report, inventory, and finance summaries in later stories.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <StatusPanel label="Frontend" value="React + Vite" />
        <StatusPanel label="API" value={isLoading ? 'Checking' : (data?.status ?? 'Unavailable')} />
        <StatusPanel label="Version" value={isError ? 'API error' : (data?.version ?? 'v1')} />
      </div>
    </section>
  );
}

function StatusPanel({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}
