import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { apiClient } from '../../api/client';
import { formatApiError } from '../../api/errors';
import { listEmployees, listHrDocuments, uploadHrDocument, type HrSchemas } from '../../api/hr';
import { hrButtonClass, hrInputClass } from './HRAccessForms';
import { TrainingRequirements, TrainingRuleEditor } from './HRTrainingRequirements';

const prefix = '/hr/training';
const sectionClass = 'space-y-3 rounded border border-theme-border bg-theme-card p-4';

export function HRTraining({ canManageDocuments }: { canManageDocuments: boolean }) {
  const [search, setSearch] = useState('');
  const [employeeId, setEmployeeId] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [receipt, setReceipt] = useState<HrSchemas['TrainingCompletionResponse'] | null>(null);
  const queryClient = useQueryClient();
  const courses = useQuery({
    queryKey: ['hr', 'training', 'courses'],
    queryFn: async () =>
      (await apiClient.get<HrSchemas['TrainingCourseListResponse']>(`${prefix}/courses`)).data
  });
  const employees = useQuery({
    queryKey: ['hr', 'training', 'employees', search],
    queryFn: () => listEmployees({ search: search.trim(), limit: 20 }),
    enabled: search.trim().length >= 2
  });
  const enrollments = useQuery({
    queryKey: ['hr', 'training', 'enrollments', employeeId],
    queryFn: async () =>
      (
        await apiClient.get<HrSchemas['TrainingEnrollmentListResponse']>(`${prefix}/enrollments`, {
          params: { employee_id: employeeId }
        })
      ).data,
    enabled: Boolean(employeeId)
  });
  const certificates = useQuery({
    queryKey: ['hr', 'training', 'certificates', employeeId],
    queryFn: async () =>
      (
        await apiClient.get<HrSchemas['CertificationListResponse']>('/hr/certifications', {
          params: { employee_id: employeeId }
        })
      ).data,
    enabled: Boolean(employeeId)
  });
  const documents = useQuery({
    queryKey: ['hr', 'training', 'evidence', employeeId],
    queryFn: () =>
      listHrDocuments({ employee_id: employeeId, document_type: 'training_certificate' }),
    enabled: canManageDocuments && Boolean(employeeId)
  });
  const approved =
    documents.data?.items.filter((doc) => doc.status === 'active' && doc.current_version > 0) ?? [];

  async function submit(
    event: FormEvent<HTMLFormElement>,
    action: (data: FormData) => Promise<unknown>
  ) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await run(async () => {
      await action(data);
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ['hr', 'training'] });
    });
  }

  async function run(action: () => Promise<void>) {
    if (pending) return;
    setPending(true);
    setError('');
    try {
      await action();
    } catch (failure) {
      setError(formatApiError(failure, 'Could not update training.'));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-4">
      <h3 className="font-semibold">Training and certification</h3>
      {error && <p role="alert">{error}</p>}
      <section className={sectionClass}>
        <h4 className="font-semibold">Course catalogue</h4>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) =>
            void submit(event, (data) =>
              apiClient.post(`${prefix}/courses`, {
                code: String(data.get('code')).trim(),
                title: String(data.get('title')).trim(),
                is_mandatory: data.get('mandatory') === 'on'
              })
            )
          }
        >
          <label>
            Course code <input className={hrInputClass} name="code" maxLength={40} required />
          </label>
          <label>
            Course title <input className={hrInputClass} name="title" maxLength={200} required />
          </label>
          <label>
            <input name="mandatory" type="checkbox" /> Mandatory course
          </label>
          <button className={hrButtonClass} disabled={pending} type="submit">
            Create course
          </button>
        </form>
        {courses.isPending && <p role="status">Loading training courses…</p>}
        {courses.isError && (
          <p role="alert">{formatApiError(courses.error, 'Could not load courses.')}</p>
        )}
        {courses.data?.items.length === 0 && <p>No training courses.</p>}
        <ul>
          {courses.data?.items.map((course) => (
            <li key={course.id}>
              {course.code} · {course.title}
              {course.is_mandatory && ' · Mandatory'}
            </li>
          ))}
        </ul>
      </section>
      <TrainingRuleEditor courses={courses.data?.items ?? []} />
      <section className={sectionClass}>
        <h4 className="font-semibold">Employee training</h4>
        <label className="block">
          Search training employee
          <input
            className={hrInputClass}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label className="block">
          Training employee
          <select
            className={hrInputClass}
            value={employeeId}
            onChange={(event) => {
              setEmployeeId(event.target.value);
              setReceipt(null);
            }}
          >
            <option value="">Select employee</option>
            {employees.data?.items.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employee.full_name} · {employee.employee_code}
              </option>
            ))}
          </select>
        </label>
        {employees.isError && (
          <p role="alert">{formatApiError(employees.error, 'Could not search employees.')}</p>
        )}
        {employees.isFetching && <p role="status">Searching employees…</p>}
        {employees.data?.items.length === 0 && <p>No employees match the search.</p>}
        {employeeId && (
          <>
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(event) =>
                void submit(event, (data) =>
                  apiClient.post(`${prefix}/enrollments`, {
                    employee_id: employeeId,
                    course_id: data.get('course'),
                    scheduled_date: data.get('scheduled') || null
                  })
                )
              }
            >
              <label>
                Enrollment course{' '}
                <select className={hrInputClass} name="course" required defaultValue="">
                  <option value="">Select course</option>
                  {courses.data?.items
                    .filter((course) => course.is_active)
                    .map((course) => (
                      <option key={course.id} value={course.id}>
                        {course.title}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Scheduled training date{' '}
                <input className={hrInputClass} type="date" name="scheduled" />
              </label>
              <button className={hrButtonClass} type="submit" disabled={pending}>
                Enroll employee
              </button>
            </form>
            {canManageDocuments && (
              <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(event) =>
                  void submit(event, (data) =>
                    uploadHrDocument({
                      file: data.get('certificate') as File,
                      title: String(data.get('title')),
                      issue_date: String(data.get('issued')),
                      expiry_date: String(data.get('expiry') || ''),
                      document_type: 'training_certificate',
                      category: 'ordinary',
                      employee_id: employeeId
                    })
                  )
                }
              >
                <label>
                  Certificate title{' '}
                  <input className={hrInputClass} name="title" maxLength={255} required />
                </label>
                <label>
                  Certificate issue date{' '}
                  <input className={hrInputClass} type="date" name="issued" required />
                </label>
                <label>
                  Certificate expiry <input className={hrInputClass} type="date" name="expiry" />
                </label>
                <label>
                  Certificate PDF{' '}
                  <input
                    className={hrInputClass}
                    type="file"
                    name="certificate"
                    accept="application/pdf"
                    required
                  />
                </label>
                <button className={hrButtonClass} type="submit" disabled={pending}>
                  Upload training certificate
                </button>
                <p>Review uploaded versions in Docs &amp; Compliance.</p>
              </form>
            )}
            {enrollments.isPending && <p role="status">Loading enrollments…</p>}
            {enrollments.isError && (
              <p role="alert">{formatApiError(enrollments.error, 'Could not load enrollments.')}</p>
            )}
            {documents.isError && (
              <p role="alert">
                {formatApiError(documents.error, 'Could not load certificate evidence.')}
              </p>
            )}
            {enrollments.data?.items.length === 0 && <p>No enrollments for this employee.</p>}
            {enrollments.data?.items.map((row) => (
              <article className={sectionClass} key={row.id}>
                <h5 className="font-semibold">
                  {courses.data?.items.find((course) => course.id === row.course_id)?.title ??
                    'Training enrollment'}
                </h5>
                <p>
                  Enrollment {row.status.replace(/_/g, ' ')}
                  {row.completed_date && ` · ${row.completed_date}`}
                </p>
                {row.status === 'completed' && (
                  <button
                    className={hrButtonClass}
                    disabled={pending}
                    type="button"
                    onClick={() =>
                      void run(async () =>
                        setReceipt(
                          (
                            await apiClient.get<HrSchemas['TrainingCompletionResponse']>(
                              `${prefix}/enrollments/${row.id}/completion`
                            )
                          ).data
                        )
                      )
                    }
                  >
                    Show verified receipt
                  </button>
                )}
                {receipt && receipt.enrollment_id === row.id && (
                  <p>
                    Verified certificate version {receipt.version_number} · {receipt.completed_date}
                  </p>
                )}
                {['enrolled', 'in_progress'].includes(row.status) && (
                  <form
                    className="flex flex-wrap items-end gap-2"
                    onSubmit={(event) =>
                      void submit(event, async (data) => {
                        const document = approved.find(
                          (item) => item.id === data.get('certificate')
                        );
                        if (!document) return;
                        const result = await apiClient.post<
                          HrSchemas['TrainingCompletionResponse']
                        >(`${prefix}/enrollments/${row.id}/completion`, {
                          document_id: document.id,
                          version_number: document.current_version,
                          completed_date: data.get('completed'),
                          score: data.get('score') || null
                        });
                        setReceipt(result.data);
                      })
                    }
                  >
                    <label>
                      Approved training certificate{' '}
                      <select className={hrInputClass} name="certificate" required defaultValue="">
                        <option value="">Select evidence</option>
                        {approved.map((doc) => (
                          <option key={doc.id} value={doc.id}>
                            {doc.title} · Version {doc.current_version}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Training completion date{' '}
                      <input name="completed" type="date" className={hrInputClass} required />
                    </label>
                    <label>
                      Training score{' '}
                      <input
                        name="score"
                        type="number"
                        min={0}
                        max={100}
                        step="0.01"
                        className={hrInputClass}
                      />
                    </label>
                    <button
                      className={hrButtonClass}
                      type="submit"
                      disabled={pending || !approved.length}
                    >
                      Verify completion
                    </button>
                  </form>
                )}
              </article>
            ))}
            <TrainingRequirements key={employeeId} employeeId={employeeId} />
            <h5 className="font-semibold">Credentials</h5>
            {certificates.isError && (
              <p role="alert">
                {formatApiError(certificates.error, 'Could not load credentials.')}
              </p>
            )}
            {certificates.isPending && <p role="status">Loading credentials…</p>}
            <ul>
              {certificates.data?.items.map((certificate) => (
                <li key={certificate.id}>
                  {certificate.name} · {certificate.effective_status}
                  {certificate.expiry_date && ` · ${certificate.expiry_date}`}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
