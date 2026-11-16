import { useQuery, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useRef, useState } from 'react';

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
  getOfferDocumentDownload,
  listApplications,
  listCandidates,
  listInterviewerOptions,
  listInterviews,
  listOffers,
  listOnboardingCases,
  recordProbationReview,
  reissueOffer,
  transitionEmployeeStatus,
  updateApplicationStage,
  updateInterview,
  updateOnboardingTask,
  type EmployeeDirectoryRecord,
  type RequisitionRecord
} from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';
import { HRApplicationWithdrawal } from './HRApplicationWithdrawal';
import { HRApplicationRejection } from './HRApplicationRejection';
import { HRApplicationHistory } from './HRApplicationHistory';
import { HRCandidateCVs } from './HRCandidateCVs';
import { HROfferDocumentPicker } from './HROfferDocumentPicker';
import { HRProbationReview } from './HRProbationReview';

type HiringRecord = 'candidate' | 'application' | 'interview' | 'offer' | 'onboarding';
type ReqStatus = Parameters<typeof decideRequisition>[1]['status'];
type OfferStatus = Parameters<typeof decideOffer>[1]['status'];
type Stage = Parameters<typeof updateApplicationStage>[1]['stage'];
const applicationPageSize = 25;
const applicationStages = [
  'applied',
  'screening',
  'shortlisted',
  'interview',
  'evaluation',
  'offer',
  'hired',
  'rejected',
  'withdrawn'
] as const satisfies readonly Stage[];

