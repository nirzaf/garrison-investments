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
