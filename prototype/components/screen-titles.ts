import type { ScreenKey } from "@/lib/portal-data";

export const screenTitles: Record<ScreenKey, string> = {
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