export function HRHiringPanel({
  requisitions,
  employees,
  canApprove,
  canManageCVs,
  reviewerId,
  reload
}: {
  requisitions: RequisitionRecord[];
  employees: EmployeeDirectoryRecord[];
  canApprove: boolean;
  canManageCVs: boolean;
  reviewerId: string | undefined;
  reload: () => Promise<void>;
}) {
  const client = useQueryClient();
  const [kind, setKind] = useState<HiringRecord>('candidate');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [applicationSearch, setApplicationSearch] = useState('');
  const [applicationStage, setApplicationStage] = useState<Stage | ''>('');
  const [applicationFilters, setApplicationFilters] = useState({
    search: '',
    stage: '' as Stage | ''
  });
  const [applicationOffset, setApplicationOffset] = useState(0);
  const [interviewerSearch, setInterviewerSearch] = useState('');
  const [interviewerId, setInterviewerId] = useState('');
  const [draftApplicationId, setDraftApplicationId] = useState('');
  const interviewAttempt = useRef<{ schedule: string; id: string } | null>(null);
  const interviewers = useQuery({
    queryKey: ['hr', 'hiring', 'interviewers', interviewerSearch.trim()],
    queryFn: () => listInterviewerOptions(interviewerSearch.trim()),
    enabled: kind === 'interview' && interviewerSearch.trim().length >= 2
  });
  const applications = useQuery({
    queryKey: ['hr', 'hiring', 'applications', applicationFilters, applicationOffset],
    queryFn: () =>
      listApplications({
        search: applicationFilters.search || undefined,
        stage: applicationFilters.stage || undefined,
        offset: applicationOffset,
        limit: applicationPageSize
      })
  });
  const hiring = useQuery({
    queryKey: ['hr', 'hiring'],
    queryFn: async () => {
      const [candidates, interviews, offers, onboarding] = await Promise.all([
        listCandidates(),
        listInterviews(),
        listOffers(),
        listOnboardingCases()
      ]);
      return { candidates, interviews, offers, onboarding };
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
      if (kind === 'interview') {
        const schedule = {
          application_id: field('application'),
          scheduled_at: new Date(field('schedule')).toISOString(),
          interview_type: 'technical',
          round_number: Number(field('round')),
          interviewer_user_id: interviewerId || null
        };
        const key = JSON.stringify(schedule);
        if (interviewAttempt.current?.schedule !== key) {
          interviewAttempt.current = { schedule: key, id: crypto.randomUUID() };
        }
        await createInterview({ ...schedule, interview_id: interviewAttempt.current.id });
        interviewAttempt.current = null;
      }
      if (kind === 'offer')
        await createOffer({
          application_id: field('application'),
          offer_code: field('code'),
          proposed_title: field('name'),
          valid_until: field('valid_until') || null,
          document_version_id: field('document_version_id') || null
        });
      if (kind === 'onboarding')
        await createOnboardingCase({
          employee_id: field('employee'),
          start_date: field('date'),
          probation_end_date: field('probation_end_date') || null
        });
      form.reset();
      setDraftApplicationId('');
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
    screening: 'shortlisted',
    shortlisted: 'interview',
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
      {canManageCVs && (
        <>
          <HRCandidateCVs candidates={data?.candidates.items ?? []} reviewerId={reviewerId} />
          <HRCandidateCVs
            candidates={data?.candidates.items ?? []}
            reviewerId={reviewerId}
            offerFiles
          />
        </>
      )}
      <ul className="space-y-2">
        {requisitions.map((row) => (
          <li className="flex flex-wrap items-center gap-2" key={row.id}>
            <span>
              {row.requisition_code} · {row.title} · Headcount {row.headcount_requested} ·{' '}
              {row.status}
              {row.rejection_reason ? ` · Rejected: ${row.rejection_reason}` : ''}
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
            {canApprove && row.status === 'submitted' && (
              <form
                className="flex flex-wrap items-center gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const form = event.currentTarget;
                  const reason = String(new FormData(form).get('reason') ?? '').trim();
                  void change(async () => {
                    await decideRequisition(row.id, { status: 'rejected', notes: reason });
                    form.reset();
                  }, true);
                }}
              >
                <label>
                  Requisition rejection reason{' '}
                  <input name="reason" className={hrInputClass} required maxLength={500} />
                </label>
                <button className={hrButtonClass} disabled={pending} type="submit">
                  Reject requisition
                </button>
              </form>
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
            onChange={(event) => {
              setDraftApplicationId('');
              setKind(event.target.value as HiringRecord);
            }}
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
        {kind === 'offer' && (
          <label>
            Valid until <input name="valid_until" className={hrInputClass} type="date" />
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
            <select
              name="application"
              className={hrInputClass}
              required
              value={draftApplicationId}
              onChange={(event) => setDraftApplicationId(event.target.value)}
            >
              <option value="" disabled>
                Choose application
              </option>
              {applications.data?.items
                .filter((row) =>
                  kind === 'interview'
                    ? ['shortlisted', 'interview', 'evaluation'].includes(row.stage)
                    : row.stage === 'evaluation'
                )
                .map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.candidate_name} · {row.position_title}
                  </option>
                ))}
            </select>
          </label>
        )}
        {kind === 'offer' && canManageCVs && draftApplicationId && (
          <HROfferDocumentPicker key={draftApplicationId} applicationId={draftApplicationId} />
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
            <label>
              Find portal interviewer{' '}
              <input
                type="search"
                maxLength={120}
                placeholder="Name or exact employee code"
                value={interviewerSearch}
                onChange={(event) => {
                  setInterviewerSearch(event.target.value);
                  setInterviewerId('');
                }}
                className={hrInputClass}
              />
            </label>
            <label>
              Portal interviewer{' '}
              <select
                value={interviewerId}
                onChange={(event) => setInterviewerId(event.target.value)}
                className={hrInputClass}
              >
                <option value="">No invitation</option>
                {interviewers.data?.items.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.full_name}
                    {person.employee_code && ` · ${person.employee_code}`}
                  </option>
                ))}
              </select>
            </label>
            {interviewerSearch.trim().length >= 2 && interviewers.isFetching && (
              <p role="status">Finding interviewers…</p>
            )}
            {interviewers.isError && (
              <p role="alert">Could not find interviewers. Try another search.</p>
            )}
            {interviewers.data?.total === 0 && <p role="status">No matching portal accounts.</p>}
            {(interviewers.data?.total ?? 0) > 20 && (
              <p>Refine the name or enter the exact employee code.</p>
            )}
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
            <label>
              Probation end date
              <input name="probation_end_date" type="date" className={hrInputClass} />
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
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              setApplicationOffset(0);
              setApplicationFilters({ search: applicationSearch.trim(), stage: applicationStage });
            }}
          >
            <label>
              Find candidate applications
              <input
                type="search"
                maxLength={120}
                value={applicationSearch}
                className={hrInputClass}
                onChange={(event) => setApplicationSearch(event.target.value)}
              />
            </label>
            <label>
              Application stage
              <select
                className={hrInputClass}
                value={applicationStage}
                onChange={(event) => setApplicationStage(event.target.value as Stage | '')}
              >
                <option value="">All stages</option>
                {applicationStages.map((stage) => (
                  <option key={stage} value={stage}>
                    {stage}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className={hrButtonClass}>
              Find applications
            </button>
          </form>
          {applications.isPending && <p role="status">Loading applications…</p>}
          {applications.isError && (
            <p role="alert">{formatApiError(applications.error, 'Could not load applications.')}</p>
          )}
          {applications.isSuccess && applications.data.items.length === 0 && (
            <p>No applications match.</p>
          )}
          {applications.data?.items.map((row) => (
            <article key={row.id} className="rounded border border-theme-border p-3">
              <p>
                {row.candidate_name} · {row.candidate_code} · {row.stage}
              </p>
              <p>{row.position_title}</p>
              {data?.interviews.items
                .filter((interview) => interview.application_id === row.id)
                .map((interview) => (
                  <div className="flex items-center gap-2" key={interview.id}>
                    <span>
                      {interview.scheduled_at
                        ? new Date(interview.scheduled_at).toLocaleString()
                        : 'Unscheduled'}{' '}
                      · {interview.status}
                    </span>
                    {interview.status === 'scheduled' &&
                      !['withdrawn', 'rejected'].includes(row.stage) && (
                        <button
                          type="button"
                          disabled={pending}
                          onClick={() =>
                            void change(() =>
                              updateInterview(interview.id, { status: 'completed' })
                            )
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
                  {row.stage === 'screening'
                    ? 'Shortlist application'
                    : row.stage === 'shortlisted'
                      ? 'Start interview stage'
                      : `Mark ${stageSteps[row.stage]}`}
                </button>
              )}
              <HRApplicationWithdrawal application={row} pending={pending} change={change} />
              <HRApplicationRejection application={row} pending={pending} change={change} />
              <HRApplicationHistory applicationId={row.id} />
            </article>
          ))}
          {(applicationOffset > 0 ||
            applicationOffset + applicationPageSize < (applications.data?.total ?? 0)) && (
            <div className="flex gap-2">
              <button
                type="button"
                className={hrButtonClass}
                disabled={!applicationOffset || applications.isFetching}
                onClick={() => setApplicationOffset(applicationOffset - applicationPageSize)}
              >
                Previous applications
              </button>
              <button
                type="button"
                className={hrButtonClass}
                disabled={
                  applications.isFetching ||
                  applicationOffset + applicationPageSize >= (applications.data?.total ?? 0)
                }
                onClick={() => setApplicationOffset(applicationOffset + applicationPageSize)}
              >
                Next applications
              </button>
            </div>
          )}
        </section>
        <section className="space-y-2">
          <h4 className="font-semibold">Offers and onboarding</h4>
          {data?.offers.items.map((row) => (
            <article key={row.id} className="space-y-2 rounded border border-theme-border p-3">
              <p>
                {row.offer_code} · {row.proposed_title} · v{row.version_number} · {row.status}
                {row.valid_until ? ` · Valid until ${row.valid_until}` : ''}
              </p>
              <div className="flex flex-wrap gap-2">
                {canManageCVs && row.document_version_id && (
                  <button
                    className={hrButtonClass}
                    type="button"
                    disabled={pending}
                    onClick={() =>
                      void change(async () => {
                        const result = await getOfferDocumentDownload(row.id);
                        window.location.assign(result.download_url);
                      })
                    }
                  >
                    Download offer file
                  </button>
                )}
                {offerSteps[row.status] && (row.status !== 'pending_approval' || canApprove) && (
                  <button
                    className={hrButtonClass}
                    type="button"
                    disabled={pending}
                    onClick={() =>
                      void change(() =>
                        decideOffer(row.id, {
                          status: offerSteps[row.status],
                          expected_version_number: row.version_number
                        })
                      )
                    }
                  >
                    Mark {offerSteps[row.status].replace(/_/g, ' ')}
                  </button>
                )}
                {row.status === 'issued' && row.valid_until && (
                  <button
                    className={hrButtonClass}
                    type="button"
                    disabled={pending}
                    onClick={() =>
                      void change(() =>
                        decideOffer(row.id, {
                          status: 'expired',
                          expected_version_number: row.version_number
                        })
                      )
                    }
                  >
                    Mark expired
                  </button>
                )}
              </div>
              {!['converted', 'superseded', 'withdrawn'].includes(row.status) && (
                <form
                  className="flex flex-wrap items-end gap-2 border-t border-theme-border pt-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const form = event.currentTarget;
                    const formData = new FormData(form);
                    void change(async () => {
                      await reissueOffer(row.id, {
                        offer_code: String(formData.get('offer_code') ?? '').trim(),
                        proposed_title: String(formData.get('proposed_title') ?? '').trim(),
                        valid_until: String(formData.get('valid_until') ?? '') || null,
                        document_version_id:
                          String(formData.get('document_version_id') ?? '') || null,
                        expected_updated_at: row.updated_at
                      });
                      form.reset();
                    });
                  }}
                >
                  <label>
                    Offer code{' '}
                    <input
                      name="offer_code"
                      className={hrInputClass}
                      placeholder={`${row.offer_code}-V${row.version_number + 1}`}
                      required
                    />
                  </label>
                  <label>
                    Proposed title{' '}
                    <input
                      name="proposed_title"
                      className={hrInputClass}
                      defaultValue={row.proposed_title}
                      required
                    />
                  </label>
                  <label>
                    Valid until{' '}
                    <input
                      name="valid_until"
                      type="date"
                      className={hrInputClass}
                      defaultValue={row.valid_until ?? ''}
                    />
                  </label>
                  {canManageCVs && (
                    <HROfferDocumentPicker
                      applicationId={row.application_id}
                      priorVersion={row.document_version_id}
                      loadOnMount={false}
                    />
                  )}
                  <button className={hrButtonClass} type="submit" disabled={pending}>
                    Reissue offer
                  </button>
                </form>
              )}
              {row.status === 'accepted' && (
                <form
                  className="space-y-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const form = new FormData(event.currentTarget);
                    void change(
                      () =>
                        convertOffer(row.id, {
                          employee_code: String(form.get('code')),
                          work_email: String(form.get('email') ?? '') || null,
                          work_phone: String(form.get('phone') ?? '') || null,
                          probation_days: Number(form.get('probation') ?? 0)
                        }),
                      true
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
                {row.employee_name ??
                  employees.find((employee) => employee.id === row.employee_id)?.full_name ??
                  row.employee_id}{' '}
                · {row.status}
              </p>
              {row.probation_end_date && <p>Probation end date {row.probation_end_date}</p>}
              {row.probation_end_date && row.employee_status === 'active' && (
                <p>Employment active</p>
              )}
              {row.status === 'completed' && canApprove && row.employee_revision != null && (
                <>
                  {row.employee_status === 'onboarding' && (
                    <button
                      type="button"
                      className={hrButtonClass}
                      disabled={pending}
                      onClick={() => {
                        const revision = row.employee_revision;
                        if (revision == null) return;
                        void change(
                          () =>
                            transitionEmployeeStatus(row.employee_id, {
                              status: 'on_probation',
                              expected_revision: revision,
                              reason:
                                'Completed onboarding and started the documented probation period.'
                            }),
                          true
                        );
                      }}
                    >
                      Start probation
                    </button>
                  )}
                  {row.employee_status === 'on_probation' && (
                    <HRProbationReview
                      key={row.employee_revision}
                      category={row.employee_category}
                      pending={pending}
                      onReview={(decision) => {
                        if (row.employee_revision == null) return;
                        const revision = row.employee_revision;
                        void change(
                          () =>
                            recordProbationReview(row.id, {
                              ...decision,
                              expected_employee_revision: revision
                            }),
                          true
                        );
                      }}
                    />
                  )}
                </>
              )}
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
