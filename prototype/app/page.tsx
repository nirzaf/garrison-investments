import {
  ArrowRight,
  Building2,
  CheckCircle2,
  CircleAlert,
  FileText,
  Gauge,
  Layers3,
  ListChecks,
  MoveRight,
  Sparkles,
} from "lucide-react";
import {
  decisionCards,
  dummyProjects,
  modules,
  navItems,
  openItems,
  reportFlow,
  roleCards,
} from "@/lib/portal-data";

const statusClass = {
  MVP: "statusMvp",
  "Phase 2": "statusPhase2",
  "Phase 3": "statusPhase3",
  Future: "statusFuture",
};

export default function Home() {
  return (
    <main className="portalShell">
      <aside className="sidebar" aria-label="Prototype navigation">
        <div className="brandMark">
          <Building2 size={28} />
          <div>
            <strong>Garrisons</strong>
            <span>Internal Portal</span>
          </div>
        </div>
        <nav className="sideNav">
          {navItems.map((item) => (
            <a href={`#${item.id}`} key={item.id}>
              <item.icon size={18} />
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="shipPanel">
          <span>Prototype Status</span>
          <strong>Requirements Visualized</strong>
          <p>Dummy operational data only</p>
        </div>
      </aside>

      <section className="content">
        <section className="hero" id="overview">
          <div className="heroCopy">
            <div className="eyebrow">
              <Sparkles size={16} />
              Animated requirements prototype
            </div>
            <h1>Final portal experience, explained through the real workflow.</h1>
            <p>
              This prototype turns the requirements into a visual operating model:
              who updates, who verifies, who approves, what launches first, and
              what remains for later phases.
            </p>
            <div className="heroActions">
              <a href="#flow" className="primaryAction">
                See report flow <ArrowRight size={18} />
              </a>
              <a href="#decisions" className="secondaryAction">
                Review decisions
              </a>
            </div>
          </div>
          <div className="heroBoard" aria-label="Live project summary mockup">
            <div className="boardHeader">
              <span>Today</span>
              <strong>Operations Pulse</strong>
            </div>
            <div className="pulseGrid">
              <Metric label="Pending approvals" value="12" tone="orange" />
              <Metric label="Late updates" value="3" tone="red" />
              <Metric label="Active projects" value="4" tone="blue" />
              <Metric label="Docs awaiting PM" value="8" tone="green" />
            </div>
            <div className="activityRail">
              <span />
              <p>Supervisor update received</p>
              <span />
              <p>Engineer verified quality</p>
              <span />
              <p>Project Manager approval pending</p>
            </div>
          </div>
        </section>

        <section className="section">
          <div className="sectionHeader">
            <div>
              <span className="sectionKicker">Launch map</span>
              <h2>What each module means for the final project</h2>
            </div>
            <p>
              The cards separate MVP essentials from later phases so stakeholders
              can understand the build order at a glance.
            </p>
          </div>
          <div className="moduleGrid">
            {modules.map((module, index) => (
              <article
                className={`moduleCard accent-${module.accent}`}
                key={module.title}
                style={{ animationDelay: `${index * 60}ms` }}
              >
                <div className="moduleIcon">
                  <module.icon size={22} />
                </div>
                <div className="moduleTop">
                  <h3>{module.title}</h3>
                  <span className={statusClass[module.status]}>{module.status}</span>
                </div>
                <p>{module.summary}</p>
                <strong>{module.metric}</strong>
              </article>
            ))}
          </div>
        </section>

        <section className="section flowSection" id="flow">
          <div className="sectionHeader">
            <div>
              <span className="sectionKicker">Primary workflow</span>
              <h2>Supervisor update to approved daily report</h2>
            </div>
            <p>
              The official report is produced by the Civil Engineer and becomes
              final only after Project Manager approval.
            </p>
          </div>
          <div className="flowLine">
            {reportFlow.map((step, index) => (
              <article className="flowStep" key={step.title}>
                <span className="stepNumber">{index + 1}</span>
                <small>{step.time}</small>
                <h3>{step.title}</h3>
                <strong>{step.owner}</strong>
                <p>{step.description}</p>
                {index < reportFlow.length - 1 ? <MoveRight className="stepArrow" /> : null}
              </article>
            ))}
          </div>
        </section>

        <section className="section splitSection">
          <div className="projectPanel">
            <div className="panelTitle">
              <Gauge size={20} />
              <h2>Dummy project dashboard</h2>
            </div>
            <div className="projectList">
              {dummyProjects.map((project) => (
                <article className="projectRow" key={project.code}>
                  <div>
                    <span>{project.code}</span>
                    <strong>{project.name}</strong>
                    <small>{project.phase} phase</small>
                  </div>
                  <div className="progressWrap">
                    <span>{project.progress}%</span>
                    <div className="progressTrack">
                      <div style={{ width: `${project.progress}%` }} />
                    </div>
                    <small>
                      {project.reports} reports / {project.delayed} delayed
                    </small>
                  </div>
                </article>
              ))}
            </div>
          </div>

          <div className="approvalPanel">
            <div className="panelTitle">
              <Layers3 size={20} />
              <h2>Approval routing</h2>
            </div>
            <div className="approvalStack">
              <Pill icon={<FileText size={16} />} text="Report: Supervisor -> Engineer -> PM" />
              <Pill icon={<ListChecks size={16} />} text="Material: Requester -> Engineer -> PM -> OM above $1k" />
              <Pill icon={<CheckCircle2 size={16} />} text="Documents: Uploader -> PM -> Active version" />
              <Pill icon={<CircleAlert size={16} />} text="Escalation: 24h reminder, 48h escalation" />
            </div>
          </div>
        </section>

        <section className="section" id="roles">
          <div className="sectionHeader">
            <div>
              <span className="sectionKicker">Role clarity</span>
              <h2>Who sees and does what</h2>
            </div>
            <p>
              MVP permissions stay role-based, while the data model remains ready
              for customizable permissions later.
            </p>
          </div>
          <div className="roleGrid">
            {roleCards.map((role) => (
              <article className="roleCard" key={role.role}>
                <h3>{role.role}</h3>
                <p>{role.scope}</p>
                <ul>
                  {role.canDo.map((item) => (
                    <li key={item}>
                      <CheckCircle2 size={15} />
                      {item}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        <section className="section decisionsSection" id="decisions">
          <div className="sectionHeader">
            <div>
              <span className="sectionKicker">Implementation decisions</span>
              <h2>Recommended answers baked into the prototype</h2>
            </div>
            <p>
              These are the defaults that reduce ambiguity before schema, API,
              and UI implementation begins.
            </p>
          </div>
          <div className="decisionGrid">
            {decisionCards.map((decision) => (
              <article className="decisionCard" key={decision.title}>
                <span>{decision.title}</span>
                <strong>{decision.value}</strong>
                <p>{decision.detail}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="section followUpSection">
          <div className="sectionHeader">
            <div>
              <span className="sectionKicker">Still needed</span>
              <h2>Remaining stakeholder inputs</h2>
            </div>
            <p>
              The prototype is ready to explain the system, but these inputs are
              still needed before production implementation.
            </p>
          </div>
          <div className="followUpList">
            {openItems.map((item) => (
              <div key={item}>
                <CircleAlert size={18} />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </section>
      </section>
    </main>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "orange" | "red" | "blue" | "green";
}) {
  return (
    <div className={`metric tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Pill({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="routePill">
      {icon}
      <span>{text}</span>
    </div>
  );
}
