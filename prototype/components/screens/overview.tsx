import type { ReactNode } from "react";
import { AlertCircle, ArrowRight, BookOpenCheck, Building2, ClipboardList, Eye, FileCheck2, FileText, Map, MousePointer2, Play, Send, Upload, UsersRound } from "lucide-react";

import { apiEndpoints, businessFlow, featureGuides, kpis, launchModules, operatingCapabilities, operatingDomains, remainingInputs, requirementCoverage, type ScreenKey } from "@/lib/portal-data";
import { AttachmentList, Checklist, MetricCard, Panel, WalkthroughTimeline } from "@/components/shared";
import { screenTitles } from "@/components/screen-titles";

export function OverviewScreen({
  onOpen,
  onStartTour,
}: {
  onOpen: (screen: ScreenKey) => void;
  onStartTour: () => void;
}) {
  return (
    <div className="screenStack">
      <section className="heroPanel" data-tour-target="hero-overview">
        <div>
          <span className="eyebrow">Construction operations platform</span>
          <h2>Site activity connected to management visibility.</h2>
          <p>
            A guided operating flow for field teams, managers, accounts, and leadership
            covering daily reports, approvals, document control, and inventory across
            all construction projects.
          </p>
          <div className="heroActions">
            <button onClick={onStartTour} type="button">
              Guided walkthrough <Play size={17} />
            </button>
            <button className="ghostButton" onClick={() => onOpen("dashboard")} type="button">
              Skip tour / explore modules
            </button>
          </div>
        </div>
        <div className="pulsePanel" data-tour-target="operations-pulse">
          <div className="pulseHeader">
            <span>Today</span>
            <strong>Operations Pulse</strong>
          </div>
          <div className="kpiGrid compact">
            {kpis.slice(0, 4).map((item) => (
              <MetricCard key={item.label} {...item} />
            ))}
          </div>
          <div className="liveTimeline">
            <span />
            <p>Supervisor update submitted — 3 sites</p>
            <span />
            <p>Engineer quality verification pending</p>
            <span />
            <p>Project Manager approval next</p>
          </div>
        </div>
      </section>

      <Panel title="Core daily workflow" icon={<Map size={18} />}>
        <BusinessFlowMap onOpen={onOpen} />
      </Panel>

      <section className="dualGrid wideLeft">
        <Panel title="End-to-end user journey" icon={<ArrowRight size={18} />}>
          <WalkthroughTimeline />
        </Panel>
        <Panel title="What the platform delivers" icon={<Eye size={18} />}>
          <Checklist
            items={[
              "The product has a clear daily workflow, not only disconnected screens",
              "Every role sees why the portal replaces chats, folders, and spreadsheets",
              "Approvals, documents, photos, and audit records are connected to business outcomes",
              "Phase 2 and Phase 3 modules are visible without confusing the MVP scope",
            ]}
          />
        </Panel>
      </section>

      <details className="moreDetails">
        <summary>More details</summary>
        <div className="screenStack">
          <section className="domainGrid" data-tour-target="before-after">
            {operatingDomains.map((item) => (
              <article className="domainCard" key={item.area}>
                <h3>{item.area}</h3>
                <p>{item.description}</p>
                <div className="domainSections">
                  <span>Covers</span>
                  <em>{item.sections}</em>
                </div>
              </article>
            ))}
          </section>

          <section className="contentGrid five" data-tour-target="executive-value">
            {operatingCapabilities.map((item) => (
              <article className="capabilityCard" key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <p>{item.detail}</p>
              </article>
            ))}
          </section>

          <Panel title="Requirements coverage by module" icon={<BookOpenCheck size={18} />}>
            <CoverageMatrix onOpen={onOpen} />
          </Panel>

          <section className="contentGrid three" data-tour-target="launch-modules">
            {launchModules.map((item) => (
              <article className="featureCard" key={item.title}>
                <item.icon size={22} />
                <span>{item.phase}</span>
                <h3>{item.title}</h3>
                <p>{item.summary}</p>
              </article>
            ))}
          </section>

          <section className="dualGrid">
            <Panel title="Sample files across the platform" icon={<Upload size={18} />}>
              <AttachmentList compact />
            </Panel>
            <Panel title="API surfaces represented" icon={<FileText size={18} />}>
              <div className="apiList">
                {apiEndpoints.map((endpoint) => (
                  <code key={endpoint}>{endpoint}</code>
                ))}
              </div>
            </Panel>
            <Panel title="Remaining stakeholder inputs" icon={<AlertCircle size={18} />}>
              <Checklist items={remainingInputs} />
            </Panel>
          </section>
        </div>
      </details>
    </div>
  );
}

export function FeatureGuideCard({ screen }: { screen: ScreenKey }) {
  const guide = featureGuides[screen];

  return (
    <section className="featureGuide" aria-label="Feature guide" data-tour-target="feature-guide">
      <div className="guideIntro">
        <BookOpenCheck size={20} />
        <div>
          <span>Feature walkthrough</span>
          <h2>{screenTitles[screen]}</h2>
        </div>
      </div>
      <div className="guideGrid">
        <GuidePoint icon={<UsersRound size={17} />} label="Owner" value={guide.owner} />
        <GuidePoint icon={<MousePointer2 size={17} />} label="Starts when" value={guide.startsWhen} />
        <GuidePoint icon={<ClipboardList size={17} />} label="User action" value={guide.userAction} />
        <GuidePoint icon={<Building2 size={17} />} label="System action" value={guide.systemAction} />
        <GuidePoint icon={<FileCheck2 size={17} />} label="Business result" value={guide.businessResult} />
      </div>
    </section>
  );
}

function GuidePoint({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <article>
      <div>{icon}</div>
      <span>{label}</span>
      <p>{value}</p>
    </article>
  );
}

function BusinessFlowMap({ onOpen }: { onOpen: (screen: ScreenKey) => void }) {
  const flowScreens: Record<string, ScreenKey> = {
    Projects: "projects",
    "Daily Reports": "reports",
    Approvals: "approvals",
    Dashboard: "dashboard",
  };

  return (
    <div className="businessFlow" data-tour-target="business-flow">
      {businessFlow.map((item, index) => (
        <article key={item.title}>
          <div className="flowNumber">{index + 1}</div>
          <span>{item.owner}</span>
          <h3>{item.title}</h3>
          <p>{item.detail}</p>
          <button onClick={() => onOpen(flowScreens[item.screen] ?? "overview")} type="button">
            Open {item.screen}
            <Send size={14} />
          </button>
        </article>
      ))}
    </div>
  );
}

function CoverageMatrix({ onOpen }: { onOpen: (screen: ScreenKey) => void }) {
  return (
    <div className="coverageMatrix" data-tour-target="coverage-matrix">
      {requirementCoverage.map((item) => (
        <article key={item.module}>
          <div>
            <span className={`phaseBadge phase-${item.phase.replace(" ", "-").toLowerCase()}`}>
              {item.phase}
            </span>
            <strong>{item.module}</strong>
          </div>
          <small>{item.source}</small>
          <p>
            <b>Prototype:</b> {item.covered}
          </p>
          <p>
            <b>End product:</b> {item.finalBehavior}
          </p>
          <button onClick={() => onOpen(item.screen)} type="button">
            Open module <ArrowRight size={14} />
          </button>
        </article>
      ))}
    </div>
  );
}
