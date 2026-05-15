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

export type FeatureGuide = {
  owner: string;
  startsWhen: string;
  userAction: string;
  systemAction: string;
  businessResult: string;
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
    label: "First-minute clarity",
    value: "One guided tour",
    detail: "A stakeholder can understand the full product without reading the specification.",
  },
  {
    label: "Core revenue workflow",
    value: "Report to approval",
    detail: "The prototype follows the highest-value construction operations path end to end.",
  },
  {
    label: "Operational control",
    value: "Role + audit first",
    detail: "Every action shows who owns it, who approves it, and what record is created.",
  },
  {
    label: "Scalable roadmap",
    value: "MVP to Phase 3",
    detail: "Materials, accounts, mobile, and offline behavior are previewed without hiding the launch scope.",
  },
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

export const mobileFeatures = [
  "Supervisor update flow",
  "Engineer report/update",
  "Photo upload and queue",
  "Document view",
  "Approvals and notifications",
  "30-second autosave",
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
