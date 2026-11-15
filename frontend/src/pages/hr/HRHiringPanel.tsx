import { useQuery, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useState } from 'react';

import { formatApiError } from '../../api/errors';
import {
  convertOffer,
  createApplication,
  createCandidate,
  createInterview,
  createOffer,
  createOnboardingCase,
  decideOffer,
  decideRequisition,
  listApplications,
  listCandidates,
  listInterviews,
  listOffers,
  listOnboardingCases,
  updateApplicationStage,
  updateInterview,
  updateOnboardingTask,
  type EmployeeDirectoryRecord,
  type RequisitionRecord
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';

type HiringRecord = 'candidate' | 'application' | 'interview' | 'offer' | 'onboarding';
type ReqStatus = Parameters<typeof decideRequisition>[1]['status'];
type OfferStatus = Parameters<typeof decideOffer>[1]['status'];
type Stage = Parameters<typeof updateApplicationStage>[1]['stage'];

export function HRHiringPanel({
  requisitions,
  employees,
  canApprove,
  reload
}: {
  requisitions: RequisitionRecord[];
  employees: EmployeeDirectoryRecord[];
  canApprove: boolean;
  reload: () => Promise<void>;
}) {
  const client = useQueryClient();
  const [kind, setKind] = useState<HiringRecord>('candidate');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const hiring = useQuery({
    queryKey: ['hr', 'hiring'],
    queryFn: async () => {
      const [candidates, applications, interviews, offers, onboarding] = await Promise.all([
        listCandidates(),
        listApplications(),
        listInterviews(),
        listOffers(),
        listOnboardingCases()
      ]);
      return { candidates, applications, interviews, offers, onboarding };
    }
  });

  async function change(action: () => Promise<unknown>, refreshWorkspace = false) {
    if (pending) return;
    setPending(true);
    setError('');
    try {
      await action();
      await client.invalidateQueries({ queryKey: ['hr', 'hiring'] });
      if (refreshWorkspace) await reload();
    } catch (failure) {
      setError(formatApiError(failure, 'Could not update recruitment.'));
    } finally {
      setPending(false);
    }
  }

  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const field = (name: string) => String(data.get(name) ?? '');
    void change(async () => {
      if (kind === 'candidate')
        await createCandidate({
          candidate_code: field('code'),
          full_name: field('name'),
          email: field('email') || null
        });
      if (kind === 'application')
        await createApplication({
          candidate_id: field('candidate'),
          requisition_id: field('requisition')
        });
      if (kind === 'interview')
        await createInterview({
          application_id: field('application'),
          scheduled_at: new Date(field('schedule')).toISOString(),
          interview_type: 'technical',
          round_number: Number(field('round'))
        });
      if (kind === 'offer')
        await createOffer({
          application_id: field('application'),
          offer_code: field('code'),
          proposed_title: field('name')
        });
      if (kind === 'onboarding')
        await createOnboardingCase({
          employee_id: field('employee'),
          start_date: field('date')
        });
      form.reset();
    });
  }

  const transitions = {
    draft: 'submitted',
    submitted: 'approved',
    approved: 'open',
    open: 'closed',
    on_hold: 'open'
  } as Record<string, ReqStatus>;
  const offerSteps = {
    draft: 'pending_approval',
    pending_approval: 'approved',
    approved: 'issued',
    issued: 'accepted'
  } as Record<string, OfferStatus>;
  const stageSteps = {
    applied: 'screening',
    screening: 'interview',
    interview: 'evaluation'
  } as Record<string, Stage>;
  const data = hiring.data;
  return (
    <div className="space-y-4 border-t border-theme-border pt-4 text-sm">
      {hiring.isPending && <p role="status">Loading recruitment records…</p>}
      {hiring.isError && (
        <p role="alert">{formatApiError(hiring.error, 'Could not load recruitment.')}</p>
      )}
      {error && (
        <p role="alert" className="text-red-700">
          {error}
        </p>
      )}
      <ul className="space-y-2">
        {requisitions.map((row) => (
          <li className="flex flex-wrap items-center gap-2" key={row.id}>
            <span>
              {row.requisition_code} · {row.title} · {row.status}
            </span>
            {(canApprove || row.status === 'draft') && transitions[row.status] && (
              <button
                className={hrButtonClass}
                disabled={pending}
                type="button"
                onClick={() =>
                  void change(
                    () => decideRequisition(row.id, { status: transitions[row.status] }),
                    true
                  )
                }
              >
                {transitions[row.status] === 'submitted'
                  ? 'Submit requisition'
                  : `Mark ${transitions[row.status]}`}
              </button>
            )}
          </li>
        ))}
      </ul>
      <form className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-3" onSubmit={add}>
        <label>
          New record{' '}
          <select
            className={hrInputClass}
            value={kind}
            onChange={(event) => setKind(event.target.value as HiringRecord)}
          >
            <option value="candidate">Candidate</option>
            <option value="application">Application</option>
            <option value="interview">Interview</option>
            <option value="offer">Offer</option>
            <option value="onboarding">Direct-hire onboarding</option>
          </select>
        </label>
        {(kind === 'candidate' || kind === 'offer') && (
          <>
            <label>
              Reference code <input name="code" className={hrInputClass} required />
            </label>
            <label>
              {kind === 'candidate' ? 'Candidate name' : 'Proposed title'}{' '}
              <input name="name" className={hrInputClass} required />
            </label>
          </>
        )}
        {kind === 'candidate' && (
          <label>
            Email <input name="email" className={hrInputClass} type="email" />
          </label>
        )}
        {kind === 'application' && (
          <>
            <label>
              Candidate{' '}
              <select name="candidate" className={hrInputClass} required defaultValue="">
                <option value="" disabled>
                  Choose candidate
                </option>
                {data?.candidates.items.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.full_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Requisition{' '}
              <select name="requisition" className={hrInputClass} required defaultValue="">
                <option value="" disabled>
                  Choose open requisition
                </option>
                {requisitions
                  .filter((row) => row.status === 'open')
                  .map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.title}
                    </option>
                  ))}
              </select>
            </label>
          </>
        )}
        {(kind === 'interview' || kind === 'offer') && (
          <label>
            Application{' '}
            <select name="application" className={hrInputClass} required defaultValue="">
              <option value="" disabled>
                Choose application
              </option>
              {data?.applications.items
                .filter((row) => kind === 'interview' || row.stage === 'evaluation')
                .map((row) => (
                  <option key={row.id} value={row.id}>
                    {data.candidates.items.find((candidate) => candidate.id === row.candidate_id)
                      ?.full_name ?? row.id}
                  </option>
                ))}
            </select>
          </label>
        )}
        {kind === 'interview' && (
          <>
            <label>
              Interview time{' '}
              <input name="schedule" type="datetime-local" className={hrInputClass} required />
            </label>
            <label>
              Round number{' '}
              <input name="round" type="number" min="1" className={hrInputClass} required />
            </label>
          </>
        )}
        {kind === 'onboarding' && (
          <>
            <label>
              Employee{' '}
              <select name="employee" className={hrInputClass} required defaultValue="">
                <option value="" disabled>
                  Choose employee
                </option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.full_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Start date <input name="date" type="date" className={hrInputClass} required />
            </label>
          </>
        )}
        <div>
          <button className={hrButtonClass} type="submit" disabled={pending}>
            Save recruitment record
          </button>
        </div>
      </form>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="space-y-2">
          <h4 className="font-semibold">Applications and interviews</h4>
          {data?.applications.items.map((row) => (
            <article key={row.id} className="rounded border border-theme-border p-3">
              <p>
                {data.candidates.items.find((candidate) => candidate.id === row.candidate_id)
                  ?.full_name ?? row.id}{' '}
                · {row.stage}
              </p>
              {data.interviews.items
                .filter((interview) => interview.application_id === row.id)
                .map((interview) => (
                  <div className="flex items-center gap-2" key={interview.id}>
                    <span>
                      {interview.scheduled_at
                        ? new Date(interview.scheduled_at).toLocaleString()
                        : 'Unscheduled'}{' '}
                      · {interview.status}
                    </span>
                    {interview.status === 'scheduled' && (
                      <button
                        type="button"
                        disabled={pending}
                        onClick={() =>
                          void change(() => updateInterview(interview.id, { status: 'completed' }))
                        }
                      >
                        Record interview completed
                      </button>
                    )}
                  </div>
                ))}
              {stageSteps[row.stage] && (
                <button
                  className={hrButtonClass}
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    void change(() =>
                      updateApplicationStage(row.id, { stage: stageSteps[row.stage] })
                    )
                  }
                >
                  Mark {stageSteps[row.stage]}
                </button>
              )}
            </article>
          ))}
        </section>
        <section className="space-y-2">
          <h4 className="font-semibold">Offers and onboarding</h4>
          {data?.offers.items.map((row) => (
            <article key={row.id} className="space-y-2 rounded border border-theme-border p-3">
              <p>
                {row.offer_code} · {row.proposed_title} · {row.status}
              </p>
              {offerSteps[row.status] && (row.status !== 'pending_approval' || canApprove) && (
                <button
                  className={hrButtonClass}
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    void change(() => decideOffer(row.id, { status: offerSteps[row.status] }))
                  }
                >
                  Mark {offerSteps[row.status].replace(/_/g, ' ')}
                </button>
              )}
              {row.status === 'accepted' && (
                <form
                  className="space-y-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const form = new FormData(event.currentTarget);
                    void change(() =>
                      convertOffer(row.id, {
                        employee_code: String(form.get('code')),
                        work_email: String(form.get('email') ?? '') || null,
                        work_phone: String(form.get('phone') ?? '') || null,
                        probation_days: Number(form.get('probation') ?? 0)
                      })
                    );
                  }}
                >
                  <label>
                    Employee code <input name="code" className={hrInputClass} required />
                  </label>
                  <label>
                    Verified work email <input name="email" type="email" className={hrInputClass} />
                  </label>
                  <label>
                    Work phone <input name="phone" type="tel" className={hrInputClass} />
                  </label>
                  <label>
                    Probation days{' '}
                    <input
                      name="probation"
                      type="number"
                      min="0"
                      max="365"
                      className={hrInputClass}
                      defaultValue="0"
                    />
                  </label>
                  <button className={hrButtonClass} type="submit" disabled={pending}>
                    Start onboarding from offer
                  </button>
                </form>
              )}
            </article>
          ))}
          {data?.onboarding.items.map((row) => (
            <article key={row.id} className="space-y-2 rounded border border-theme-border p-3">
              <p>
                {employees.find((employee) => employee.id === row.employee_id)?.full_name ??
                  row.employee_id}{' '}
                · {row.status}
              </p>
              {row.tasks?.map((task) => (
                <div key={task.id}>
                  <p>
                    {task.title} · {task.status}
                  </p>
                  {row.status !== 'completed' && !['completed', 'waived'].includes(task.status) && (
                    <form
                      className="flex items-end gap-2"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const evidence = String(new FormData(event.currentTarget).get('evidence'));
                        void change(() =>
                          updateOnboardingTask(task.id, {
                            status: 'completed',
                            evidence_notes: evidence
                          })
                        );
                      }}
                    >
                      <label>
                        Evidence <input required name="evidence" className={hrInputClass} />
                      </label>
                      <button className={hrButtonClass} type="submit" disabled={pending}>
                        Complete task
                      </button>
                    </form>
                  )}
                </div>
              ))}
            </article>
          ))}
        </section>
      </div>
    </div>
  );
}
