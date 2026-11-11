import {
  AlertTriangle,
  BookOpen,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Info,
  Lightbulb,
  Lock,
  Unlock,
  User
} from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { useAuth } from '../../context/useAuth';
import {
  COMMON_SECTIONS,
  accountsManual,
  adminManual,
  civilEngineerManual,
  civilSupervisorManual,
  generalManagerManual,
  operationManagerManual,
  projectManagerManual,
  storeKeeperManual
} from './manuals';
import type { Manual, ManualSection } from './manuals';

const MANUALS: Record<string, Manual> = {
  admin: adminManual,
  general_manager: generalManagerManual,
  operation_manager: operationManagerManual,
  project_manager: projectManagerManual,
  civil_engineer: civilEngineerManual,
  civil_supervisor: civilSupervisorManual,
  store_keeper: storeKeeperManual,
  accounts: accountsManual
};

function Diagram({ text }: { text: string }) {
  return (
    <pre className="overflow-x-auto rounded-lg border border-theme-border bg-theme-card-elevated p-4 font-mono text-xs leading-relaxed text-theme-text-secondary whitespace-pre">
      {text.trim()}
    </pre>
  );
}

function StepList({ steps }: { steps: NonNullable<ManualSection['steps']> }) {
  return (
    <ol className="space-y-3">
      {steps.map((s) => (
        <li className="flex gap-3" key={s.step}>
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white">
            {s.step}
          </span>
          <div className="min-w-0 pt-0.5">
            <span className="font-semibold text-theme-text-primary">{s.action}</span>
            {s.detail && <p className="mt-0.5 text-sm text-theme-text-secondary">{s.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function TipList({ tips }: { tips: string[] }) {
  return (
    <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <div className="flex items-center gap-1.5 text-amber-700">
        <Lightbulb className="h-4 w-4 shrink-0" />
        <span className="text-xs font-semibold uppercase tracking-wide">Tips</span>
      </div>
      <ul className="space-y-1.5 text-sm text-amber-800">
        {tips.map((tip, i) => (
          <li className="flex gap-2" key={i}>
            <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
            {tip}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SectionCard({ section }: { section: ManualSection }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="rounded-xl border border-theme-border bg-theme-card shadow-sm">
      <button
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
        onClick={() => setOpen((v) => !v)}
        type="button"
      >
        <div className="flex items-center gap-3">
          <span className="text-2xl leading-none" role="img" aria-hidden>
            {section.icon}
          </span>
          <h3 className="text-base font-semibold text-theme-text-primary">{section.title}</h3>
        </div>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-theme-text-muted transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="space-y-4 border-t border-theme-border px-5 pb-5 pt-4">
          {section.content && (
            <p className="text-sm text-theme-text-secondary leading-relaxed">{section.content}</p>
          )}
          {section.steps && <StepList steps={section.steps} />}
          {section.diagram && <Diagram text={section.diagram} />}
          {section.tips && <TipList tips={section.tips} />}
        </div>
      )}
    </div>
  );
}

function PermissionPills({ permissions }: { permissions: string[] }) {
  if (permissions.length === 0) {
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-4">
        <p className="text-sm font-semibold text-green-700">Full access — no limitations.</p>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {permissions.map((p, i) => (
        <span
          className="flex items-center gap-1.5 rounded-full border border-green-200 bg-green-50 px-3 py-1 text-xs font-medium text-green-700"
          key={i}
        >
          <CheckCircle className="h-3 w-3" />
          {p}
        </span>
      ))}
    </div>
  );
}

function LimitationPills({ limitations }: { limitations: string[] }) {
  if (limitations.length === 0) {
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-4">
        <p className="text-sm text-green-700">✓ No limitations — full platform access.</p>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {limitations.map((l, i) => (
        <span
          className="flex items-center gap-1.5 rounded-full border border-theme-border bg-theme-card-elevated px-3 py-1 text-xs text-theme-text-muted"
          key={i}
        >
          <Lock className="h-3 w-3" />
          {l}
        </span>
      ))}
    </div>
  );
}

function RoleHero({ manual }: { manual: Manual }) {
  return (
    <div className="rounded-2xl border border-brand-200 bg-gradient-to-br from-brand-50 to-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-white shadow-md">
            <User className="h-6 w-6" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-brand-600">
              Your Role
            </p>
            <h2 className="mt-0.5 text-2xl font-bold text-theme-text-primary">
              {manual.roleLabel}
            </h2>
            <p className="mt-1 text-sm text-theme-text-secondary">{manual.tagline}</p>
          </div>
        </div>
        <Link
          className="shrink-0 rounded-lg border border-theme-border px-3 py-2 text-xs text-theme-text-secondary hover:bg-theme-card-elevated"
          to="/roles"
        >
          View permission matrix →
        </Link>
      </div>
      <p className="mt-4 text-sm text-theme-text-secondary leading-relaxed">{manual.overview}</p>
    </div>
  );
}

type Tab = 'manual' | 'permissions' | 'common';

export function ManualPage() {
  const { user } = useAuth();
  const role = user?.role ?? '';
  const manual = MANUALS[role];
  const [activeTab, setActiveTab] = useState<Tab>('manual');
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);

  if (!manual) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-500" />
        <div>
          <p className="text-lg font-semibold text-theme-text-primary">
            No manual found for your role
          </p>
          <p className="mt-1 text-sm text-theme-text-secondary">
            Role key:{' '}
            <code className="rounded bg-theme-card-elevated px-1 text-xs text-brand-600">
              {role || 'unknown'}
            </code>
          </p>
        </div>
      </div>
    );
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'manual', label: 'How-To Guide' },
    { key: 'permissions', label: 'Permissions & Limits' },
    { key: 'common', label: 'Common Features' }
  ];

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Page header */}
      <div>
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-brand-600" />
          <p className="text-sm font-medium text-brand-600">User Manual</p>
        </div>
        <h1 className="mt-1 text-2xl font-semibold text-theme-text-primary">
          {manual.roleLabel} Manual
        </h1>
        <p className="mt-1 text-sm text-theme-text-secondary">
          A practical guide tailored to your role. Learn how to use every feature available to you.
        </p>
      </div>

      {/* Role hero card */}
      <RoleHero manual={manual} />

      {/* Tabs */}
      <div className="flex gap-1 border-b border-theme-border">
        {tabs.map((t) => (
          <button
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === t.key
                ? 'border-b-2 border-brand-600 text-brand-600'
                : 'text-theme-text-secondary hover:text-theme-text-primary'
            }`}
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            type="button"
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab: How-To Guide */}
      {activeTab === 'manual' && (
        <div className="space-y-4">
          {/* Jump-to TOC */}
          <div className="rounded-lg border border-theme-border bg-theme-card p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-theme-text-muted">
              Sections in this guide
            </p>
            <div className="flex flex-wrap gap-2">
              {manual.sections.map((s) => (
                <button
                  className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    activeSectionId === s.id
                      ? 'border-brand-300 bg-brand-50 text-brand-600'
                      : 'border-theme-border text-theme-text-secondary hover:border-brand-300 hover:text-brand-600'
                  }`}
                  key={s.id}
                  onClick={() => {
                    setActiveSectionId(activeSectionId === s.id ? null : s.id);
                    document
                      .getElementById(`section-${s.id}`)
                      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                  }}
                  type="button"
                >
                  <span role="img" aria-hidden>
                    {s.icon}
                  </span>
                  {s.title}
                </button>
              ))}
            </div>
          </div>

          {/* Sections */}
          {manual.sections.map((section) => (
            <div id={`section-${section.id}`} key={section.id}>
              <SectionCard section={section} />
            </div>
          ))}
        </div>
      )}

      {/* Tab: Permissions & Limits */}
      {activeTab === 'permissions' && (
        <div className="space-y-6">
          <section>
            <div className="mb-3 flex items-center gap-2">
              <Unlock className="h-4 w-4 text-green-600" />
              <h3 className="text-sm font-semibold text-theme-text-primary">What you can do</h3>
            </div>
            <PermissionPills permissions={manual.permissions} />
          </section>

          <section>
            <div className="mb-3 flex items-center gap-2">
              <Lock className="h-4 w-4 text-theme-text-muted" />
              <h3 className="text-sm font-semibold text-theme-text-primary">What you cannot do</h3>
            </div>
            <LimitationPills limitations={manual.limitations} />
          </section>

          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
            <div className="flex gap-2">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
              <p className="text-sm text-blue-700">
                Permissions are set by an Admin and cannot be changed by you. If you believe your
                role is incorrect, contact your system administrator.{' '}
                <Link className="font-semibold underline" to="/roles">
                  View the full permissions matrix →
                </Link>
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Common Features */}
      {activeTab === 'common' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-theme-border bg-theme-card p-4 text-sm text-theme-text-secondary">
            These features are available to{' '}
            <strong className="text-theme-text-primary">all authenticated users</strong> regardless
            of role.
          </div>
          {COMMON_SECTIONS.map((section) => (
            <SectionCard key={section.id} section={section} />
          ))}
        </div>
      )}
    </div>
  );
}
