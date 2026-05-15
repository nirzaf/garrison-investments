import {
  Archive,
  Bell,
  BookOpenCheck,
  BriefcaseBusiness,
  CalendarClock,
  Camera,
  ClipboardCheck,
  Cloud,
  Database,
  FileStack,
  Gauge,
  HardHat,
  KeyRound,
  Layers3,
  ListChecks,
  PackageCheck,
  Route,
  ShieldCheck,
  Smartphone,
  Truck,
  UsersRound,
  WalletCards,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type ScreenKey =
  | "overview"
  | "auth"
  | "dashboard"
  | "projects"
  | "reports"
  | "approvals"
  | "materials"
  | "documents"
  | "photos"
  | "accounts"
  | "notifications"
  | "admin"
  | "mobile"
  | "security"
  | "delivery";

export type PortalNavItem = {
  key: ScreenKey;
  label: string;
  icon: LucideIcon;
  phase: "MVP" | "Phase 2" | "Phase 3" | "Ops";
};

export type GuidedTourStep = {
  label: string;
  screen: ScreenKey;
  persona: string;
  trigger: string;
  outcome: string;
};

export type ProductTourStep = {
  title: string;
  screen: ScreenKey;
  target: string;
  eyebrow: string;
  body: string;
  instruction: string;
  position?: "top" | "right" | "bottom" | "left";
};

export type FeatureGuide = {
  owner: string;
  startsWhen: string;
  userAction: string;
  systemAction: string;
  businessResult: string;
};

export type RequirementCoverage = {
  module: string;
  phase: PortalNavItem["phase"];
  screen: ScreenKey;
  source: string;
  covered: string;
  finalBehavior: string;
};

export const navItems: PortalNavItem[] = [
  { key: "overview", label: "Overview", icon: Gauge, phase: "MVP" },
  { key: "auth", label: "Login & Roles", icon: KeyRound, phase: "MVP" },
  { key: "dashboard", label: "Dashboard", icon: Layers3, phase: "MVP" },
  { key: "projects", label: "Projects", icon: BriefcaseBusiness, phase: "MVP" },
  { key: "reports", label: "Daily Reports", icon: ClipboardCheck, phase: "MVP" },
  { key: "approvals", label: "Approvals", icon: ShieldCheck, phase: "MVP" },
  { key: "materials", label: "Materials", icon: PackageCheck, phase: "Phase 2" },
  { key: "documents", label: "Documents", icon: FileStack, phase: "MVP" },
  { key: "photos", label: "Photos", icon: Camera, phase: "MVP" },
  { key: "accounts", label: "Accounts", icon: WalletCards, phase: "Phase 2" },
  { key: "notifications", label: "Notifications", icon: Bell, phase: "MVP" },
  { key: "admin", label: "Admin", icon: UsersRound, phase: "MVP" },
  { key: "mobile", label: "Mobile/PWA", icon: Smartphone, phase: "Phase 3" },
  { key: "security", label: "Security", icon: ShieldCheck, phase: "MVP" },
  { key: "delivery", label: "Delivery Plan", icon: Cloud, phase: "Ops" },
];

export const kpis = [
  { label: "Active projects", value: "4", detail: "company-wide", tone: "blue" },
  { label: "Pending approvals", value: "12", detail: "8 due today", tone: "orange" },
  { label: "Late updates", value: "3", detail: "PM notified", tone: "red" },
  { label: "Documents pending", value: "8", detail: "MAR/MIR/WIR", tone: "green" },
  { label: "Low stock", value: "5", detail: "2 critical", tone: "purple" },
  { label: "Unread alerts", value: "17", detail: "90-day history", tone: "teal" },
];

export const launchModules = [
  {
    title: "Task/report updates",
    phase: "MVP",
    summary: "Supervisor field updates, engineer verification, PM final approval.",
    icon: ClipboardCheck,
  },
  {
    title: "Documents/versioning",
    phase: "MVP",
    summary: "MAR, MIR, WIR, delivery notes, active versions, superseded warnings.",
    icon: FileStack,
  },
  {
    title: "Photo evidence",
    phase: "MVP",
    summary: "5 photos/report, compression, thumbnails, company watermark.",
    icon: Camera,
  },
  {
    title: "Materials workflow",
    phase: "Phase 2",
    summary: "Requests, reservations, multi-location stock, transfers, low stock.",
    icon: PackageCheck,
  },
  {
    title: "Accounts",
    phase: "Phase 2",
    summary: "Budgets, invoices, manpower cost, payment status, P&L, salary sheets.",
    icon: WalletCards,
  },
  {
    title: "Offline PWA",
    phase: "Phase 3",
    summary: "Offline drafts, photo queue, autosave, H+ tolerant mobile flows.",
    icon: Smartphone,
  },
];

export const investorHighlights = [
  {
    label: "Reporting speed",
    value: "Same-day control",
    detail: "Site updates become engineer-verified reports, approval tasks, PDFs, and management KPIs.",
  },
  {
    label: "Approval discipline",
    value: "No silent work",
    detail: "Every report, material request, document, invoice, payment, and change has a visible route.",
  },
  {
    label: "Document trust",
    value: "Active version only",
    detail: "Field staff see the approved version while managers keep revision history and superseded warnings.",
  },
  {
    label: "Cost visibility",
    value: "Project-level finance",
    detail: "Manpower, material consumption, supplier invoices, payments, and P&L connect to field activity.",
  },
  {
    label: "Mobile adoption",
    value: "Built for site teams",
    detail: "Phone-first updates, autosave, photo queue, and offline drafts make the process practical on site.",
  },
];

export const painPointComparisons = [
  {
    area: "Daily site updates",
    before: "Supervisors share WhatsApp photos and notes that managers manually chase later.",
    after: "A guided report captures attendance, OT, materials, safety, WIR, delays, photos, and attachments.",
    impact: "Fewer missing reports, faster PM approval, and a reliable contractual record.",
  },
  {
    area: "Approvals",
    before: "Approvals sit in chat threads or email inboxes with unclear ownership and no SLA.",
    after: "The portal assigns approvers by role/project, tracks SLA, reminds at 24h, and escalates at 48h.",
    impact: "Decisions are visible, reject reasons are retained, and overrides are audited.",
  },
  {
    area: "Documents",
    before: "Drawings, WIRs, MIRs, delivery notes, and invoices live in folders with version confusion.",
    after: "Each document has metadata, approval status, revision history, active/superseded state, and search.",
    impact: "Field teams stop using outdated files while management keeps complete history.",
  },
  {
    area: "Materials and cost",
    before: "Stock, requests, supplier terms, consumption, invoices, and budgets are split across spreadsheets.",
    after: "Materials move through request, approval, reserve, issue, transaction, and finance visibility.",
    impact: "Low stock, over-budget work, and payment exposure become visible earlier.",
  },
];

export const requirementCoverage: RequirementCoverage[] = [
  {
    module: "Authentication and RBAC",
    phase: "MVP",
    screen: "auth",
    source: "Technical spec, API auth, UI login",
    covered: "Login mock, 2FA, first-login decisions, role matrix, session/security rules.",
    finalBehavior: "JWT auth, refresh rotation, fixed MVP roles, protected routes, audit middleware.",
  },
  {
    module: "Projects and BOQ",
    phase: "MVP",
    screen: "projects",
    source: "WBS 1.3, API projects, UI routes",
    covered: "Project selector, budget/deadline/progress cards, BOQ fields, discipline progress, Gantt.",
    finalBehavior: "Project CRUD, project members, BOQ import/manual entry, milestones, weighted progress.",
  },
  {
    module: "Daily reports",
    phase: "MVP",
    screen: "reports",
    source: "WBS 1.4, API reports, database schema",
    covered: "Supervisor -> engineer -> PM workflow, report list, required form sections, attachments.",
    finalBehavior: "Draft/update/submit/approve/reject reports with manpower, equipment, materials, photos, PDF export.",
  },
  {
    module: "Photo evidence",
    phase: "MVP",
    screen: "photos",
    source: "WBS 1.5, API photos, database photos",
    covered: "5-photo rule, watermark, thumbnail/display/original handling, offline queue, recoverable delete.",
    finalBehavior: "Multipart upload to object storage, thumbnail generation, metadata, download and soft delete.",
  },
  {
    module: "Dashboard and analytics",
    phase: "MVP",
    screen: "dashboard",
    source: "WBS 1.6, API dashboard",
    covered: "Operational KPIs, project progress chart, approval widget, live risk story.",
    finalBehavior: "Role-scoped summaries, recent activity, project progress, material usage, approval stats.",
  },
  {
    module: "Materials and suppliers",
    phase: "Phase 2",
    screen: "materials",
    source: "WBS 2.1, API materials/suppliers",
    covered: "Inventory by location, request lifecycle, supplier terms, low-stock and pricing rules.",
    finalBehavior: "CRUD, stock transactions, reservations, transfers, reorder alerts, supplier management.",
  },
  {
    module: "Approval workflow",
    phase: "Phase 2",
    screen: "approvals",
    source: "WBS 2.2, API approvals",
    covered: "Approval inbox cards for reports, materials, documents, invoices, SLA and reject actions.",
    finalBehavior: "Generic multi-level approval engine with delegation, comments, escalation, and audit trail.",
  },
  {
    module: "Notifications",
    phase: "MVP",
    screen: "notifications",
    source: "WBS 2.3, API notifications",
    covered: "In-app/email triggers, unread count, 90-day history, mute behavior, audit separation.",
    finalBehavior: "Notification API, unread count, mark read, email tasks for approvals, late reports, low stock.",
  },
  {
    module: "Document control",
    phase: "MVP",
    screen: "documents",
    source: "WBS 2.4, API documents, UI library",
    covered: "Upload/search/filter toolbar, document list, version preview, active/superseded decision rules.",
    finalBehavior: "Upload/download, metadata, full-text search, version history, active status after approval.",
  },
  {
    module: "Accounts and finance",
    phase: "Phase 2",
    screen: "accounts",
    source: "WBS 3.1, export API, requirements",
    covered: "Budget-vs-actual, manpower cost, pending payment, invoices, P&L and approval path.",
    finalBehavior: "Invoice tracking, payment status, manpower/material cost, budget reports, project P&L.",
  },
  {
    module: "Mobile/PWA field use",
    phase: "Phase 3",
    screen: "mobile",
    source: "Technical spec offline-first, WBS 3.3",
    covered: "Phone mock, offline draft, photo queue, sync, autosave, document view scope.",
    finalBehavior: "Service worker, IndexedDB drafts, background sync, camera capture, optimistic UI.",
  },
  {
    module: "Security and audit",
    phase: "MVP",
    screen: "security",
    source: "Technical security, database activity_log",
    covered: "2FA, session, lockout, blocked files, retention, downloads, encrypted backups.",
    finalBehavior: "Secure headers, RBAC, rate limiting, type whitelist, audit log, recovery windows.",
  },
  {
    module: "Delivery and migration",
    phase: "Ops",
    screen: "delivery",
    source: "Technical deployment, WBS launch tasks",
    covered: "Hosting, staging/production, deployment approval, backups, testing, migration imports.",
    finalBehavior: "Docker/VPS MVP, GitHub Actions, restore tests, browser/device QA, launch data import.",
  },
];

export const dashboardPanels = [
  { label: "Missing reports", value: "3", detail: "submitter notified, PM next", tone: "red" },
  { label: "Manpower today", value: "186", detail: "across active sites", tone: "blue" },
  { label: "Approval SLA", value: "82%", detail: "closed within target", tone: "green" },
  { label: "Low stock exposure", value: "QAR 64k", detail: "materials below reorder point", tone: "orange" },
];

export const businessFlow = [
  {
    title: "1. Project baseline",
    screen: "Projects",
    owner: "Admin / Operation Manager",
    detail: "Create project code, BOQ, milestones, members, and target dates.",
  },
  {
    title: "2. Site update",
    screen: "Daily Reports",
    owner: "Civil Supervisor",
    detail: "Capture attendance, overtime, location, progress, safety, materials, and photos.",
  },
  {
    title: "3. Technical verification",
    screen: "Daily Reports",
    owner: "Civil Engineer",
    detail: "Validate work quality, WIR status, quantities, blockers, and next-day plan.",
  },
  {
    title: "4. Approval control",
    screen: "Approvals",
    owner: "Project Manager",
    detail: "Approve, reject with reason, or trigger escalation based on role and SLA.",
  },
  {
    title: "5. Company record",
    screen: "Dashboard",
    owner: "System",
    detail: "Update KPIs, generate PDF, email stakeholders, log audit trail, and refresh documents/costs.",
  },
];

export const guidedTourSteps: GuidedTourStep[] = [
  {
    label: "Investor snapshot",
    screen: "overview",
    persona: "Investor / General Manager",
    trigger: "Open the product for the first time",
    outcome: "Understand the market problem, product scope, and rollout plan in under one minute.",
  },
  {
    label: "Secure onboarding",
    screen: "auth",
    persona: "Admin",
    trigger: "Create users and send first-login access",
    outcome: "Each employee enters through role-based access, 2FA, and audit-friendly sessions.",
  },
  {
    label: "Project setup",
    screen: "projects",
    persona: "Operation Manager",
    trigger: "A new construction job is awarded",
    outcome: "The portal creates one source of truth for BOQ, phases, deadlines, team members, and progress.",
  },
  {
    label: "Daily field capture",
    screen: "reports",
    persona: "Supervisor and Civil Engineer",
    trigger: "Work is completed on site today",
    outcome: "Supervisor input becomes an engineer-verified official report with photos and attachments.",
  },
  {
    label: "Management approval",
    screen: "approvals",
    persona: "Project Manager",
    trigger: "A report, document, material request, or invoice needs sign-off",
    outcome: "Approvals move through the right chain with comments, reminders, escalation, and audit records.",
  },
  {
    label: "Controls at scale",
    screen: "materials",
    persona: "Store Keeper / Accounts / Manager",
    trigger: "Stock, supplier, or cost decisions affect a project",
    outcome: "Materials, suppliers, invoices, and budgets become governed workflows instead of spreadsheets.",
  },
  {
    label: "Mobile execution",
    screen: "mobile",
    persona: "Field team",
    trigger: "Users work from site on low bandwidth",
    outcome: "A PWA-friendly flow keeps drafts, photos, approvals, and notifications usable on phones.",
  },
  {
    label: "Launch path",
    screen: "delivery",
    persona: "Delivery team",
    trigger: "Stakeholders approve build funding",
    outcome: "The team has an MVP scope, acceptance scenarios, migration inputs, and deployment model.",
  },
];

export const productTourSteps: ProductTourStep[] = [
  {
    title: "Start with the investor story",
    screen: "overview",
    target: "hero-overview",
    eyebrow: "Welcome tour",
    body: "This opening view explains the final product in plain business language before the viewer studies any module.",
    instruction: "Use this screen to frame the portal as one operating system for construction reporting, approvals, documents, materials, finance, and mobile work.",
    position: "right",
  },
  {
    title: "Read the operations pulse",
    screen: "overview",
    target: "operations-pulse",
    eyebrow: "Executive summary",
    body: "The pulse card shows the kind of live management view investors expect from an enterprise SaaS product.",
    instruction: "Point out that approved field activity immediately updates KPIs, pending approvals, late updates, and document risk.",
    position: "left",
  },
  {
    title: "Show the business problem",
    screen: "overview",
    target: "before-after",
    eyebrow: "Why it matters",
    body: "The proposal explains what the company is replacing: chat follow-ups, spreadsheet tracking, unclear approvals, and document confusion.",
    instruction: "Use this section to make non-technical viewers feel the pain before showing the product solution.",
    position: "top",
  },
  {
    title: "Prove executive value",
    screen: "overview",
    target: "executive-value",
    eyebrow: "Investor value",
    body: "The value cards translate features into measurable operating outcomes: speed, control, trust, cost, and field adoption.",
    instruction: "Frame the product as a management operating layer, not only a reporting app.",
    position: "top",
  },
  {
    title: "Follow the business flow",
    screen: "overview",
    target: "business-flow",
    eyebrow: "End-to-end workflow",
    body: "This map connects project setup, field update, engineer verification, approval, and final business record.",
    instruction: "Walk stakeholders through this first so every later feature feels connected to the operating flow.",
    position: "top",
  },
  {
    title: "Confirm requirements coverage",
    screen: "overview",
    target: "coverage-matrix",
    eyebrow: "Docs-backed coverage",
    body: "Every documented module is mapped to prototype coverage and final-product behavior so stakeholders can see nothing important is missing.",
    instruction: "Use this when technical and non-technical reviewers ask whether the prototype reflects the documentation.",
    position: "top",
  },
  {
    title: "Secure first login",
    screen: "auth",
    target: "auth-login",
    eyebrow: "Onboarding",
    body: "New users enter through a controlled sign-in flow with email, password, and 2FA for the MVP.",
    instruction: "Explain that Admin creates users, sends access, and the first login requires secure completion before role-based access opens.",
    position: "right",
  },
  {
    title: "Show role-based permissions",
    screen: "auth",
    target: "feature-guide",
    eyebrow: "Access control",
    body: "Every feature screen now starts with owner, trigger, user action, system action, and business result.",
    instruction: "Use this guide to explain how each module works without making investors read technical documentation.",
    position: "bottom",
  },
  {
    title: "Track operational KPIs",
    screen: "dashboard",
    target: "dashboard-kpis",
    eyebrow: "Dashboard",
    body: "The dashboard summarizes active projects, pending approvals, late updates, documents, low stock, and unread alerts.",
    instruction: "Highlight that managers get live risk signals instead of waiting for spreadsheets or chat updates.",
    position: "bottom",
  },
  {
    title: "Review project progress",
    screen: "projects",
    target: "project-selector",
    eyebrow: "Project control",
    body: "Project cards let managers switch between jobs and inspect progress, budget, deadlines, delayed reports, and discipline progress.",
    instruction: "Click a project to show how the prototype changes the detail panel while keeping the same workflow structure.",
    position: "bottom",
  },
  {
    title: "Create the project baseline",
    screen: "projects",
    target: "project-setup-preview",
    eyebrow: "Project setup",
    body: "The final product starts each job with project code, BOQ import/manual entry, milestones, members, deadlines, and progress rules.",
    instruction: "Explain that all later reports, WIRs, costs, documents, and approvals connect back to this baseline.",
    position: "top",
  },
  {
    title: "Explain BOQ and Gantt logic",
    screen: "projects",
    target: "gantt-timeline",
    eyebrow: "Timeline",
    body: "The Gantt-style timeline previews phase planning, owners, progress status, and delay visibility.",
    instruction: "Connect this to the BOQ baseline and approved quantities that drive real project progress later.",
    position: "top",
  },
  {
    title: "Walk the daily report chain",
    screen: "reports",
    target: "report-flow",
    eyebrow: "Core workflow",
    body: "Supervisor updates become engineer-verified daily reports, then move to PM approval and automated PDF/email/archive.",
    instruction: "This is the most important MVP story: field data becomes an official company record.",
    position: "bottom",
  },
  {
    title: "Show required report inputs",
    screen: "reports",
    target: "report-form-preview",
    eyebrow: "Form guidance",
    body: "The report form guides users through mandatory operational sections such as manpower, equipment, materials, safety, WIR, delays, photos, and attachments.",
    instruction: "Explain that this standardizes reporting and prevents incomplete daily records.",
    position: "left",
  },
  {
    title: "Show report outcomes",
    screen: "reports",
    target: "report-outcomes",
    eyebrow: "Business record",
    body: "A completed report does more than save a form: it updates approval tasks, PDF/email export, audit, dashboard, and archive.",
    instruction: "This is the investor-grade story: the product turns field work into management evidence.",
    position: "top",
  },
  {
    title: "Manage approval decisions",
    screen: "approvals",
    target: "approval-cards",
    eyebrow: "Approval inbox",
    body: "Approvers see report, material, document, and invoice requests with route, SLA, status, and action buttons.",
    instruction: "Call out reject-with-reason, reminders, escalation, delegation, and audit trail as the management-control layer.",
    position: "bottom",
  },
  {
    title: "Control stock and suppliers",
    screen: "materials",
    target: "materials-inventory",
    eyebrow: "Supply chain",
    body: "Inventory is shown by material, location, stock, minimum threshold, and status, with supplier and lifecycle context nearby.",
    instruction: "Use this to show how Phase 2 turns material requests and stock movement into traceable workflow.",
    position: "right",
  },
  {
    title: "Follow material movement",
    screen: "materials",
    target: "material-flow",
    eyebrow: "Material workflow",
    body: "Requests move through review, approval, reservation, issue, transfer, consumption, return, or adjustment with stock protection.",
    instruction: "Connect this directly to low-stock risk and cost visibility.",
    position: "top",
  },
  {
    title: "Handle controlled documents",
    screen: "documents",
    target: "documents-table",
    eyebrow: "Document control",
    body: "Documents include type, project, revision, approval status, active/superseded versioning, and searchable metadata.",
    instruction: "Explain that field teams use active documents while managers retain version history and approval evidence.",
    position: "top",
  },
  {
    title: "Preview document governance",
    screen: "documents",
    target: "document-flow",
    eyebrow: "Version control",
    body: "The prototype explains upload, review, active release, superseded warnings, and expiry reminders.",
    instruction: "Use this to reassure stakeholders that document control is not just file upload.",
    position: "top",
  },
  {
    title: "Capture photo evidence",
    screen: "photos",
    target: "photo-grid",
    eyebrow: "Media evidence",
    body: "Photos are limited, compressed, watermarked, queued for offline upload, and recoverable by Admin.",
    instruction: "Connect photo evidence back to the daily report and audit-ready project record.",
    position: "bottom",
  },
  {
    title: "Preview financial control",
    screen: "accounts",
    target: "finance-kpis",
    eyebrow: "Accounts",
    body: "Finance previews budget-vs-actual, manpower cost, pending payment, invoices, payment status, and project P&L.",
    instruction: "Position this as Phase 2/3 value: cost visibility becomes connected to reports, materials, documents, and approvals.",
    position: "bottom",
  },
  {
    title: "Trace invoice to P&L",
    screen: "accounts",
    target: "finance-workflow",
    eyebrow: "Financial workflow",
    body: "Invoices move from capture to accounts check, Operation Manager approval, payment status, and project cost rollup.",
    instruction: "This gives investors the finance expansion path without pretending OCR or full accounting is in the MVP.",
    position: "top",
  },
  {
    title: "Explain alerts and reminders",
    screen: "notifications",
    target: "notification-cards",
    eyebrow: "Notifications",
    body: "Notifications drive action for pending approvals, late reports, low stock, and active document updates.",
    instruction: "Show that the product actively moves work forward instead of depending on manual follow-up.",
    position: "bottom",
  },
  {
    title: "Govern users and audit logs",
    screen: "admin",
    target: "admin-grid",
    eyebrow: "Administration",
    body: "Admin can manage users and inspect audit logs while approved reports and historical identities remain protected.",
    instruction: "Explain the governance model: deactivate users, preserve records, audit overrides, and avoid silent edits.",
    position: "bottom",
  },
  {
    title: "Show governance controls",
    screen: "admin",
    target: "admin-security-controls",
    eyebrow: "Audit and control",
    body: "The portal preserves identity history, controls overrides, and keeps queryable audit evidence for sensitive actions.",
    instruction: "This is where technical reviewers see the product has real enterprise governance thinking.",
    position: "top",
  },
  {
    title: "Show the field mobile flow",
    screen: "mobile",
    target: "phone-preview",
    eyebrow: "Mobile/PWA",
    body: "The phone preview shows site users saving updates, queueing photos, and syncing when the connection allows.",
    instruction: "Use this to make the end product feel practical for construction sites, not only desktop offices.",
    position: "right",
  },
  {
    title: "Explain offline execution",
    screen: "mobile",
    target: "mobile-field-states",
    eyebrow: "Offline field work",
    body: "Mobile behavior covers offline drafts, camera capture, photo queue, sync, autosave, approvals, and active document view.",
    instruction: "Close the adoption concern: the people on site can actually use it.",
    position: "top",
  },
  {
    title: "Close with delivery confidence",
    screen: "delivery",
    target: "delivery-plan",
    eyebrow: "Launch path",
    body: "Delivery cards show hosting, environments, deployment, backups, testing, migration, and acceptance scenarios.",
    instruction: "End here so investors understand the prototype maps directly to implementation scope and launch readiness.",
    position: "bottom",
  },
];

export const featureGuides: Record<ScreenKey, FeatureGuide> = {
  overview: {
    owner: "Investor, founder, and delivery sponsor",
    startsWhen: "A stakeholder opens the prototype before funding or build approval.",
    userAction: "Start the guided tour or jump into any module from the side navigation.",
    systemAction: "Surfaces the core workflow, phase scope, sample data, API surfaces, and open inputs.",
    businessResult: "Everyone can picture the final SaaS product before engineering starts.",
  },
  auth: {
    owner: "Admin",
    startsWhen: "A new employee, manager, store keeper, or accounts user needs portal access.",
    userAction: "Admin creates the account, assigns one role, and the user completes secure first login.",
    systemAction: "Applies RBAC, token/session rules, lockout, first-login password change, and audit logging.",
    businessResult: "Access is controlled by role without breaking historical records when employees change.",
  },
  dashboard: {
    owner: "General Manager, Operation Manager, Project Manager",
    startsWhen: "Management needs a company-wide operations pulse.",
    userAction: "Filter active projects, delayed reports, approvals, documents, stock, and alerts.",
    systemAction: "Refreshes role-scoped operational summaries every few minutes.",
    businessResult: "Leadership sees risk early instead of waiting for manual WhatsApp or spreadsheet updates.",
  },
  projects: {
    owner: "Operation Manager / Project Manager",
    startsWhen: "A project is created or progress needs to be reviewed.",
    userAction: "Enter BOQ, milestones, phases, activities, team members, deadlines, and progress updates.",
    systemAction: "Calculates progress from approved quantities, discipline progress, WIRs, and timeline status.",
    businessResult: "Project tracking becomes standardized and comparable across the company.",
  },
  reports: {
    owner: "Civil Supervisor / Civil Engineer",
    startsWhen: "Daily site work is ready to be recorded.",
    userAction: "Supervisor saves field inputs; engineer verifies, adds official report details, and submits.",
    systemAction: "Validates mandatory fields, attaches photos/docs, numbers the report, and routes approval.",
    businessResult: "The daily report becomes a reliable operational and contractual record.",
  },
  approvals: {
    owner: "Project Manager / Operation Manager / Admin",
    startsWhen: "A report, document, material request, invoice, payment, or scope change needs sign-off.",
    userAction: "Approve, reject with reason, delegate, or escalate according to role and SLA.",
    systemAction: "Finds the approver automatically, sends reminders, locks approved records, and audits overrides.",
    businessResult: "Management controls risk without slowing field execution.",
  },
  materials: {
    owner: "Store Keeper / Project Manager / Operation Manager",
    startsWhen: "A team requests, reserves, issues, transfers, or consumes material.",
    userAction: "Create requests, manage stock by location, record supplier details, and process movements.",
    systemAction: "Prevents negative stock, flags low stock, reserves approved quantities, and restricts pricing.",
    businessResult: "Inventory movement is traceable from supplier to project consumption.",
  },
  documents: {
    owner: "Civil Engineer / Project Manager",
    startsWhen: "A MAR, MIR, WIR, drawing, delivery note, BOQ, contract, or invoice is uploaded.",
    userAction: "Upload metadata, route approval, preview active documents, and review version history.",
    systemAction: "Maintains revisions, superseded warnings, search, expiry reminders, and active-version control.",
    businessResult: "Field teams use the right document while managers retain history and approvals.",
  },
  photos: {
    owner: "Civil Supervisor",
    startsWhen: "Photo evidence is attached to daily work.",
    userAction: "Capture up to five report photos or attach approved evidence from the gallery.",
    systemAction: "Stores original, display image, thumbnail, watermark, metadata, and recoverable deletes.",
    businessResult: "Visual proof is searchable, controlled, and linked to reports instead of scattered in chats.",
  },
  accounts: {
    owner: "Accounts / Operation Manager",
    startsWhen: "Costs, invoices, payments, salaries, and project budgets need review.",
    userAction: "Enter invoices, validate costs, track status, and prepare payment approvals.",
    systemAction: "Connects financial documents to projects, approvals, manpower, material cost, and P&L views.",
    businessResult: "Finance can see project-level cost exposure before budget overruns become invisible.",
  },
  notifications: {
    owner: "Every role",
    startsWhen: "A pending action, rejection, approval, low stock item, or late report occurs.",
    userAction: "Open alerts, act on assigned work, mute non-critical items, and review history.",
    systemAction: "Sends in-app/email notifications, tracks unread counts, and keeps audit records separately.",
    businessResult: "The business flow keeps moving without depending on manual reminders.",
  },
  admin: {
    owner: "Admin",
    startsWhen: "Users, permissions, overrides, or audit inspection are needed.",
    userAction: "Create/deactivate users, review logs, delegate unavailable approvers, and record override reasons.",
    systemAction: "Preserves old identities, blocks edits to approved reports, and records sensitive actions.",
    businessResult: "The company gets governance without losing accountability.",
  },
  mobile: {
    owner: "Supervisor / Engineer / Approver",
    startsWhen: "A site user works on a phone or low-speed network.",
    userAction: "Save drafts, upload photos, view documents, and approve from a compact field flow.",
    systemAction: "Autosaves, queues uploads, syncs when online, and keeps reference screens usable.",
    businessResult: "The product remains practical for construction sites, not only office desktops.",
  },
  security: {
    owner: "Admin / Delivery owner",
    startsWhen: "The portal handles reports, documents, finance, and employee data.",
    userAction: "Configure retention, blocked file types, recovery windows, backups, and download controls.",
    systemAction: "Uses audit logs, expiring URLs, encrypted backups, lockout, and role-scoped access.",
    businessResult: "The system is built for operational trust from the first release.",
  },
  delivery: {
    owner: "Product and engineering delivery team",
    startsWhen: "Stakeholders approve the build after prototype review.",
    userAction: "Confirm MVP scope, source data, hosting owner, acceptance scenarios, and migration inputs.",
    systemAction: "Guides staging, production approval, backups, restore testing, browser/device QA, and launch import.",
    businessResult: "The prototype translates directly into a funded delivery plan.",
  },
};

export const roleMatrix = [
  {
    role: "General Manager",
    access: "Executive visibility",
    permissions: ["Company-wide dashboard", "Escalation view", "Scope-change approval"],
  },
  {
    role: "Operation Manager",
    access: "Operations control",
    permissions: ["Escalated report review", "Invoices/payments approval", ">$1k material approval"],
  },
  {
    role: "Project Manager",
    access: "All projects now, project-wise later",
    permissions: ["Approve reports", "Approve active documents", "Review WIR progress"],
  },
  {
    role: "Civil Engineer",
    access: "Official reporting",
    permissions: ["Verify supervisor update", "Submit official report", "Upload docs"],
  },
  {
    role: "Civil Supervisor",
    access: "Field updates",
    permissions: ["Attendance", "Work location", "Overtime", "Photos", "Progress input"],
  },
  {
    role: "Store Keeper",
    access: "Materials only",
    permissions: ["Inventory screens", "Stock movement", "Supplier records"],
  },
  {
    role: "Accounts",
    access: "All financial/project data",
    permissions: ["Invoices", "Budgets", "Manpower cost", "P&L", "Salary sheets"],
  },
  {
    role: "Admin",
    access: "Configuration and audit",
    permissions: ["Users", "Permissions later", "Audit logs", "Override with reason"],
  },
];

export const projects = [
  {
    code: "GIP-2401",
    name: "Al Rayyan Villa Compound",
    location: "Al Rayyan",
    phase: "Finishing",
    manager: "N. Rahman",
    progress: 68,
    budget: "QAR 4.8M",
    deadline: "2026-07-30",
    reports: 18,
    delayed: 2,
    disciplines: [
      { name: "Civil", value: 82 },
      { name: "MEP", value: 57 },
      { name: "Finishing", value: 44 },
    ],
  },
  {
    code: "GIP-2402",
    name: "Industrial Store Extension",
    location: "Industrial Area",
    phase: "MEP",
    manager: "S. Kumar",
    progress: 42,
    budget: "QAR 2.1M",
    deadline: "2026-08-15",
    reports: 11,
    delayed: 1,
    disciplines: [
      { name: "Civil", value: 65 },
      { name: "MEP", value: 34 },
      { name: "Finishing", value: 12 },
    ],
  },
  {
    code: "GIP-2403",
    name: "Doha Office Fit-Out",
    location: "West Bay",
    phase: "Civil",
    manager: "A. Hassan",
    progress: 81,
    budget: "QAR 1.6M",
    deadline: "2026-06-12",
    reports: 27,
    delayed: 0,
    disciplines: [
      { name: "Civil", value: 91 },
      { name: "MEP", value: 79 },
      { name: "Finishing", value: 66 },
    ],
  },
];

export const ganttTasks = [
  { task: "BOQ baseline", owner: "PM", start: 5, span: 12, status: "Done" },
  { task: "Civil works", owner: "Engineer", start: 18, span: 30, status: "On track" },
  { task: "MEP rough-in", owner: "MEP Lead", start: 42, span: 24, status: "Risk" },
  { task: "WIR inspection", owner: "PM", start: 61, span: 12, status: "Pending" },
  { task: "Finishing handover", owner: "Supervisor", start: 73, span: 20, status: "Upcoming" },
];

export const projectSetupPreview = [
  { label: "Project code", value: "GIP-2401", detail: "Auto-generated from company standard" },
  { label: "BOQ import", value: "248 lines", detail: "Item code, unit, quantity, rate, discipline, milestone" },
  { label: "Milestones", value: "14 active", detail: "Baseline, actual dates, dependencies, delay reason" },
  { label: "Progress formula", value: "Weighted BOQ", detail: "Approved quantity divided by planned quantity" },
];

export const reportFlow = [
  {
    title: "Supervisor update",
    owner: "Civil Supervisor",
    detail: "Attendance, work location, overtime, progress, safety incidents, site photos.",
    status: "Submitted",
  },
  {
    title: "Engineer verification",
    owner: "Civil Engineer",
    detail: "Checks work quality, confirms WIR/inspection status, adds official report.",
    status: "In review",
  },
  {
    title: "PM approval",
    owner: "Project Manager",
    detail: "Approves target coverage or rejects with mandatory comments.",
    status: "Pending",
  },
  {
    title: "PDF/email/archive",
    owner: "System",
    detail: "Generates numbered PDF, emails it, and updates dashboard.",
    status: "Automatic",
  },
];

export const reportRows = [
  {
    no: "GIP-2401-DR-20260515-001",
    project: "Al Rayyan Villa Compound",
    owner: "Civil Engineer",
    status: "Pending PM",
    progress: "68%",
    photos: 5,
    due: "10:00 AM",
  },
  {
    no: "GIP-2402-DR-20260515-001",
    project: "Industrial Store Extension",
    owner: "Civil Engineer",
    status: "Draft",
    progress: "42%",
    photos: 3,
    due: "10:00 AM",
  },
  {
    no: "GIP-2403-DR-20260514-002",
    project: "Doha Office Fit-Out",
    owner: "Civil Engineer",
    status: "Approved",
    progress: "81%",
    photos: 5,
    due: "Complete",
  },
];

export const formSections = [
  "Project/date/weather",
  "Work area/location",
  "Manpower and OT",
  "Equipment usage",
  "Material consumption",
  "Safety incidents",
  "Visitors/subcontractors",
  "WIR/inspection status",
  "Delays and next-day plan",
  "Photos and attachments",
];

export const reportFormPreview = [
  { label: "Weather", value: "Sunny, 34.5 C", status: "Auto + manual" },
  { label: "Manpower", value: "12 masons, 20 helpers", status: "8h + OT" },
  { label: "Equipment", value: "2 mixers, 1 pump", status: "6h used" },
  { label: "Materials", value: "150 cement bags", status: "stock linked" },
  { label: "Safety", value: "0 incidents", status: "mandatory" },
  { label: "WIR", value: "WIR-CIV-014-B", status: "pending PM" },
];

export const reportOutcomeCards = [
  { label: "Draft saved", value: "30 sec autosave", detail: "Field user never loses work" },
  { label: "Submit", value: "Engineer verified", detail: "Mandatory sections complete" },
  { label: "Approve", value: "PM decision", detail: "Reject reason stays in history" },
  { label: "Export", value: "PDF + email", detail: "Archive, audit, dashboard update" },
];

export const approvalItems = [
  {
    type: "Daily Report",
    title: "Al Rayyan Villa Compound - DR 001",
    route: "Supervisor -> Engineer -> PM",
    sla: "6h left",
    status: "PM pending",
  },
  {
    type: "Material Request",
    title: "Steel bundle request - USD 1,420",
    route: "Requester -> Engineer -> PM -> OM",
    sla: "Escalates at 48h",
    status: "OM required",
  },
  {
    type: "Document",
    title: "MIR-2026-014 revision B",
    route: "Uploader -> PM -> Active",
    sla: "22h left",
    status: "PM pending",
  },
  {
    type: "Invoice",
    title: "Supplier invoice INV-8842",
    route: "Accounts -> OM",
    sla: "1 day left",
    status: "Accounts checked",
  },
];

export const materials = [
  {
    code: "MAT-CEM-001",
    name: "Cement OPC 43",
    location: "Central warehouse",
    stock: 820,
    unit: "Bags",
    min: 500,
    status: "Healthy",
  },
  {
    code: "MAT-STL-012",
    name: "Steel rebar 12mm",
    location: "Al Rayyan site",
    stock: 18,
    unit: "TON",
    min: 25,
    status: "Low",
  },
  {
    code: "TOOL-DRL-004",
    name: "Rotary drill",
    location: "Industrial store",
    stock: 4,
    unit: "Nos",
    min: 3,
    status: "Reserved",
  },
];

export const materialLifecycle = [
  "Requested",
  "Engineer reviewed",
  "PM approved",
  "Reserved",
  "Issued / partially issued / cancelled",
];

export const materialRequestFlow = [
  { step: "Request", owner: "Supervisor / Engineer", detail: "Select material, location, quantity, project, and required date." },
  { step: "Approve", owner: "Engineer -> PM -> OM", detail: "High-value requests above USD 1,000 route to Operation Manager." },
  { step: "Reserve", owner: "System / Store Keeper", detail: "Approved quantity is reserved to prevent double issue." },
  { step: "Issue", owner: "Store Keeper", detail: "Stock movement records handler, reference, project, and partial issue state." },
];

export const materialTransactions = [
  { type: "Transfer", item: "Steel rebar 12mm", qty: "7 TON", from: "Central warehouse", to: "Al Rayyan site" },
  { type: "Consumption", item: "Cement OPC 43", qty: "150 Bags", from: "Al Rayyan site", to: "DR-20260515" },
  { type: "Return", item: "Rotary drill", qty: "1 Nos", from: "Doha Office", to: "Industrial store" },
];

export const suppliers = [
  { name: "Qatar Build Supplies", category: "Cement", terms: "30 days", tds: "Valid" },
  { name: "Doha Steel Trading", category: "Steel", terms: "45 days", tds: "Expiring" },
  { name: "Site Tools WLL", category: "Tools", terms: "COD", tds: "Valid" },
];

export const documents = [
  {
    number: "GIP-2401-WIR-CIV-2026-014-B",
    type: "WIR",
    project: "Al Rayyan Villa Compound",
    status: "Pending approval",
    version: "Rev B",
    size: "18 MB",
  },
  {
    number: "GIP-2402-MIR-MEP-2026-006-A",
    type: "MIR",
    project: "Industrial Store Extension",
    status: "Active",
    version: "Rev A",
    size: "7 MB",
  },
  {
    number: "GIP-2403-DN-CIV-2026-021-A",
    type: "Delivery Note",
    project: "Doha Office Fit-Out",
    status: "Superseded",
    version: "Rev A",
    size: "2 MB",
  },
];

export const documentControlStates = [
  { state: "Upload", detail: "Civil Engineer uploads WIR/MIR/MAR/delivery note with project metadata." },
  { state: "Review", detail: "Project Manager approves before the version becomes active for the field team." },
  { state: "Active", detail: "Current revision is previewable in browser and visible to permitted roles." },
  { state: "Superseded", detail: "Old versions remain downloadable for managers with a strong warning." },
  { state: "Renew", detail: "Expiry dates trigger reminders before compliance documents lapse." },
];

export const photoCards = [
  { label: "Supervisor upload", project: "Al Rayyan", meta: "5/5 photos, watermark applied", tone: "orange" },
  { label: "Compressed display", project: "Doha Office", meta: "1920px display version", tone: "blue" },
  { label: "Offline queue", project: "Industrial Store", meta: "2 waiting for network", tone: "purple" },
  { label: "Admin recoverable", project: "Archive", meta: "soft deleted, 30-day restore", tone: "green" },
];

export const invoices = [
  { no: "INV-8842", supplier: "Doha Steel Trading", amount: "QAR 18,200", status: "OM approval" },
  { no: "INV-8811", supplier: "Qatar Build Supplies", amount: "QAR 9,760", status: "Paid" },
  { no: "INV-8794", supplier: "Site Tools WLL", amount: "QAR 2,450", status: "Accounts review" },
];

export const financeCards = [
  { label: "Budget vs actual", value: "72%", icon: WalletCards },
  { label: "Manpower cost", value: "QAR 42k", icon: HardHat },
  { label: "Pending payment", value: "QAR 20.6k", icon: CalendarClock },
  { label: "Project P&L", value: "Phase 2", icon: Archive },
];

export const financeWorkflow = [
  { label: "Invoice captured", value: "INV-8842", detail: "Supplier, project, amount, due date, attachment" },
  { label: "Accounts checked", value: "QAR 18.2k", detail: "Linked to steel supply and project budget" },
  { label: "OM approval", value: "Pending", detail: "Payment cannot proceed without decision" },
  { label: "Cost rollup", value: "Budget impact", detail: "Manpower + material + invoice feeds project P&L" },
];

export const notifications = [
  { label: "Approval pending", target: "Assigned approver", timing: "Immediate + 24h reminder" },
  { label: "Late report", target: "Submitter, then PM", timing: "10:00 AM next day" },
  { label: "Low stock", target: "Store Keeper, PM, OM", timing: "Threshold crossed" },
  { label: "Active document", target: "Project team", timing: "After approval" },
];

export const users = [
  { name: "Mohamed Admin", role: "Admin", status: "Active", last: "Today" },
  { name: "N. Rahman", role: "Project Manager", status: "Active", last: "Today" },
  { name: "A. Thomas", role: "Civil Engineer", status: "Active", last: "Yesterday" },
  { name: "K. Ali", role: "Civil Supervisor", status: "Inactive", last: "2026-04-21" },
];

export const auditRows = [
  { event: "Report approved", actor: "N. Rahman", target: "GIP-2401-DR-20260515-001" },
  { event: "Download logged", actor: "Accounts", target: "INV-8842.pdf" },
  { event: "Admin override", actor: "Admin", target: "Delegated PM approval" },
  { event: "User deactivated", actor: "Admin", target: "K. Ali" },
];

export const adminSecurityControls = [
  { label: "RBAC", detail: "Fixed MVP roles with future customizable permissions in database design." },
  { label: "Identity history", detail: "Deactivate users instead of overwriting names, preserving historical reports." },
  { label: "Override control", detail: "Delegation or Admin override requires reason, timestamp, original approver, acting user." },
  { label: "Audit evidence", detail: "Create, update, delete, login, download, and approve actions stay queryable." },
];

export const mobileFeatures = [
  "Supervisor update flow",
  "Engineer report/update",
  "Photo upload and queue",
  "Document view",
  "Approvals and notifications",
  "30-second autosave",
];

export const mobileFieldStates = [
  { label: "Offline draft", value: "Saved locally", detail: "Report remains editable until network returns." },
  { label: "Camera capture", value: "5 photos", detail: "Watermark, compress, thumbnail, queue." },
  { label: "Sync", value: "2 waiting", detail: "Uploads resume when online." },
  { label: "Document view", value: "Rev B active", detail: "Field team sees the approved version." },
];

export const securityItems = [
  { label: "2FA", detail: "Email OTP for MVP, authenticator app later" },
  { label: "Session", detail: "1-day session with short access token and silent refresh" },
  { label: "Lockout", detail: "3 failed attempts" },
  { label: "Blocked files", detail: ".exe, .sh, .bat, .cmd, .js, .php, .html, unknown binaries" },
  { label: "Audit", detail: "View, download, create, update, delete, login, approve" },
  { label: "Retention", detail: "Audit logs 7 years, deleted records recoverable 30 days" },
];

export const deliveryItems = [
  { label: "Hosting", detail: "Cloud VPS with Docker Compose for MVP", icon: Cloud },
  { label: "Environments", detail: "Staging and production", icon: Route },
  { label: "Deployment", detail: "GitHub Actions to staging, production approval by OM", icon: Truck },
  { label: "Backups", detail: "Daily 30 days, monthly 12 months, monthly restore test", icon: Database },
  { label: "Testing", detail: "Chrome, Edge, Safari iOS, Android Chrome, low-speed network", icon: BookOpenCheck },
  { label: "Migration", detail: "Import users, projects, suppliers, materials, BOQ, opening stock", icon: Archive },
];

export const apiEndpoints = [
  "/auth/login",
  "/projects/{id}/timeline",
  "/reports/{id}/submit",
  "/photos/upload",
  "/materials/low-stock",
  "/documents/{id}/versions",
  "/approvals/inbox",
  "/notifications/unread-count",
  "/dashboard/summary",
];

export const remainingInputs = [
  "Company logo, colors, typography, and paper forms",
  "Final first-release module sign-off",
  "General Manager approval/read-only authority",
  "BOQ, report, and document numbering templates",
  "Hosting provider, backup location, and server owner",
  "Source spreadsheets for users, projects, suppliers, materials, BOQ, and stock",
];

export const walkthroughSteps = [
  {
    step: "1",
    title: "Create project baseline",
    screen: "Projects",
    detail: "Admin/Operation Manager creates project, BOQ, milestones, members, and deadlines.",
  },
  {
    step: "2",
    title: "Supervisor submits field update",
    screen: "Daily Reports",
    detail: "Attendance, work location, OT, progress, safety, and five site photos are captured.",
  },
  {
    step: "3",
    title: "Engineer verifies and submits report",
    screen: "Daily Reports",
    detail: "Engineer validates quality/WIR status, adds work summary, and submits official report.",
  },
  {
    step: "4",
    title: "Project Manager approves",
    screen: "Approvals",
    detail: "PM approves, rejects with comments, or lets the system escalate after SLA breach.",
  },
  {
    step: "5",
    title: "System updates records",
    screen: "Dashboard",
    detail: "Dashboard, PDF export, email notification, audit log, documents, and costs update.",
  },
];

export const sampleAttachments = [
  {
    name: "GIP-2401-DR-20260515-001.pdf",
    type: "Daily Report PDF",
    owner: "Civil Engineer",
    size: "1.8 MB",
    linkedTo: "Approved daily report",
  },
  {
    name: "site-progress-west-wing-01.jpg",
    type: "Watermarked Photo",
    owner: "Civil Supervisor",
    size: "820 KB",
    linkedTo: "Photo evidence",
  },
  {
    name: "GIP-2401-WIR-CIV-2026-014-B.pdf",
    type: "WIR Document",
    owner: "Project Manager",
    size: "18 MB",
    linkedTo: "Document control",
  },
  {
    name: "boq-import-template.xlsx",
    type: "BOQ Import",
    owner: "Operation Manager",
    size: "240 KB",
    linkedTo: "Project baseline",
  },
  {
    name: "supplier-tds-certificate.pdf",
    type: "Supplier Compliance",
    owner: "Store Keeper",
    size: "950 KB",
    linkedTo: "Supplier record",
  },
  {
    name: "INV-8842-steel-supply.pdf",
    type: "Invoice",
    owner: "Accounts",
    size: "1.1 MB",
    linkedTo: "Payment approval",
  },
];
