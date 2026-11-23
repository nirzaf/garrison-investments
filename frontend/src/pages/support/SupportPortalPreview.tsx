import { useEffect, useState } from 'react';

import type { components } from '../../api/schema';
import { supportPost, supportRequest } from '../../api/support';
import { buttonClass, panelCardClass, statusLabel } from './supportPanelUtils';

type Preview = components['schemas']['SupportPortalPreview'];
type Destination = { page: 'home' | 'projects' } | { page: 'project'; label: string };

export function SupportPortalPreview({
  viewId,
  onExit,
  onExpired
}: {
  viewId: string;
  onExit: () => void;
  onExpired: () => void;
}) {
  const [destination, setDestination] = useState<Destination>({ page: 'home' });
  const [data, setData] = useState<Preview | null>(null);
  const [pending, setPending] = useState(true);
  const [ending, setEnding] = useState(false);
  const [error, setError] = useState('');
  const [endError, setEndError] = useState('');
  const [expired, setExpired] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setPending(true);
      setError('');
      const qs = new URLSearchParams({ page: destination.page });
      if (destination.page === 'project') qs.set('project', destination.label);
      try {
        const response = await supportRequest(`/portal-preview/${viewId}?${qs}`, {
          signal: controller.signal
        });
        if (controller.signal.aborted) return;
        if (response.status === 401) return onExpired();
        if ([403, 404, 409].includes(response.status)) {
          setExpired(true);
          setData(null);
          return;
        }
        if (!response.ok) {
          setError('The preview could not be loaded. Select the page again to retry.');
          return;
        }
        const payload = (await response.json()) as Preview;
        if (!controller.signal.aborted) setData(payload);
      } catch {
        if (!controller.signal.aborted) setError('The preview could not be loaded.');
      } finally {
        if (!controller.signal.aborted) setPending(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [destination, onExpired, viewId]);

  async function exit() {
    if (ending) return;
    setEnding(true);
    setEndError('');
    try {
      const response = await supportPost(`/portal-preview/${viewId}/end`, {});
      if (response.status === 401) return onExpired();
      if (response.ok || response.status === 404) return onExit();
      setEndError('Could not end the preview. Try again.');
    } catch {
      setEndError('Could not end the preview. Try again.');
    } finally {
      setEnding(false);
    }
  }

  const seconds = data ? Math.max(0, Math.ceil((Date.parse(data.expires_at) - now) / 1_000)) : null;
  const unavailable = expired || seconds === 0;

  return (
    <div className="space-y-4">
      <header
        className="sticky top-0 z-10 space-y-2 rounded-lg border border-amber-600 bg-theme-card p-4"
        role="banner"
        aria-label="Read-only support session"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="font-semibold">
              {data && !unavailable ? `Viewing as: ${data.subject_name}` : 'Portal preview'} ·
              Read-only support session
            </h1>
            {data && !unavailable && (
              <p className="text-sm">
                {data.role_label} · Case {data.case_reference} · {seconds}s remaining
              </p>
            )}
          </div>
          <button
            className={buttonClass}
            type="button"
            onClick={() => void exit()}
            disabled={ending}
          >
            {ending ? 'Ending…' : 'Exit User View'}
          </button>
        </div>
        {endError && <p role="alert">{endError}</p>}
      </header>
      {unavailable ? (
        <p role="alert">
          This preview expired or its authorization changed. Exit to return to Super Admin.
        </p>
      ) : (
        <>
          {data && (
            <nav className="flex flex-wrap gap-2" aria-label="Preview navigation">
              <button
                className={buttonClass}
                type="button"
                onClick={() => setDestination({ page: 'home' })}
              >
                Dashboard
              </button>
              {data.routes.includes('projects') && (
                <button
                  className={buttonClass}
                  type="button"
                  onClick={() => setDestination({ page: 'projects' })}
                >
                  Projects
                </button>
              )}
            </nav>
          )}
          {pending ? (
            <p role="status">Loading approved preview…</p>
          ) : error ? (
            <p role="alert">{error}</p>
          ) : (
            data && (
              <section className={panelCardClass}>
                {destination.page === 'home' && (
                  <>
                    <h2 className="font-semibold">Dashboard · navigation and access</h2>
                    <ul className="grid gap-2 text-sm sm:grid-cols-2">
                      {data.routes.map((route) => (
                        <li key={route}>
                          {route.replace(/-/g, ' ')}{' '}
                          {['dashboard', 'projects'].includes(route)
                            ? '· preview available'
                            : '· data unavailable in preview'}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {destination.page === 'projects' && (
                  <>
                    <h2 className="font-semibold">Projects in the approved case</h2>
                    {data.projects.length ? (
                      <ul className="space-y-2">
                        {data.projects.map((project) => (
                          <li key={project.label}>
                            <button
                              className={buttonClass}
                              type="button"
                              onClick={() =>
                                setDestination({ page: 'project', label: project.label })
                              }
                            >
                              {project.label}
                            </button>{' '}
                            {statusLabel(project.status)}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>No projects match the account’s access and case scope.</p>
                    )}
                  </>
                )}
                {destination.page === 'project' && data.project && (
                  <>
                    <h2 className="font-semibold">{data.project.label}</h2>
                    <p>Status {statusLabel(data.project.status)}</p>
                    <p>
                      Milestones {data.project.milestones} · Tasks {data.project.tasks}
                      {data.project.counts_capped ? ' · counts capped' : ''}
                    </p>
                  </>
                )}
              </section>
            )
          )}
        </>
      )}
    </div>
  );
}
