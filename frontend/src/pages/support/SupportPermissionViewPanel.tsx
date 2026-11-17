import { useEffect, useState, type FormEvent } from 'react';

import type { components } from '../../api/schema';
import { supportPost, supportRequest } from '../../api/support';

type Explanation = components['schemas']['SupportPermissionExplanation'];
type Summary = components['schemas']['SupportRequestSummary'];
type Navigation = components['schemas']['SupportNavigationProjection'];
type ProjectList = components['schemas']['SupportProjectList'];
type ProjectDetail = components['schemas']['SupportProjectDetail'];
type Projection = Explanation | Summary | Navigation | ProjectList | ProjectDetail;
type Adapter = NonNullable<Projection['adapter']>;
const uuid = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const idleTimeoutMs = 10 * 60 * 1000;

export function SupportPermissionViewPanel({ onExpired }: { onExpired: () => void }) {
  const [reference, setReference] = useState('');
  const [adapter, setAdapter] = useState<Adapter>('permission-explanation');
  const [result, setResult] = useState<{ projection: Projection; expires: number }>();
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!result) return;
    const timer = window.setTimeout(() => {
      setResult(undefined);
      setNotice('Support view expired.');
    }, Math.max(0, result.expires - Date.now()));
    return () => window.clearTimeout(timer);
  }, [result]);

  async function read(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setResult(undefined);
    setNotice('');
    setError('');
    try {
      const started = Date.now();
      const response = await supportRequest(
        '/views/' + encodeURIComponent(reference) + '/projection/' + adapter
      );
      if (response.status === 401) return onExpired();
      if (!response.ok) {
        setError('The reviewed support view is unavailable to this session.');
        return;
      }
      const projection = await response.json() as Projection;
      const expires = Math.min(Date.parse(projection.expires_at), started + idleTimeoutMs);
      if (projection.adapter !== adapter || projection.view_id !== reference.toLowerCase() || !(expires > Date.now())) {
        throw new Error();
      }
      setResult({ projection, expires });
    } catch {
      setError('The support view could not be loaded.');
    } finally {
      setPending(false);
    }
  }

  async function end() {
    if (!result || pending) return;
    const viewId = result.projection.view_id;
    setPending(true);
    setResult(undefined);
    setNotice('');
    setError('');
    try {
      const response = await supportPost('/views/' + encodeURIComponent(viewId) + '/end', {});
      if (response.status === 401) return onExpired();
      if (!response.ok) throw new Error();
      setReference('');
      setNotice('Support view ended.');
    } catch {
      setError('The end request could not be confirmed.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Reviewed support view" className="space-y-2 border-t pt-3">
      <h2 className="font-semibold">Reviewed support view</h2>
      <form onSubmit={(event) => void read(event)} className="space-y-2">
        <label className="block">
          Approved support view reference
          <input value={reference} disabled={pending} required pattern={uuid}
            onChange={(event) => {
              setReference(event.target.value);
              setResult(undefined);
              setNotice('');
              setError('');
            }}
            className="block w-full rounded border p-2" />
        </label>
        <label className="block">
          View type
          <select value={adapter} disabled={pending} className="block rounded border p-2"
            onChange={(event) => {
              setAdapter(event.target.value as Adapter);
              setResult(undefined);
              setError('');
              setNotice('');
            }}>
            <option value="permission-explanation">Role permission</option>
            <option value="navigation">Portal navigation</option>
            <option value="project-list">Masked project list</option>
            <option value="project-detail-summary">Masked project detail</option>
            <option value="request-summary">Request summary</option>
          </select>
        </label>
        <button type="submit" disabled={pending}>Load support view</button>
      </form>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {result && (
        <div className="space-y-2">
          {result.projection.adapter === 'request-summary' ? (
            <>
              <p>HTTP {result.projection.method} {result.projection.status_code}</p>
              <p className="break-all">Request {result.projection.request_ref}</p>
              <p>Observed <time dateTime={result.projection.occurred_at}>
                {new Date(result.projection.occurred_at).toLocaleString()}
              </time></p>
            </>
          ) : result.projection.adapter === 'navigation' ? (
            <ul aria-label="Portal menu visibility" className="grid gap-1 sm:grid-cols-2">
              {result.projection.routes.map((route) => (
                <li key={route.route_id}>
                  <code>{route.route_id}</code> {route.visible ? 'Visible' : 'Hidden'}
                </li>
              ))}
            </ul>
          ) : result.projection.adapter === 'project-list' ? (
            result.projection.projects.length > 0 ? (
              <ul aria-label="Masked projects">
                {result.projection.projects.map((project) => (
                  <li key={project.label}>{project.label} · {project.status.replace(/_/g, ' ')}</li>
                ))}
              </ul>
            ) : <p>No approved projects are visible to the account.</p>
          ) : result.projection.adapter === 'project-detail-summary' ? (
            <div aria-label="Masked project summary">
              <p>{result.projection.project.label} · {result.projection.project.status.replace(/_/g, ' ')}</p>
              <p>Milestones {result.projection.project.milestones} · Tasks {result.projection.project.tasks}</p>
              {result.projection.project.counts_capped && <p>Counts are capped at 100 per category.</p>}
            </div>
          ) : (
            <>
              <p>Role permission <code>{result.projection.permission_key}</code></p>
              <p>{result.projection.allowed ? 'Granted by the account role' : 'Absent from the account role'}</p>
            </>
          )}
          <p className="break-all">Operator {result.projection.operator_id}</p>
          <p className="break-all">Case {result.projection.case_id}</p>
          <p className="break-all">Account {result.projection.subject_id}</p>
          <p>Expires <time dateTime={new Date(result.expires).toISOString()}>
            {new Date(result.expires).toLocaleString()}
          </time></p>
          <button type="button" disabled={pending} onClick={() => void end()}>End support view</button>
        </div>
      )}
    </section>
  );
}
