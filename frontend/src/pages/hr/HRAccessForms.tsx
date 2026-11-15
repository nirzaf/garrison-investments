import { type FormEvent, useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  createAccessRequest,
  decideAccessRequest,
  type AccessRequestRecord,
  type EmployeeDetailRecord,
  type EmployeeDirectoryRecord
} from '../../api/hr';
import rolePermissions from '../roles/rolePermissions.json';

export const hrInputClass = 'w-full rounded border border-theme-border bg-theme-input px-2 py-1.5';
export const hrButtonClass =
  'rounded bg-brand-600 px-3 py-1.5 font-semibold text-white disabled:opacity-50';

type Props = {
  employees: EmployeeDirectoryRecord[];
  selectedEmployee: EmployeeDetailRecord | null;
  requests: AccessRequestRecord[];
  canRequest: boolean;
  canReview: boolean;
  canFulfill: boolean;
  actorId?: string;
  onChange: () => Promise<void>;
};

type RequestType = 'provision' | 'link_existing' | 'role_change' | 'deactivate' | 'reactivate';

export function HRAccessForms({
  employees,
  selectedEmployee,
  requests,
  canRequest,
  canReview,
  canFulfill,
  actorId,
  onChange
}: Props) {
  const [requestType, setRequestType] = useState<RequestType>('provision');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  async function mutate(action: () => Promise<unknown>) {
    if (pending) return;
    setPending(true);
    setError('');
    try {
      await action();
      await onChange();
    } catch (failure) {
      setError(formatApiError(failure, 'Could not update the access request.'));
    } finally {
      setPending(false);
    }
  }

  function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void mutate(async () => {
      await createAccessRequest({
        employee_id: String(data.get('employee')),
        request_type: requestType,
        requested_role: String(data.get('role') ?? '') || null,
        justification: String(data.get('reason') ?? '') || null,
        portal_access_required: requestType !== 'deactivate',
        submit_immediately: true
      });
      form.reset();
    });
  }

  return (
    <div className="space-y-4 text-sm">
      {error && (
        <p role="alert" className="text-red-700">
          {error}
        </p>
      )}
      {canRequest && (
        <form className="space-y-2" onSubmit={submitRequest}>
          <label className="block">
            Employee{' '}
            <input
              name="employee"
              list="hr-access-employees"
              className={hrInputClass}
              defaultValue={selectedEmployee?.id}
              key={selectedEmployee?.id}
              required
            />
          </label>
          <datalist id="hr-access-employees">
            {employees.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employee.full_name} ({employee.employee_code})
              </option>
            ))}
          </datalist>
          <label className="block">
            Requested action{' '}
            <select
              className={hrInputClass}
              value={requestType}
              onChange={(event) => setRequestType(event.target.value as RequestType)}
            >
              <option value="provision">Provision an account</option>
              <option value="link_existing">Link an existing account</option>
              <option value="role_change">Change role</option>
              <option value="deactivate">Deactivate access</option>
              <option value="reactivate">Reactivate access</option>
            </select>
          </label>
          {['provision', 'role_change'].includes(requestType) && (
            <label className="block">
              Requested role{' '}
              <select name="role" className={hrInputClass} required defaultValue="">
                <option value="" disabled>
                  Select a role
                </option>
                {Object.keys(rolePermissions.roles).map((role) => (
                  <option key={role} value={role}>
                    {role.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="block">
            Justification <textarea name="reason" className={hrInputClass} required />
          </label>
          <button className={hrButtonClass} type="submit" disabled={pending}>
            Submit access request
          </button>
        </form>
      )}
      {requests.length === 0 && <p className="text-theme-text-muted">No access requests.</p>}
      {requests.map((request) => (
        <article key={request.id} className="space-y-2 rounded border border-theme-border p-3">
          <p className="font-medium">
            {request.request_type.replace(/_/g, ' ')} · {request.status.replace(/_/g, ' ')}
          </p>
          <p>
            {request.requested_role?.replace(/_/g, ' ')} {request.requested_email}
          </p>
          <p>{request.justification}</p>
          {request.status === 'draft' && request.requested_by_id === actorId && (
            <button
              type="button"
              className={hrButtonClass}
              disabled={pending}
              onClick={() =>
                void mutate(() => decideAccessRequest(request.id, { action: 'submit' }))
              }
            >
              Submit draft
            </button>
          )}
          {request.status === 'submitted' && canReview && request.requested_by_id !== actorId && (
            <button
              type="button"
              className={hrButtonClass}
              disabled={pending}
              onClick={() =>
                void mutate(() => decideAccessRequest(request.id, { action: 'hr_approve' }))
              }
            >
              HR approve
            </button>
          )}
          {request.status === 'hr_approved' && canFulfill && (
            <form
              className="space-y-2"
              onSubmit={(event) => {
                event.preventDefault();
                const form = event.currentTarget;
                const data = new FormData(form);
                void mutate(async () => {
                  await decideAccessRequest(request.id, {
                    action: 'admin_action',
                    ...(request.request_type === 'provision'
                      ? { temporary_password: String(data.get('password')) }
                      : {}),
                    ...(request.request_type === 'link_existing'
                      ? { link_existing_user_id: String(data.get('user_id')) }
                      : {})
                  });
                  form.reset();
                });
              }}
            >
              {request.request_type === 'provision' && (
                <label className="block">
                  Temporary password{' '}
                  <input
                    name="password"
                    autoComplete="new-password"
                    className={hrInputClass}
                    type="password"
                    required
                  />
                </label>
              )}
              {request.request_type === 'link_existing' && (
                <label className="block">
                  Verified portal user ID <input name="user_id" className={hrInputClass} required />
                </label>
              )}
              <button className={hrButtonClass} type="submit" disabled={pending}>
                Fulfill access request
              </button>
            </form>
          )}
        </article>
      ))}
    </div>
  );
}
