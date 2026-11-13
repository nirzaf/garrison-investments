import { Archive, BookOpenCheck, Cloud, Database, Route, Smartphone, Truck } from 'lucide-react';

import { StatusBadge } from '../../components/shared/StatusBadge';

const deliveryItems = [
  {
    label: 'Hosting',
    detail: 'The production deployment uses Docker Compose on the VPS.',
    icon: Cloud,
    status: 'configured'
  },
  {
    label: 'Environments',
    detail: 'Use isolated test environments for acceptance checks that need test data or fault injection.',
    icon: Route,
    status: 'external proof'
  },
  {
    label: 'Deployment',
    detail:
      'GitHub Actions has a production workflow for verified main commits. Check the release record for execution and approval evidence.',
    icon: Truck,
    status: 'configured'
  },
  {
    label: 'Backups',
    detail: 'Scheduled database backups are configured. Independent recovery also needs the referenced files and an executed restore drill.',
    icon: Database,
    status: 'configured'
  },
  {
    label: 'Testing',
    detail: 'Desktop Chrome and Edge, including degraded-network checks.',
    icon: BookOpenCheck,
    status: 'pending QA'
  },
  {
    label: 'Migration',
    detail: 'CSV imports for users, projects, suppliers, inventory, BOQ, and opening stock.',
    icon: Archive,
    status: 'partial'
  }
];

const acceptanceScenarios = [
  'Login, OTP, and password reset',
  'User creation and deactivation',
  'Project creation with BOQ baseline',
  'Supervisor site update with photos',
  'Engineer daily report submission',
  'Approval and rejection with reason',
  'Document version upload and approval',
  'Notification and report export',
  'Inventory receive, request, reserve, issue, transfer, and return',
  'Offline drafts and queued photo uploads'
];

const remainingInputs = [
  'Formal acceptance from the business sponsor, finance/data owner, QA lead, and operations owner',
  'Independent backup and monitoring destinations and named operators',
  'Company-approved report, export, BOQ, and numbering templates',
  'Source spreadsheets for launch users, projects, suppliers, inventory, BOQ, and opening stock',
  'QA sign-off for desktop Chrome and Edge'
];

export function DeliveryPlanPage() {
  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-theme-text-primary">Launch readiness</h2>
        <p className="mt-1 text-sm text-theme-text-secondary">
          Use the{' '}
          <a
            className="text-brand-600 underline"
            href="https://github.com/nirzaf/garrison-investments/blob/main/docs/OPERATIONS_AND_DEPLOYMENT.md"
          >
            operations guide
          </a>{' '}
          to record release checks and sign-off.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {deliveryItems.map((item) => {
          const Icon = item.icon;
          return (
            <article
              className="rounded-lg border border-theme-border bg-theme-card p-4"
              key={item.label}
            >
              <Icon className="h-5 w-5 text-brand-600" />
              <div className="mt-3 flex items-center justify-between gap-3">
                <h3 className="text-base font-semibold text-theme-text-primary">{item.label}</h3>
                <StatusBadge tone={item.status === 'configured' ? 'success' : 'warning'}>
                  {item.status}
                </StatusBadge>
              </div>
              <p className="mt-1 text-sm text-theme-text-secondary">{item.detail}</p>
            </article>
          );
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Checklist title="Launch acceptance scenarios" rows={acceptanceScenarios} />
        <Checklist title="Remaining external inputs" rows={remainingInputs} warning />
      </div>

      <div className="rounded-lg border border-theme-border bg-theme-card p-4">
        <div className="flex items-center gap-2">
          <Smartphone className="h-5 w-5 text-brand-600" />
          <h3 className="text-base font-semibold text-theme-text-primary">
            Offline and file acceptance scenarios
          </h3>
        </div>
        <div className="mt-3 grid gap-3 text-sm text-theme-text-secondary md:grid-cols-4">
          <span>30-second draft autosave</span>
          <span>Photo file selection</span>
          <span>Queued photo upload</span>
          <span>Active document viewing</span>
        </div>
      </div>
    </section>
  );
}

function Checklist({ title, rows, warning }: { title: string; rows: string[]; warning?: boolean }) {
  return (
    <article className="rounded-lg border border-theme-border bg-theme-card p-4">
      <h3 className="text-base font-semibold text-theme-text-primary">{title}</h3>
      <ul className="mt-3 space-y-3 text-sm text-theme-text-secondary">
        {rows.map((row) => (
          <li className="flex gap-2" key={row}>
            <span
              className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                warning ? 'bg-[var(--status-warning-text)]' : 'bg-brand-600'
              }`}
            />
            <span>{row}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}
