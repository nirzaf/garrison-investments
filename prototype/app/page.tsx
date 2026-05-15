"use client";

import { useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  Bell,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  FileText,
  Filter,
  HardHat,
  ListChecks,
  LogOut,
  Menu,
  Plus,
  Search,
  ShieldCheck,
  Upload,
} from "lucide-react";
import {
  apiEndpoints,
  approvalItems,
  auditRows,
  deliveryItems,
  documents,
  financeCards,
  formSections,
  ganttTasks,
  invoices,
  kpis,
  launchModules,
  materialLifecycle,
  materials,
  mobileFeatures,
  navItems,
  notifications,
  photoCards,
  projects,
  remainingInputs,
  reportFlow,
  reportRows,
  roleMatrix,
  sampleAttachments,
  securityItems,
  suppliers,
  users,
  walkthroughSteps,
  type ScreenKey,
} from "@/lib/portal-data";

const screenTitles: Record<ScreenKey, string> = {
  overview: "Executive overview",
  auth: "Login, roles, and permission model",
  dashboard: "Operational dashboard",
  projects: "Projects and Gantt timeline",
  reports: "Daily reports and field update flow",
  approvals: "Approval inbox and routing",
  materials: "Materials, inventory, and suppliers",
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

  const activeNav = useMemo(
    () => navItems.find((item) => item.key === activeScreen),
    [activeScreen],
  );

  const selectScreen = (screen: ScreenKey) => {
    setActiveScreen(screen);
    setMobileNavOpen(false);
  };

  return (
    <main className="appShell">
      <aside className={`sideRail ${mobileNavOpen ? "isOpen" : ""}`} aria-label="Prototype modules">
        <div className="brandBlock">
          <div className="brandIcon">GI</div>
          <div>
            <strong>Garrisons</strong>
            <span>Internal Portal Prototype</span>
          </div>
        </div>

        <nav className="moduleNav">
          {navItems.map((item) => (
            <button
              className={item.key === activeScreen ? "isActive" : ""}
              key={item.key}
              onClick={() => selectScreen(item.key)}
              type="button"
            >
              <item.icon size={18} />
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
              <span>Search reports, docs, materials</span>
            </div>
            <button type="button">
              <Bell size={17} />
              17
            </button>
            <button type="button">
              <LogOut size={17} />
            </button>
          </div>
        </header>

        <section className="screenCard" key={activeScreen}>
          {activeScreen === "overview" ? <OverviewScreen onOpen={selectScreen} /> : null}
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

function OverviewScreen({ onOpen }: { onOpen: (screen: ScreenKey) => void }) {
  return (
    <div className="screenStack">
      <section className="heroPanel">
        <div>
          <span className="eyebrow">Animated full-feature prototype</span>
          <h2>See how the final portal will work before implementation starts.</h2>
          <p>
            This clickable prototype translates the technical docs, stakeholder answers, API
            specification, and UI component tree into a concrete product experience.
          </p>
          <div className="heroActions">
            <button onClick={() => onOpen("reports")} type="button">
              Walk daily report flow <ArrowRight size={18} />
            </button>
            <button className="ghostButton" onClick={() => onOpen("projects")} type="button">
              View project tracking
            </button>
          </div>
        </div>
        <div className="pulsePanel">
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
            <p>Supervisor update submitted</p>
            <span />
            <p>Engineer quality verification pending</p>
            <span />
            <p>Project Manager approval next</p>
          </div>
        </div>
      </section>

      <section className="contentGrid three">
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
        <Panel title="Guided end-to-end sample journey" icon={<ArrowRight size={19} />}>
          <WalkthroughTimeline />
        </Panel>
        <Panel title="Sample files used across the prototype" icon={<Upload size={19} />}>
          <AttachmentList compact />
        </Panel>
      </section>

      <section className="dualGrid">
        <Panel title="API surfaces represented" icon={<FileText size={19} />}>
          <div className="apiList">
            {apiEndpoints.map((endpoint) => (
              <code key={endpoint}>{endpoint}</code>
            ))}
          </div>
        </Panel>
        <Panel title="Remaining stakeholder inputs" icon={<AlertCircle size={19} />}>
          <Checklist items={remainingInputs} />
        </Panel>
      </section>
    </div>
  );
}

function AuthScreen() {
  return (
    <div className="screenStack">
      <div className="dualGrid">
        <Panel title="Login experience" icon={<ShieldCheck size={19} />}>
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
        <Panel title="Session and security decisions" icon={<CheckCircle2 size={19} />}>
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
      <div className="kpiGrid">
        {kpis.map((item) => (
          <MetricCard key={item.label} {...item} />
        ))}
      </div>
      <section className="dualGrid">
        <Panel title="Project progress chart" icon={<CircleDashed size={19} />}>
          <BarList
            rows={projects.map((project) => ({
              label: project.name,
              value: project.progress,
              meta: `${project.phase} • ${project.deadline}`,
            }))}
          />
        </Panel>
        <Panel title="Pending approvals widget" icon={<ShieldCheck size={19} />}>
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
      <div className="projectSelector">
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
        <Panel title={`${selectedProject.name} details`} icon={<HardHat size={19} />}>
          <div className="detailGrid">
            <Detail label="Location" value={selectedProject.location} />
            <Detail label="Manager" value={selectedProject.manager} />
            <Detail label="Deadline" value={selectedProject.deadline} />
            <Detail label="Budget" value={selectedProject.budget} />
            <Detail label="Reports" value={`${selectedProject.reports}`} />
            <Detail label="Delayed" value={`${selectedProject.delayed}`} />
          </div>
          <BarList
            rows={selectedProject.disciplines.map((item) => ({
              label: item.name,
              value: item.value,
              meta: "approved quantity / planned quantity",
            }))}
          />
        </Panel>
        <Panel title="BOQ and progress rules" icon={<ListChecks size={19} />}>
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
      <Panel title="Gantt-style timeline" icon={<CircleDashed size={19} />}>
        <div className="gantt">
          {ganttTasks.map((task) => (
            <div className="ganttRow" key={task.task}>
              <span>{task.task}</span>
              <div className="ganttTrack">
                <div style={{ marginLeft: `${task.start}%`, width: `${task.span}%` }}>
                  {task.status}
                </div>
              </div>
              <small>{task.owner}</small>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function ReportsScreen() {
  return (
    <div className="screenStack">
      <section className="flowGrid">
        {reportFlow.map((step, index) => (
          <article className="flowCard" key={step.title}>
            <span>{index + 1}</span>
            <small>{step.status}</small>
            <h3>{step.title}</h3>
            <strong>{step.owner}</strong>
            <p>{step.detail}</p>
          </article>
        ))}
      </section>
      <section className="dualGrid wideLeft">
        <Panel title="Daily report list" icon={<Filter size={19} />}>
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
        <Panel title="Report form sections" icon={<Plus size={19} />}>
          <Checklist items={formSections} />
        </Panel>
      </section>
      <Panel title="Sample report attachments" icon={<Upload size={19} />}>
        <AttachmentList filter={["Daily Report PDF", "Watermarked Photo", "WIR Document"]} />
      </Panel>
    </div>
  );
}

function ApprovalsScreen() {
  return (
    <div className="screenStack">
      <section className="contentGrid two">
        {approvalItems.map((item) => (
          <article className="approvalCard" key={item.title}>
            <span>{item.type}</span>
            <h3>{item.title}</h3>
            <p>{item.route}</p>
            <div>
              <strong>{item.sla}</strong>
              <em>{item.status}</em>
            </div>
            <div className="buttonRow">
              <button type="button">Approve</button>
              <button className="dangerButton" type="button">Reject with reason</button>
            </div>
          </article>
        ))}
      </section>
      <Panel title="Approval rules" icon={<ShieldCheck size={19} />}>
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
      <section className="dualGrid wideLeft">
        <Panel title="Inventory by location" icon={<PackageIcon />}>
          <DataTable
            columns={["Code", "Material", "Location", "Stock", "Min", "Status"]}
            rows={materials.map((item) => [
              item.code,
              item.name,
              item.location,
              `${item.stock} ${item.unit}`,
              `${item.min}`,
              item.status,
            ])}
          />
        </Panel>
        <Panel title="Request lifecycle" icon={<RouteIcon />}>
          <Checklist items={materialLifecycle} />
        </Panel>
      </section>
      <section className="dualGrid">
        <Panel title="Supplier management" icon={<Upload size={19} />}>
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
        <Panel title="Material rules" icon={<CheckCircle2 size={19} />}>
          <Checklist
            items={[
              "No negative stock",
              "Requests above USD 1,000 escalate to Operation Manager",
              "Unit conversion configured per material",
              "Transfers between warehouse, store, and project/site",
              "Pricing restricted to allowed finance/management roles",
            ]}
          />
        </Panel>
      </section>
      <Panel title="Sample material and supplier attachments" icon={<Upload size={19} />}>
        <AttachmentList filter={["Supplier Compliance", "BOQ Import"]} />
      </Panel>
    </div>
  );
}

function DocumentsScreen() {
  return (
    <div className="screenStack">
      <section className="toolbarMock">
        <button type="button"><Upload size={16} /> Upload document</button>
        <button type="button"><Search size={16} /> Search contents</button>
        <button type="button"><Filter size={16} /> Type/project filters</button>
      </section>
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
      <section className="dualGrid">
        <Panel title="Version control preview" icon={<FileText size={19} />}>
          <div className="versionStack">
            <div><strong>Rev C</strong><span>Pending PM approval</span></div>
            <div><strong>Rev B</strong><span>Active for field team</span></div>
            <div><strong>Rev A</strong><span>Superseded warning before view</span></div>
          </div>
        </Panel>
        <Panel title="Document decisions" icon={<CheckCircle2 size={19} />}>
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
      <Panel title="Sample controlled documents" icon={<Upload size={19} />}>
        <AttachmentList filter={["WIR Document", "BOQ Import", "Daily Report PDF"]} />
      </Panel>
    </div>
  );
}

function PhotosScreen() {
  return (
    <div className="screenStack">
      <section className="photoGrid">
        {photoCards.map((photo) => (
          <article className={`photoCard tone-${photo.tone}`} key={photo.label}>
            <div />
            <span>{photo.project}</span>
            <h3>{photo.label}</h3>
            <p>{photo.meta}</p>
          </article>
        ))}
      </section>
      <Panel title="Media handling rules" icon={<CameraIcon />}>
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
      <Panel title="Sample media attachment" icon={<Upload size={19} />}>
        <AttachmentList filter={["Watermarked Photo"]} />
      </Panel>
    </div>
  );
}

function AccountsScreen() {
  return (
    <div className="screenStack">
      <div className="kpiGrid compact">
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
      <Panel title="Finance requirements" icon={<CheckCircle2 size={19} />}>
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
      <Panel title="Sample finance attachment" icon={<Upload size={19} />}>
        <AttachmentList filter={["Invoice"]} />
      </Panel>
    </div>
  );
}

function NotificationsScreen() {
  return (
    <div className="screenStack">
      <section className="contentGrid two">
        {notifications.map((item) => (
          <article className="notificationCard" key={item.label}>
            <Bell size={19} />
            <h3>{item.label}</h3>
            <p>{item.target}</p>
            <strong>{item.timing}</strong>
          </article>
        ))}
      </section>
      <Panel title="Notification behavior" icon={<Bell size={19} />}>
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
      <section className="dualGrid">
        <Panel title="User management" icon={<Plus size={19} />}>
          <DataTable
            columns={["Name", "Role", "Status", "Last login"]}
            rows={users.map((user) => [user.name, user.role, user.status, user.last])}
          />
        </Panel>
        <Panel title="Audit log" icon={<FileText size={19} />}>
          <DataTable
            columns={["Event", "Actor", "Target"]}
            rows={auditRows.map((row) => [row.event, row.actor, row.target])}
          />
        </Panel>
      </section>
      <Panel title="Admin rules" icon={<ShieldCheck size={19} />}>
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
    </div>
  );
}

function MobileScreen() {
  return (
    <div className="dualGrid wideLeft">
      <Panel title="Mobile field app preview" icon={<SmartphoneIcon />}>
        <div className="phoneMock">
          <div className="phoneTop">Al Rayyan Villa Compound</div>
          <div className="phoneStep active">Supervisor update saved</div>
          <div className="phoneStep">5 photos queued</div>
          <div className="phoneStep">Engineer verification pending</div>
          <button type="button">Sync when online</button>
        </div>
      </Panel>
      <Panel title="Mobile/PWA scope" icon={<CheckCircle2 size={19} />}>
        <Checklist items={mobileFeatures} />
        <div className="noteBox">
          Offline draft saving can wait until Phase 3. Photo upload queue is represented here so the final UX is clear.
        </div>
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
      <Panel title="Compliance posture" icon={<ShieldCheck size={19} />}>
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
      <section className="contentGrid three">
        {deliveryItems.map((item) => (
          <article className="featureCard" key={item.label}>
            <item.icon size={22} />
            <span>Recommended</span>
            <h3>{item.label}</h3>
            <p>{item.detail}</p>
          </article>
        ))}
      </section>
      <Panel title="Launch acceptance scenarios" icon={<CheckCircle2 size={19} />}>
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
      <Panel title="Sample import and launch attachments" icon={<Upload size={19} />}>
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

function DataTable({ columns, rows }: { columns: string[]; rows: string[][] }) {
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
          {rows.map((row) => (
            <tr key={row.join("-")}>
              {row.map((cell, index) => (
                <td key={`${cell}-${index}`}>{cell}</td>
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
          <CheckCircle2 size={15} />
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
          <em>{row.badge}</em>
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
          <FileText size={18} />
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
  return <Upload size={19} />;
}

function RouteIcon() {
  return <ArrowRight size={19} />;
}

function CameraIcon() {
  return <Upload size={19} />;
}

function SmartphoneIcon() {
  return <ShieldCheck size={19} />;
}
