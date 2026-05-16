import { Archive, FileWarning, LockKeyhole, ShieldCheck, Timer, UserCheck } from 'lucide-react';

import { StatusBadge } from '../../components/shared/StatusBadge';

const controls = [
  {
    label: '2FA',
    detail: 'Email OTP challenge before token issuance.',
    icon: UserCheck,
    status: 'implemented'
  },
  {
    label: 'Session',
    detail: 'Short access tokens with HttpOnly refresh-cookie rotation.',
    icon: LockKeyhole,
    status: 'implemented'
  },
  {
    label: 'Lockout',
    detail: 'Failed-login lockout and auth endpoint rate limiting.',
    icon: Timer,
    status: 'implemented'
  },
  {
    label: 'Blocked files',
    detail: 'Executable/script file extensions and unknown binaries are rejected.',
    icon: FileWarning,
    status: 'implemented'
  },
  {
    label: 'Audit',
    detail:
      'Create, update, login, download, approve, reject, and override paths record audit events.',
    icon: ShieldCheck,
    status: 'partial'
  },
  {
    label: 'Retention',
    detail:
      'Notification cleanup and soft delete paths exist; audit 7-year lifecycle still needs production policy enforcement.',
    icon: Archive,
    status: 'partial'
  }
];

const complianceRows = [
  'Downloads are logged for protected documents, photos, supplier TDS files, and invoice attachments',
  'Private files use short-lived signed URLs',
  'Backups support encryption and are scheduled daily/monthly through Celery beat',
  'Monthly restore testing remains an operations sign-off item',
  'Reports, documents, and photos remain linked to active/completed project records'
];

export function SecurityPage() {
  return (
    <section className="space-y-6">
      <div>
        <p className="text-sm font-medium text-brand-600">Governance</p>
        <h2 className="text-2xl font-semibold text-theme-text-primary">Security And Audit</h2>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {controls.map((control) => {
          const Icon = control.icon;
          return (
            <article
              className="rounded-lg border border-theme-border bg-theme-card p-4"
              key={control.label}
            >
              <div className="flex items-start justify-between gap-3">
                <Icon className="h-5 w-5 text-brand-600" />
                <StatusBadge tone={control.status === 'implemented' ? 'success' : 'warning'}>
                  {control.status}
                </StatusBadge>
              </div>
              <h3 className="mt-3 text-base font-semibold text-theme-text-primary">
                {control.label}
              </h3>
              <p className="mt-1 text-sm text-theme-text-secondary">{control.detail}</p>
            </article>
          );
        })}
      </div>

      <div className="rounded-lg border border-theme-border bg-theme-card p-4">
        <h3 className="text-base font-semibold text-theme-text-primary">Compliance posture</h3>
        <ul className="mt-3 grid gap-3 text-sm text-theme-text-secondary md:grid-cols-2">
          {complianceRows.map((row) => (
            <li className="flex gap-2" key={row}>
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
              <span>{row}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
