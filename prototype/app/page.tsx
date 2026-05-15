"use client";

import { useEffect, useMemo, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowRight,
  Bell,
  BookOpenCheck,
  BriefcaseBusiness,
  Building2,
  Camera,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  ClipboardList,
  Cloud as CloudIcon,
  Eye,
  FileCheck2,
  FileText,
  Filter,
  HardHat,
  Image,
  ListChecks,
  LogOut,
  Map,
  Menu,
  MousePointer2,
  Play,
  Plus,
  Rocket,
  Search,
  Send,
  ShieldCheck,
  Upload,
  UsersRound,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import {
  apiEndpoints,
  adminSecurityControls,
  approvalItems,
  auditRows,
  businessFlow,
  dashboardPanels,
  deliveryItems,
  documentControlStates,
  documents,
  featureGuides,
  financeCards,
  financeWorkflow,
  formSections,
  ganttTasks,
  operatingCapabilities,
  invoices,
  kpis,
  launchModules,
  inventoryItems,
  inventoryMovementFlow,
  lowStockByLocation,
  materialLifecycle,
  materialTransactions,
  mobileFieldStates,
  mobileFeatures,
  navItems,
  notifications,
  operatingDomains,
  photoCards,
  productTourSteps,
  projectSetupPreview,
  projects,
  remainingInputs,
  reportFormPreview,
  reportFlow,
  reportOutcomeCards,
  reportRows,
  requirementCoverage,
  roleMatrix,
  sampleAttachments,
  securityItems,
  storageLocations,
  suppliers,
  toolAssets,
  users,
  walkthroughSteps,
  type ScreenKey,
} from "@/lib/portal-data";

type TourRect = {
  top: number;
  left: number;
  width: number;
  height: number;
};

type TourModalPosition = {
  top: number;
  left: number;
};

const screenTitles: Record<ScreenKey, string> = {
  overview: "Platform overview",
  auth: "Login, roles, and permission model",
  dashboard: "Operational dashboard",
  projects: "Projects and Gantt timeline",
  reports: "Daily reports and field update flow",
  approvals: "Approval inbox and routing",
  materials: "Inventory & Stores",
  documents: "Document control and versioning",
  photos: "Photo evidence and media handling",
  accounts: "Accounts and financial controls",
  notifications: "Notifications and alerts",
  admin: "Admin, users, and audit logs",
  mobile: "Mobile and offline behavior",
  security: "Security and compliance",
  delivery: "Delivery, deployment, and migration",
};

export default function Home() {
  const [activeScreen, setActiveScreen] = useState<ScreenKey>("overview");
  const [selectedProject, setSelectedProject] = useState(projects[0]);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [tourOpen, setTourOpen] = useState(true);
  const [tourIndex, setTourIndex] = useState(0);
  const [tourRect, setTourRect] = useState<TourRect | null>(null);
  const [tourModalPosition, setTourModalPosition] = useState<TourModalPosition | null>(null);

  const activeNav = useMemo(
    () => navItems.find((item) => item.key === activeScreen),
    [activeScreen],
  );

  const activeTourStep = productTourSteps[tourIndex];

  const selectScreen = (screen: ScreenKey) => {
    setActiveScreen(screen);
    setMobileNavOpen(false);
  };

  const startTour = () => {
    setTourOpen(true);
    setTourIndex(0);
    selectScreen(productTourSteps[0].screen);
  };

  const goToTourStep = (nextIndex: number) => {
    const boundedIndex = (nextIndex + productTourSteps.length) % productTourSteps.length;
    setTourIndex(boundedIndex);
    selectScreen(productTourSteps[boundedIndex].screen);
    setTourOpen(true);
  };

  useEffect(() => {
    const handleTourControl = (event: PointerEvent | MouseEvent) => {
      if (event.type === "click" && "detail" in event && event.detail > 0) {
        return;
      }

      if (!(event.target instanceof Element)) {
        return;
      }

      const control = event.target.closest<HTMLElement>("[data-tour-action]");
      if (!control) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();

      const action = control.dataset.tourAction;
      if (action === "next") {
        goToTourStep(tourIndex + 1);
      }
      if (action === "prev") {
        goToTourStep(tourIndex - 1);
      }
      if (action === "close") {
        setTourOpen(false);
      }
      if (action === "step" && control.dataset.tourStep) {
        goToTourStep(Number(control.dataset.tourStep));
      }
    };

    document.addEventListener("pointerdown", handleTourControl, true);
    document.addEventListener("mousedown", handleTourControl, true);
    document.addEventListener("click", handleTourControl, true);

    return () => {
      document.removeEventListener("pointerdown", handleTourControl, true);
      document.removeEventListener("mousedown", handleTourControl, true);
      document.removeEventListener("click", handleTourControl, true);
    };
  }, [tourIndex]);

  useEffect(() => {
    if (!tourOpen) {
      setTourRect(null);
      setTourModalPosition(null);
      return;
    }

    let frameId = 0;
    let timeoutId = 0;

    const updateTourTarget = (shouldScroll = false) => {
      const target = document.querySelector<HTMLElement>(
        `[data-tour-target="${activeTourStep.target}"]`,
      );

      if (!target) {
        setTourRect(null);
        setTourModalPosition(null);
        return;
      }

      if (shouldScroll) {
        target.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
      }

      timeoutId = window.setTimeout(() => {
        const rect = target.getBoundingClientRect();
        const padding = 8;
        const nextRect = {
          top: Math.max(rect.top - padding, 8),
          left: Math.max(rect.left - padding, 8),
          width: Math.min(rect.width + padding * 2, window.innerWidth - 16),
          height: Math.min(rect.height + padding * 2, window.innerHeight - 16),
        };

        setTourRect(nextRect);
        setTourModalPosition(getTourModalPosition(nextRect, activeTourStep.position));
      }, 220);
    };

    const handleResize = () => updateTourTarget(false);
    const handleScroll = () => updateTourTarget(false);

    frameId = window.requestAnimationFrame(() => updateTourTarget(true));
    window.addEventListener("resize", handleResize);
    window.addEventListener("scroll", handleScroll, true);

    return () => {
      window.cancelAnimationFrame(frameId);
      window.clearTimeout(timeoutId);
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [activeTourStep, activeScreen, tourOpen]);

  return (
    <main className="appShell">
      <aside className={`sideRail ${mobileNavOpen ? "isOpen" : ""}`} aria-label="Prototype modules">
        <div className="brandBlock">
          <div className="brandIcon">GI</div>
          <div>
            <strong>Garrisons</strong>
            <span>Internal Portal</span>
          </div>
        </div>

        <nav className="moduleNav">
          {navItems.map((item) => (
            <button
              className={[
                item.key === activeScreen ? "isActive" : "",
                tourOpen && item.key === activeTourStep.screen ? "isTourTarget" : "",
              ].join(" ")}
              key={item.key}
              onClick={() => selectScreen(item.key)}
              type="button"
            >
              <item.icon size={17} />
              <span>{item.label}</span>
              <small>{item.phase}</small>
            </button>
          ))}
        </nav>

        <div className="prototypeStatus">
          <span>Coverage</span>
          <strong>All documented modules</strong>
          <p>Interactive dummy data for stakeholder walkthroughs.</p>
        </div>
      </aside>

      <section className="workspace">
        <header className="topBar">
          <button
            aria-label="Toggle module navigation"
            className="mobileMenu"
            onClick={() => setMobileNavOpen((value) => !value)}
            type="button"
          >
            <Menu size={20} />
          </button>
          <div>
            <span className="breadcrumb">
              Prototype <ChevronRight size={14} /> {activeNav?.phase}
            </span>
            <h1>{screenTitles[activeScreen]}</h1>
          </div>
          <div className="topActions">
            <div className="searchBox">
              <Search size={16} />
              <span>Search reports, docs, inventory</span>
            </div>
            <button data-tour-target="notification-bell" type="button">
              <Bell size={16} />
              17
            </button>
            <button className="tourButton" onClick={startTour} type="button">
              <Play size={16} />
              Walkthrough
            </button>
            <button type="button">
              <LogOut size={16} />
            </button>
          </div>
        </header>

        {tourOpen ? (
          <ProductTourOverlay
            activeStep={activeTourStep}
            index={tourIndex}
            modalPosition={tourModalPosition}
            onClose={() => setTourOpen(false)}
            onNext={() => goToTourStep(tourIndex + 1)}
            onPrev={() => goToTourStep(tourIndex - 1)}
            onStep={goToTourStep}
            targetRect={tourRect}
          />
        ) : (
          <button className="floatingTourButton" onClick={startTour} type="button">
            <Rocket size={17} />
            Guided walkthrough
          </button>
        )}

        <section className="screenCard" key={activeScreen}>
          {activeScreen !== "overview" ? <FeatureGuideCard screen={activeScreen} /> : null}
          {activeScreen === "overview" ? <OverviewScreen onOpen={selectScreen} onStartTour={startTour} /> : null}
          {activeScreen === "auth" ? <AuthScreen /> : null}
          {activeScreen === "dashboard" ? <DashboardScreen /> : null}
          {activeScreen === "projects" ? (
            <ProjectsScreen selectedProject={selectedProject} setSelectedProject={setSelectedProject} />
          ) : null}
          {activeScreen === "reports" ? <ReportsScreen /> : null}
          {activeScreen === "approvals" ? <ApprovalsScreen /> : null}
          {activeScreen === "materials" ? <MaterialsScreen /> : null}
          {activeScreen === "documents" ? <DocumentsScreen /> : null}
          {activeScreen === "photos" ? <PhotosScreen /> : null}
          {activeScreen === "accounts" ? <AccountsScreen /> : null}
          {activeScreen === "notifications" ? <NotificationsScreen /> : null}
          {activeScreen === "admin" ? <AdminScreen /> : null}
          {activeScreen === "mobile" ? <MobileScreen /> : null}
          {activeScreen === "security" ? <SecurityScreen /> : null}
          {activeScreen === "delivery" ? <DeliveryScreen /> : null}
        </section>
      </section>
    </main>
  );
}

function getTourModalPosition(
  rect: TourRect,
  preferredPosition: "top" | "right" | "bottom" | "left" = "bottom",
): TourModalPosition {
  const gap = 14;
  const modalWidth = Math.min(390, window.innerWidth - 28);
  const modalHeight = Math.min(430, window.innerHeight - 28);
  const centeredLeft = rect.left + rect.width / 2 - modalWidth / 2;
  const clampLeft = (value: number) => Math.min(Math.max(value, 14), window.innerWidth - modalWidth - 14);
  const clampTop = (value: number) => Math.min(Math.max(value, 14), window.innerHeight - modalHeight - 14);

  if (preferredPosition === "top" && rect.top > modalHeight + gap) {
    return { top: clampTop(rect.top - modalHeight - gap), left: clampLeft(centeredLeft) };
  }

  if (preferredPosition === "right" && rect.left + rect.width + modalWidth + gap < window.innerWidth) {
    return { top: clampTop(rect.top), left: clampLeft(rect.left + rect.width + gap) };
  }

  if (preferredPosition === "left" && rect.left > modalWidth + gap) {
    return { top: clampTop(rect.top), left: clampLeft(rect.left - modalWidth - gap) };
  }

  if (rect.top + rect.height + modalHeight + gap < window.innerHeight) {
    return { top: clampTop(rect.top + rect.height + gap), left: clampLeft(centeredLeft) };
  }

  return { top: clampTop(rect.top - modalHeight - gap), left: clampLeft(centeredLeft) };
}

function StatusPill({ status }: { status: string }) {
  const normalized = status.toLowerCase().replace(/\s+/g, "-");
  const label = status;
  return <span className={`statusPill ${normalized}`}>{label}</span>;
}

function OverviewScreen({
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

      <Panel title="End-to-end business flow" icon={<Map size={18} />}>
        <BusinessFlowMap onOpen={onOpen} />
      </Panel>

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
  );
}

function ProductTourOverlay({
  activeStep,
  index,
  targetRect,
  modalPosition,
  onClose,
  onNext,
  onPrev,
  onStep,
}: {
  activeStep: (typeof productTourSteps)[number];
  index: number;
  targetRect: TourRect | null;
  modalPosition: TourModalPosition | null;
  onClose: () => void;
  onNext: () => void;
  onPrev: () => void;
  onStep: (index: number) => void;
}) {
  const isFinalStep = index === productTourSteps.length - 1;
  const resolvedModalPosition =
    targetRect && typeof window !== "undefined"
      ? getTourModalPosition(targetRect, activeStep.position)
      : modalPosition;
  const runTourAction = (
    event: ReactPointerEvent<HTMLButtonElement>,
    action: () => void,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    action();
  };

  return (
    <div className="productTourLayer" aria-label="Interactive product tour" aria-modal="true" role="dialog">
      {targetRect ? (
        <>
          <div className="tourShade top" style={{ height: targetRect.top }} />
          <div
            className="tourShade left"
            style={{
              top: targetRect.top,
              width: targetRect.left,
              height: targetRect.height,
            }}
          />
          <div
            className="tourShade right"
            style={{
              top: targetRect.top,
              left: targetRect.left + targetRect.width,
              height: targetRect.height,
            }}
          />
          <div
            className="tourShade bottom"
            style={{ top: targetRect.top + targetRect.height }}
          />
          <div
            className="tourSpotlight"
            style={{
              top: targetRect.top,
              left: targetRect.left,
              width: targetRect.width,
              height: targetRect.height,
            }}
          />
        </>
      ) : (
        <div className="tourShade full" />
      )}

      <section
        className="tourInstructionModal"
        style={
          resolvedModalPosition
            ? { top: resolvedModalPosition.top, left: resolvedModalPosition.left }
            : undefined
        }
      >
        <button
          aria-label="Close walkthrough"
          className="tourCloseButton"
          data-tour-action="close"
          onPointerDown={(event) => runTourAction(event, onClose)}
          type="button"
        >
          <X size={16} />
        </button>
        <div className="tourModalBody">
          <span className="tourEyebrow">{activeStep.eyebrow}</span>
          <h2>{activeStep.title}</h2>
          <p>{activeStep.body}</p>
          <div className="tourInstruction">
            <strong>How to present it</strong>
            <span>{activeStep.instruction}</span>
          </div>
          <div className="tourProgress">
            <span>
              {index + 1} / {productTourSteps.length}
            </span>
            <div>
              {productTourSteps.map((step, stepIndex) => (
                <button
                  aria-label={`Go to ${step.title}`}
                  className={stepIndex === index ? "isActive" : ""}
                  data-tour-action="step"
                  data-tour-step={stepIndex}
                  key={step.title}
                  onPointerDown={(event) => runTourAction(event, () => onStep(stepIndex))}
                  type="button"
                />
              ))}
            </div>
          </div>
        </div>
        <div className="tourButtons">
          <button
            className="ghostButton"
            data-tour-action="prev"
            onPointerDown={(event) => runTourAction(event, onPrev)}
            type="button"
          >
            Previous
          </button>
          <button
            data-tour-action="next"
            onPointerDown={(event) => runTourAction(event, onNext)}
            type="button"
          >
            {isFinalStep ? "Restart tour" : "Next"}
            <ArrowRight size={17} />
          </button>
        </div>
      </section>
    </div>
  );
}

function FeatureGuideCard({ screen }: { screen: ScreenKey }) {
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

function MiniFactGrid({
  rows,
  target,
}: {
  rows: { label: string; value?: string; detail?: string; status?: string }[];
  target?: string;
}) {
  return (
    <div className="miniFactGrid" data-tour-target={target}>
      {rows.map((row) => (
        <article key={`${row.label}-${row.value}`}>
          <span>{row.label}</span>
          {row.value ? <strong>{row.value}</strong> : null}
          {row.status ? <em>{row.status}</em> : null}
          {row.detail ? <p>{row.detail}</p> : null}
        </article>
      ))}
    </div>
  );
}

function ProcessStrip({
  rows,
  target,
}: {
  rows: { step?: string; state?: string; owner?: string; detail: string }[];
  target?: string;
}) {
  return (
    <div className="processStrip" data-tour-target={target}>
      {rows.map((row, index) => (
        <article key={`${row.step ?? row.state}-${index}`}>
          <span>{index + 1}</span>
          <div>
            <strong>{row.step ?? row.state}</strong>
            {row.owner ? <small>{row.owner}</small> : null}
            <p>{row.detail}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

function AuthScreen() {
  return (
    <div className="screenStack">
      <div className="dualGrid">
        <div data-tour-target="auth-login">
          <Panel title="Login experience" icon={<ShieldCheck size={18} />}>
            <div className="loginMock">
              <label>Email</label>
              <div>engineer@garrisons.example</div>
              <label>Password</label>
              <div>••••••••••••</div>
              <label>2FA code</label>
              <div>184 902</div>
              <button type="button">Sign in securely</button>
            </div>
          </Panel>
        </div>
        <Panel title="Session and security decisions" icon={<CheckCircle2 size={18} />}>
          <Checklist
            items={[
              "Email OTP for MVP two-factor authentication",
              "1-day session with short-lived access token and silent refresh",
              "3 failed attempts lock the account",
              "Admin creates accounts and can reset passwords",
              "First login requires password change",
            ]}
          />
        </Panel>
      </div>
      <DataTable
        columns={["Role", "Access scope", "Key permissions"]}
        rows={roleMatrix.map((role) => [
          role.role,
          role.access,
          role.permissions.join(", "),
        ])}
      />
    </div>
  );
}

function DashboardScreen() {
  return (
    <div className="screenStack">
      <div className="kpiGrid" data-tour-target="dashboard-kpis">
        {kpis.map((item) => (
          <MetricCard key={item.label} {...item} />
        ))}
      </div>
      <MiniFactGrid rows={dashboardPanels} target="dashboard-risk-panels" />
      <section className="dualGrid">
        <Panel title="Project progress chart" icon={<CircleDashed size={18} />}>
          <BarList
            rows={projects.map((project) => ({
              label: project.name,
              value: project.progress,
              meta: `${project.phase} • ${project.deadline}`,
            }))}
          />
        </Panel>
        <Panel title="Pending approvals widget" icon={<ShieldCheck size={18} />}>
          <CardList
            rows={approvalItems.slice(0, 3).map((item) => ({
              title: item.title,
              meta: `${item.type} • ${item.sla}`,
              badge: item.status,
            }))}
          />
        </Panel>
      </section>
    </div>
  );
}

function ProjectsScreen({
  selectedProject,
  setSelectedProject,
}: {
  selectedProject: (typeof projects)[number];
  setSelectedProject: (project: (typeof projects)[number]) => void;
}) {
  return (
    <div className="screenStack">
      <div className="projectSelector" data-tour-target="project-selector">
        {projects.map((project) => (
          <button
            className={project.code === selectedProject.code ? "selected" : ""}
            key={project.code}
            onClick={() => setSelectedProject(project)}
            type="button"
          >
            <strong>{project.code}</strong>
            <span>{project.name}</span>
          </button>
        ))}
      </div>
      <section className="dualGrid wideLeft">
        <Panel title={`${selectedProject.name} details`} icon={<HardHat size={18} />}>
          <div className="detailGrid">
            <Detail label="Location" value={selectedProject.location} />
            <Detail label="Manager" value={selectedProject.manager} />
            <Detail label="Deadline" value={selectedProject.deadline} />
            <Detail label="Budget" value={selectedProject.budget} />
            <Detail
              label="Reports"
              value={`${selectedProject.reports} (${selectedProject.delayed} delayed)`}
            />
            <Detail label="Phase" value={selectedProject.phase} />
          </div>
          <BarList
            rows={selectedProject.disciplines.map((item) => ({
              label: item.name,
              value: item.value,
              meta: "approved quantity / planned quantity",
            }))}
          />
        </Panel>
        <Panel title="BOQ and progress rules" icon={<ListChecks size={18} />}>
          <Checklist
            items={[
              "BOQ supports manual entry and spreadsheet import",
              "Fields: item code, description, unit, quantity, rate, amount, discipline, phase, milestone",
              "Project code is auto-generated",
              "Progress is weighted by discipline/BOQ progress",
            ]}
          />
        </Panel>
      </section>
      <Panel title="Project setup preview" icon={<BriefcaseBusiness size={18} />}>
        <MiniFactGrid rows={projectSetupPreview} target="project-setup-preview" />
      </Panel>
      <div data-tour-target="gantt-timeline">
        <Panel title="Gantt-style timeline" icon={<CircleDashed size={18} />}>
          <div className="gantt">
            {ganttTasks.map((task) => {
              const statusClass = `status-${task.status.toLowerCase().replace(/\s+/g, "-")}`;
              return (
                <div className="ganttRow" key={task.task}>
                  <span>{task.task}</span>
                  <div className="ganttTrack">
                    <div
                      className={statusClass}
                      style={{ marginLeft: `${task.start}%`, width: `${task.span}%` }}
                    >
                      {task.status}
                    </div>
                  </div>
                  <small>{task.owner}</small>
                </div>
              );
            })}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function ReportsScreen() {
  const statusLabels: Record<string, string> = {
    Submitted: "active",
    "In review": "pending",
    Pending: "pending",
    Automatic: "draft",
  };

  return (
    <div className="screenStack">
      <section className="flowGrid" data-tour-target="report-flow">
        {reportFlow.map((step, index) => (
          <article className="flowCard" key={step.title}>
            <span>{index + 1}</span>
            <small>
              <StatusPill status={statusLabels[step.status] ?? step.status} />
            </small>
            <h3>{step.title}</h3>
            <strong>{step.owner}</strong>
            <p>{step.detail}</p>
          </article>
        ))}
      </section>
      <section className="dualGrid wideLeft">
        <Panel title="Daily report list" icon={<Filter size={18} />}>
          <DataTable
            columns={["Report no.", "Project", "Status", "Progress", "Photos", "Due"]}
            rows={reportRows.map((row) => [
              row.no,
              row.project,
              row.status,
              row.progress,
              `${row.photos}/5`,
              row.due,
            ])}
          />
        </Panel>
        <div data-tour-target="report-form-preview">
          <Panel title="Live report form preview" icon={<Plus size={18} />}>
            <MiniFactGrid rows={reportFormPreview} />
          </Panel>
        </div>
      </section>
      <section className="dualGrid">
        <Panel title="Required form sections" icon={<ListChecks size={18} />}>
          <Checklist items={formSections} />
        </Panel>
        <Panel title="What happens after submit" icon={<FileCheck2 size={18} />}>
          <MiniFactGrid rows={reportOutcomeCards} target="report-outcomes" />
        </Panel>
      </section>
      <Panel title="Sample report attachments" icon={<Upload size={18} />}>
        <AttachmentList filter={["Daily Report PDF", "Watermarked Photo", "WIR Document"]} />
      </Panel>
    </div>
  );
}

function ApprovalsScreen() {
  const approvalStatusMap: Record<string, string> = {
    "PM pending": "Pending",
    "OM required": "Pending",
    "Accounts checked": "Approved",
  };

  return (
    <div className="screenStack">
      <section className="contentGrid two" data-tour-target="approval-cards">
        {approvalItems.map((item) => (
          <article className="approvalCard" key={item.title}>
            <span>{item.type}</span>
            <h3>{item.title}</h3>
            <p>{item.route}</p>
            <div>
              <strong>{item.sla}</strong>
              <StatusPill status={approvalStatusMap[item.status] ?? item.status} />
            </div>
            <div className="buttonRow">
              <button type="button">Approve</button>
              <button className="dangerButton" type="button">Reject with reason</button>
            </div>
          </article>
        ))}
      </section>
      <Panel title="Approval rules" icon={<ShieldCheck size={18} />}>
        <Checklist
          items={[
            "Approver is selected automatically by project/role",
            "Rejection reason is mandatory",
            "24-hour reminder and 48-hour escalation",
            "Admin override and delegation require audit reason",
            "Approval comments visible only to managers",
          ]}
        />
      </Panel>
    </div>
  );
}

function MaterialsScreen() {
  return (
    <div className="screenStack">
      <Panel title="Warehouse and site stores" icon={<PackageIcon />}>
        <section className="locationCardGrid" data-tour-target="storage-locations">
          {storageLocations.map((location) => (
            <article key={location.code}>
              <div>
                <span>{location.code}</span>
                <StatusPill status={location.status} />
              </div>
              <h3>{location.name}</h3>
              <p>{location.project}</p>
              <div className="locationMeta">
                <strong>{location.type}</strong>
                <span>{location.items}</span>
                <em>{location.lowStock} low-stock</em>
              </div>
            </article>
          ))}
        </section>
      </Panel>

      <section className="dualGrid wideLeft">
        <div data-tour-target="materials-inventory">
          <Panel title="Inventory stock matrix" icon={<PackageIcon />}>
            <DataTable
              columns={["Code", "Item", "Type", "Total", "Reserved", "Available", "Current location", "Status"]}
              rows={inventoryItems.map((item) => [
                item.code,
                item.name,
                item.type,
                `${item.totalStock} ${item.unit}`,
                `${item.reserved} ${item.unit}`,
                `${item.available} ${item.unit}`,
                item.currentLocation,
                <StatusPill key={item.status} status={item.status} />,
              ])}
            />
          </Panel>
        </div>
        <Panel title="Request lifecycle" icon={<RouteIcon />}>
          <Checklist items={materialLifecycle} />
        </Panel>
      </section>

      <section className="dualGrid">
        <Panel title="Stock by warehouse/site" icon={<ListChecks size={18} />}>
          <DataTable
            columns={["Item", "Location", "On hand", "Reserved", "Available", "Status"]}
            rows={inventoryItems.flatMap((item) =>
              item.locations.map((location) => [
                item.name,
                location.location,
                `${location.onHand} ${item.unit}`,
                `${location.reserved} ${item.unit}`,
                `${location.available} ${item.unit}`,
                <StatusPill key={`${item.code}-${location.location}`} status={location.status} />,
              ]),
            )}
          />
        </Panel>
        <Panel title="Low stock by location" icon={<AlertCircle size={18} />}>
          <DataTable
            columns={["Location", "Item", "Available", "Minimum", "Status"]}
            rows={lowStockByLocation.map((item) => [
              item.location,
              item.item,
              item.available,
              item.minimum,
              <StatusPill key={`${item.location}-${item.item}`} status={item.status} />,
            ])}
          />
        </Panel>
      </section>

      <Panel title="Current tool/item location tracker" icon={<Map size={18} />}>
        <section className="assetTrackerGrid" data-tour-target="tool-location-tracker">
          {toolAssets.map((asset) => (
            <article key={asset.tag}>
              <div>
                <strong>{asset.tag}</strong>
                <StatusPill status={asset.status} />
              </div>
              <h3>{asset.item}</h3>
              <p>{asset.currentLocation}</p>
              <dl>
                <div>
                  <dt>Project</dt>
                  <dd>{asset.project}</dd>
                </div>
                <div>
                  <dt>Condition</dt>
                  <dd>{asset.condition}</dd>
                </div>
              </dl>
              <small>{asset.lastMovement}</small>
            </article>
          ))}
        </section>
      </Panel>

      <section className="dualGrid">
        <Panel title="Supplier management" icon={<Upload size={18} />}>
          <DataTable
            columns={["Supplier", "Category", "Terms", "TDS"]}
            rows={suppliers.map((supplier) => [
              supplier.name,
              supplier.category,
              supplier.terms,
              supplier.tds,
            ])}
          />
        </Panel>
        <Panel title="Material rules" icon={<CheckCircle2 size={18} />}>
          <Checklist
            items={[
              "No negative stock",
              "Issue and transfer require approval before stock moves",
              "Warehouse/site location is mandatory for every movement",
              "Asset-tagged tools keep current warehouse/site location",
              "Unit conversion configured per material",
              "Pricing restricted to allowed finance/management roles",
            ]}
          />
        </Panel>
      </section>
      <section className="dualGrid wideLeft">
        <Panel title="Approved issue and transfer workflow" icon={<RouteIcon />}>
          <ProcessStrip rows={inventoryMovementFlow} target="material-flow" />
        </Panel>
        <Panel title="Recent inventory movements" icon={<FileText size={18} />}>
          <DataTable
            columns={["Type", "Item", "Qty", "From", "To", "Approval"]}
            rows={materialTransactions.map((item) => [
              item.type,
              item.item,
              item.qty,
              item.from,
              item.to,
              item.approval,
            ])}
          />
        </Panel>
      </section>
      <Panel title="Sample inventory and supplier attachments" icon={<Upload size={18} />}>
        <AttachmentList filter={["Supplier Compliance", "BOQ Import"]} />
      </Panel>
    </div>
  );
}

function DocumentsScreen() {
  return (
    <div className="screenStack">
      <section className="toolbarMock">
        <button type="button"><Upload size={15} /> Upload document</button>
        <button type="button"><Search size={15} /> Search contents</button>
        <button type="button"><Filter size={15} /> Type/project filters</button>
      </section>
      <div data-tour-target="documents-table">
        <DataTable
          columns={["Document no.", "Type", "Project", "Version", "Status", "Size"]}
          rows={documents.map((doc) => [
            doc.number,
            doc.type,
            doc.project,
            doc.version,
            doc.status,
            doc.size,
          ])}
        />
      </div>
      <section className="dualGrid">
        <Panel title="Version control preview" icon={<FileText size={18} />}>
          <div className="versionStack">
            <div>
              <strong>Rev C</strong>
              <StatusPill status="pending" />
            </div>
            <div>
              <strong>Rev B</strong>
              <StatusPill status="active" />
            </div>
            <div>
              <strong>Rev A</strong>
              <StatusPill status="superseded" />
            </div>
          </div>
        </Panel>
        <Panel title="Document decisions" icon={<CheckCircle2 size={18} />}>
          <Checklist
            items={[
              "First release: MAR, MIR, WIR, delivery notes",
              "PDF preview in browser",
              "CAD/DWG stored and downloadable; preview later",
              "60 MB max file size",
              "Expiry dates and renewal reminders",
            ]}
          />
        </Panel>
      </section>
      <Panel title="Document governance flow" icon={<ShieldCheck size={18} />}>
        <ProcessStrip rows={documentControlStates} target="document-flow" />
      </Panel>
      <Panel title="Sample controlled documents" icon={<Upload size={18} />}>
        <AttachmentList filter={["WIR Document", "BOQ Import", "Daily Report PDF"]} />
      </Panel>
    </div>
  );
}

function PhotosScreen() {
  return (
    <div className="screenStack">
      <section className="photoGrid" data-tour-target="photo-grid">
        {photoCards.map((photo) => (
          <article className={`photoCard tone-${photo.tone}`} key={photo.label}>
            <div />
            <span>{photo.project}</span>
            <h3>{photo.label}</h3>
            <p>{photo.meta}</p>
          </article>
        ))}
      </section>
      <Panel title="Media handling rules" icon={<Camera size={18} />}>
        <Checklist
          items={[
            "Maximum 5 photos per report",
            "10 MB per file",
            "Store original, compressed display image, and thumbnail",
            "Recommended compression: 1920px longest side, quality 75-85",
            "Watermark with company name",
            "Deleted photos recoverable by Admin",
          ]}
        />
      </Panel>
      <Panel title="Sample media attachment" icon={<Upload size={18} />}>
        <AttachmentList filter={["Watermarked Photo"]} />
      </Panel>
    </div>
  );
}

function AccountsScreen() {
  return (
    <div className="screenStack">
      <div className="kpiGrid compact" data-tour-target="finance-kpis">
        {financeCards.map((card) => (
          <article className="metricCard" key={card.label}>
            <card.icon size={20} />
            <span>{card.label}</span>
            <strong>{card.value}</strong>
          </article>
        ))}
      </div>
      <DataTable
        columns={["Invoice", "Supplier", "Amount", "Status"]}
        rows={invoices.map((invoice) => [
          invoice.no,
          invoice.supplier,
          invoice.amount,
          invoice.status,
        ])}
      />
      <Panel title="Invoice to project P&L workflow" icon={<FileCheck2 size={18} />}>
        <MiniFactGrid rows={financeWorkflow} target="finance-workflow" />
      </Panel>
      <Panel title="Finance requirements" icon={<CheckCircle2 size={18} />}>
        <Checklist
          items={[
            "Structured invoice fields, not only document upload",
            "Accounts create/check, Operation Manager approves",
            "Project budget vs actual cost",
            "Manpower cost and salary sheets",
            "Bookkeeping and project-wise profit/loss",
            "OCR is future enhancement, not MVP",
          ]}
        />
      </Panel>
      <Panel title="Sample finance attachment" icon={<Upload size={18} />}>
        <AttachmentList filter={["Invoice"]} />
      </Panel>
    </div>
  );
}

function NotificationsScreen() {
  return (
    <div className="screenStack">
      <section className="contentGrid two" data-tour-target="notification-cards">
        {notifications.map((item) => (
          <article className="notificationCard" key={item.label}>
            <Bell size={18} />
            <h3>{item.label}</h3>
            <strong>{item.target}</strong>
            <p>{item.timing}</p>
          </article>
        ))}
      </section>
      <Panel title="Notification behavior" icon={<Bell size={18} />}>
        <Checklist
          items={[
            "In-app and email notifications",
            "Users can mute non-critical alerts",
            "90-day user-facing notification history",
            "Unread count in header",
            "Audit records retained separately",
          ]}
        />
      </Panel>
    </div>
  );
}

function AdminScreen() {
  return (
    <div className="screenStack">
      <section className="dualGrid" data-tour-target="admin-grid">
        <Panel title="User management" icon={<Plus size={18} />}>
          <DataTable
            columns={["Name", "Role", "Status", "Last login"]}
            rows={users.map((user) => [user.name, user.role, user.status, user.last])}
          />
        </Panel>
        <Panel title="Audit log" icon={<FileText size={18} />}>
          <DataTable
            columns={["Event", "Actor", "Target"]}
            rows={auditRows.map((row) => [row.event, row.actor, row.target])}
          />
        </Panel>
      </section>
      <Panel title="Admin rules" icon={<ShieldCheck size={18} />}>
        <Checklist
          items={[
            "Deactivate old users; never overwrite historical identity",
            "Customizable permissions later, fixed role matrix in MVP",
            "Approved reports cannot be edited by Admin",
            "Admin overrides require reason and audit trail",
            "Deleted records recoverable for 30 days",
          ]}
        />
      </Panel>
      <Panel title="Enterprise governance controls" icon={<ShieldCheck size={18} />}>
        <MiniFactGrid rows={adminSecurityControls} target="admin-security-controls" />
      </Panel>
    </div>
  );
}

function MobileScreen() {
  return (
    <div className="dualGrid wideLeft">
      <div data-tour-target="phone-preview">
        <Panel title="Mobile field app preview" icon={<SmartphoneIcon />}>
          <div className="phoneMock">
            <div className="phoneTop">
              <HardHat size={16} />
              Al Rayyan Villa Compound
            </div>
            <div className="phoneStep active">
              <span className="phoneStepDot success" />
              Supervisor update saved
            </div>
            <div className="phoneStep">
              <span className="phoneStepDot pending" />
              Engineer verification pending
            </div>
            <div className="phoneStep">
              <span className="phoneStepDot queue" />
              <span>5 photos queued for upload</span>
            </div>
            <div className="phoneProgressBar">
              <span style={{ width: "65%" }} />
            </div>
            <div className="phoneSyncStatus">
              <WifiOff size={14} />
              <span>2 items waiting for network</span>
            </div>
            <button type="button">Sync when online</button>
          </div>
        </Panel>
      </div>
      <Panel title="Mobile/PWA scope" icon={<CheckCircle2 size={18} />}>
        <Checklist items={mobileFeatures} />
        <div className="noteBox">
          Offline draft saving can wait until Phase 3. Photo upload queue is represented here so the final UX is clear.
        </div>
        <MiniFactGrid rows={mobileFieldStates} target="mobile-field-states" />
      </Panel>
    </div>
  );
}

function SecurityScreen() {
  return (
    <div className="screenStack">
      <section className="contentGrid two">
        {securityItems.map((item) => (
          <article className="decisionCard" key={item.label}>
            <span>{item.label}</span>
            <p>{item.detail}</p>
          </article>
        ))}
      </section>
      <Panel title="Compliance posture" icon={<ShieldCheck size={18} />}>
        <Checklist
          items={[
            "Downloads are logged",
            "Files use expiring/presigned URLs where suitable",
            "Backups encrypted off-server/cloud plus local DB backup",
            "Monthly restore testing",
            "Reports, documents, and photos retained permanently for active/completed projects",
          ]}
        />
      </Panel>
    </div>
  );
}

function DeliveryScreen() {
  return (
    <div className="screenStack">
      <section className="contentGrid three" data-tour-target="delivery-plan">
        {deliveryItems.map((item) => (
          <article className="featureCard" key={item.label}>
            <item.icon size={22} />
            <span>Recommended</span>
            <h3>{item.label}</h3>
            <p>{item.detail}</p>
          </article>
        ))}
      </section>
      <Panel title="Launch acceptance scenarios" icon={<CheckCircle2 size={18} />}>
        <Checklist
          items={[
            "Login and 2FA",
            "User creation",
            "Project creation",
            "Supervisor update",
            "Engineer report",
            "Approval and rejection",
            "Photo upload",
            "Document version upload",
            "Notification and export",
          ]}
        />
      </Panel>
      <Panel title="Sample import and launch attachments" icon={<Upload size={18} />}>
        <AttachmentList filter={["BOQ Import", "Supplier Compliance"]} />
      </Panel>
    </div>
  );
}

function Panel({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panelHeader">
        <div>{icon}</div>
        <h2>{title}</h2>
      </header>
      {children}
    </section>
  );
}

function MetricCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: string;
}) {
  return (
    <article className={`metricCard tone-${tone ?? "blue"}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </article>
  );
}

function DataTable({ columns, rows }: { columns: string[]; rows: ReactNode[][] }) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, index) => (
                <td key={index}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Checklist({ items }: { items: string[] }) {
  return (
    <ul className="checkList">
      {items.map((item) => (
        <li key={item}>
          <CheckCircle2 size={14} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function BarList({ rows }: { rows: { label: string; value: number; meta: string }[] }) {
  return (
    <div className="barList">
      {rows.map((row) => (
        <div key={row.label}>
          <div>
            <strong>{row.label}</strong>
            <span>{row.value}%</span>
          </div>
          <div className="barTrack">
            <span style={{ width: `${row.value}%` }} />
          </div>
          <small>{row.meta}</small>
        </div>
      ))}
    </div>
  );
}

function CardList({ rows }: { rows: { title: string; meta: string; badge: string }[] }) {
  return (
    <div className="cardList">
      {rows.map((row) => (
        <article key={row.title}>
          <div>
            <strong>{row.title}</strong>
            <span>{row.meta}</span>
          </div>
          <StatusPill status={row.badge} />
        </article>
      ))}
    </div>
  );
}

function WalkthroughTimeline() {
  return (
    <div className="walkthrough">
      {walkthroughSteps.map((item) => (
        <article key={item.step}>
          <span>{item.step}</span>
          <div>
            <strong>{item.title}</strong>
            <small>{item.screen}</small>
            <p>{item.detail}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

function AttachmentList({
  filter,
  compact = false,
}: {
  filter?: string[];
  compact?: boolean;
}) {
  const rows = filter
    ? sampleAttachments.filter((item) => filter.includes(item.type))
    : sampleAttachments;

  return (
    <div className={compact ? "attachmentList compact" : "attachmentList"}>
      {rows.map((item) => (
        <article key={item.name}>
          <FileText size={17} />
          <div>
            <strong>{item.name}</strong>
            <span>
              {item.type} • {item.owner} • {item.size}
            </span>
            <small>{item.linkedTo}</small>
          </div>
        </article>
      ))}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detailItem">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PackageIcon() {
  return <Upload size={18} />;
}

function RouteIcon() {
  return <ArrowRight size={18} />;
}

function SmartphoneIcon() {
  return <HardHat size={18} />;
}
