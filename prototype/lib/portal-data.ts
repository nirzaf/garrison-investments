import {
  Archive,
  Bell,
  BriefcaseBusiness,
  ClipboardCheck,
  Clock3,
  FileStack,
  HardHat,
  LayoutDashboard,
  PackageCheck,
  ShieldCheck,
  Smartphone,
  UsersRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type PortalModule = {
  title: string;
  status: "MVP" | "Phase 2" | "Phase 3" | "Future";
  summary: string;
  metric: string;
  icon: LucideIcon;
  accent: string;
};

export type WorkflowStep = {
  title: string;
  owner: string;
  description: string;
  time: string;
};

export type RoleCard = {
  role: string;
  scope: string;
  canDo: string[];
};

export const modules: PortalModule[] = [
  {
    title: "Task & Daily Updates",
    status: "MVP",
    summary: "Supervisor updates feed the engineer report and final PM approval.",
    metric: "Core launch flow",
    icon: ClipboardCheck,
    accent: "orange",
  },
  {
    title: "Project Tracking",
    status: "MVP",
    summary: "Projects use BOQ, milestones, Gantt tasks, and discipline progress.",
    metric: "4 active projects",
    icon: BriefcaseBusiness,
    accent: "blue",
  },
  {
    title: "Photo Evidence",
    status: "MVP",
    summary: "Five site photos per report, compressed, thumbnailed, and watermarked.",
    metric: "5/report",
    icon: HardHat,
    accent: "yellow",
  },
  {
    title: "Document Control",
    status: "MVP",
    summary: "MAR, MIR, WIR, and delivery notes with versions and active approval.",
    metric: "60 MB max",
    icon: FileStack,
    accent: "green",
  },
  {
    title: "Approvals",
    status: "MVP",
    summary: "Automatic routing, 24h reminders, 48h escalations, full audit trail.",
    metric: "2-stage flows",
    icon: ShieldCheck,
    accent: "red",
  },
  {
    title: "Materials",
    status: "Phase 2",
    summary: "Requests, reservations, multi-location stock, transfers, and low-stock alerts.",
    metric: "> $1k escalates",
    icon: PackageCheck,
    accent: "teal",
  },
  {
    title: "Accounts",
    status: "Phase 2",
    summary: "Structured invoices, payment status, budgets, manpower cost, P&L reports.",
    metric: "OM approval",
    icon: Archive,
    accent: "purple",
  },
  {
    title: "Offline PWA",
    status: "Phase 3",
    summary: "Offline drafts and photo sync queue with autosave every 30 seconds.",
    metric: "H+ tolerant",
    icon: Smartphone,
    accent: "pink",
  },
];

export const reportFlow: WorkflowStep[] = [
  {
    title: "Supervisor Update",
    owner: "Civil Supervisor",
    description: "Attendance, work location, overtime, progress, and photo evidence.",
    time: "Site entry",
  },
  {
    title: "Quality Verification",
    owner: "Civil Engineer",
    description: "Engineer checks site quality, confirms target coverage, and adds report.",
    time: "Same day",
  },
  {
    title: "Project Approval",
    owner: "Project Manager",
    description: "PM approves final official report or rejects with mandatory comments.",
    time: "24h SLA",
  },
  {
    title: "PDF & Alerts",
    owner: "System",
    description: "Approved report is numbered, emailed, archived, and visible in dashboard.",
    time: "Automatic",
  },
];

export const roleCards: RoleCard[] = [
  {
    role: "General Manager",
    scope: "Executive visibility and selected approvals",
    canDo: ["Review company-wide progress", "See escalations", "Approve scope changes"],
  },
  {
    role: "Operation Manager",
    scope: "Operational control and escalations",
    canDo: ["Approve high-value materials", "Approve invoices", "Receive critical alerts"],
  },
  {
    role: "Project Manager",
    scope: "Project delivery owner",
    canDo: ["Approve reports", "Review WIR progress", "Manage project tasks"],
  },
  {
    role: "Civil Engineer",
    scope: "Official reporting owner",
    canDo: ["Verify supervisor update", "Submit official report", "Upload documents"],
  },
  {
    role: "Civil Supervisor",
    scope: "Field update owner",
    canDo: ["Update attendance", "Record work location", "Upload site photos"],
  },
  {
    role: "Accounts",
    scope: "Financial visibility",
    canDo: ["Track invoices", "Track budget vs actual", "Prepare P&L and salary sheets"],
  },
];

export const dummyProjects = [
  {
    code: "GIP-2401",
    name: "Al Rayyan Villa Compound",
    progress: 68,
    phase: "Finishing",
    reports: 18,
    delayed: 2,
  },
  {
    code: "GIP-2402",
    name: "Industrial Store Extension",
    progress: 42,
    phase: "MEP",
    reports: 11,
    delayed: 1,
  },
  {
    code: "GIP-2403",
    name: "Doha Office Fit-Out",
    progress: 81,
    phase: "Civil",
    reports: 27,
    delayed: 0,
  },
];

export const decisionCards = [
  {
    title: "MVP Shape",
    value: "Real operational portal",
    detail: "Launch around task/report update, document control, approvals, and essentials.",
  },
  {
    title: "Daily Report Number",
    value: "PROJECTCODE-DR-YYYYMMDD-###",
    detail: "Final report is the engineer report approved by the Project Manager.",
  },
  {
    title: "Browser Support",
    value: "Chrome, Edge, Safari iOS, Android Chrome",
    detail: "Edge replaces Internet Explorer due to IE end-of-life.",
  },
  {
    title: "Security",
    value: "2FA + 1-day session",
    detail: "Email OTP for MVP, download logging, 3 failed attempts lockout.",
  },
];

export const openItems = [
  "Collect company logo, colors, typography, and paper forms.",
  "Confirm final first-release module list and material placeholder needs.",
  "Confirm General Manager visibility/approval authority.",
  "Collect BOQ, report, and document numbering templates.",
  "Confirm hosting provider, backup location, and internal server owner.",
  "Collect spreadsheet data for users, projects, suppliers, materials, BOQ, and stock.",
];

export const navItems = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "flow", label: "Report Flow", icon: Clock3 },
  { id: "roles", label: "Roles", icon: UsersRound },
  { id: "decisions", label: "Decisions", icon: Bell },
];
