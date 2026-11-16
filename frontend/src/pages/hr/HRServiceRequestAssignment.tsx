import { useState } from 'react';

import {
  assignServiceRequest,
  type HrSchemas,
  type HrServiceRequestRecord
} from '../../api/hr';

export function HRServiceRequestAssignment({
  request,
  assignees,
  pending,
  onChange
}: {
  request: HrServiceRequestRecord;
  assignees: HrSchemas['HrServiceRequestAssignee'][];
  pending: boolean;
  onChange: (action: () => Promise<unknown>, fallback: string) => Promise<void>;
}) {
  const [assignee, setAssignee] = useState('');
  const [reason, setReason] = useState('');
  const options = assignees.filter((user) => user.id !== request.assigned_to_id);

  if (!options.length) return null;

  return (
    <details className="space-y-2">
      <summary>{request.assigned_to_id ? 'Reassign request' : 'Assign request'}</summary>
      <form
        className="space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          void onChange(async () => {
            await assignServiceRequest(request.id, {
              assigned_to_id: assignee,
              expected_updated_at: request.updated_at,
              reason: reason.trim()
            });
            setAssignee('');
            setReason('');
          }, 'Unable to hand off this HR request.');
        }}
      >
        <label className="block">
          Assign to
          <select className="ml-2 rounded border border-theme-border bg-theme-input"
            value={assignee} onChange={(event) => setAssignee(event.target.value)} required
            disabled={pending}>
            <option value="">Select an HR user</option>
            {options.map((user) => <option key={user.id} value={user.id}>{user.full_name}</option>)}
          </select>
        </label>
        <label className="block">
          Handoff reason
          <input className="ml-2 rounded border border-theme-border bg-theme-input p-1"
            value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500}
            disabled={pending} required />
        </label>
        <button className="rounded bg-brand-600 px-2 py-1 text-white" type="submit"
          disabled={pending || !assignee || !reason.trim()}>
          Save assignment
        </button>
      </form>
    </details>
  );
}
