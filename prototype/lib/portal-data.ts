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
  PackageCheck,
  Route,
  ShieldCheck,
  Smartphone,
  Truck,
  UsersRound,
  WalletCards,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import navigationData from "@/lib/data/navigation.json";
import overviewData from "@/lib/data/overview.json";
import requirementCoverageData from "@/lib/data/requirement-coverage.json";
import dashboardData from "@/lib/data/dashboard.json";
import projectsData from "@/lib/data/projects.json";
import reportsData from "@/lib/data/reports.json";
import approvalsData from "@/lib/data/approvals.json";
import inventoryStoresData from "@/lib/data/inventory-stores.json";
import documentsData from "@/lib/data/documents.json";
import photosData from "@/lib/data/photos.json";
import accountsData from "@/lib/data/accounts.json";
import notificationsData from "@/lib/data/notifications.json";
import adminData from "@/lib/data/admin.json";
import mobileData from "@/lib/data/mobile.json";
import securityData from "@/lib/data/security.json";
import rolloutPlanData from "@/lib/data/rollout-plan.json";
import tourData from "@/lib/data/tour.json";
import featureGuidesData from "@/lib/data/feature-guides.json";
import sampleAttachmentsData from "@/lib/data/sample-attachments.json";

const iconMap: Record<string, LucideIcon> = {
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
  PackageCheck,
  Route,
  ShieldCheck,
  Smartphone,
  Truck,
  UsersRound,
  WalletCards,
};

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
  group: PortalNavGroup;
};

export type PortalNavGroup = "core" | "management" | "phase2" | "delivery";

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

export const navItems: PortalNavItem[] = navigationData.map((item) => ({
  ...item,
  icon: iconMap[item.icon],
})) as PortalNavItem[];

export const kpis = overviewData.kpis;

export const launchModules = overviewData.launchModules.map((item) => ({
  ...item,
  icon: iconMap[item.icon],
}));

export const operatingCapabilities = overviewData.operatingCapabilities;

export const operatingDomains = overviewData.operatingDomains;

export const requirementCoverage: RequirementCoverage[] = requirementCoverageData as RequirementCoverage[];

export const dashboardPanels = dashboardData.dashboardPanels;

export const businessFlow = overviewData.businessFlow;

export const productTourSteps: ProductTourStep[] = tourData.productTourSteps as ProductTourStep[];

export const featureGuides: Record<ScreenKey, FeatureGuide> = featureGuidesData as Record<ScreenKey, FeatureGuide>;

export const roleMatrix = adminData.roleMatrix;

export const projects = projectsData.projects;

export const ganttTasks = projectsData.ganttTasks;

export const projectSetupPreview = projectsData.projectSetupPreview;

export const reportFlow = reportsData.reportFlow;

export const reportRows = reportsData.reportRows;

export const formSections = reportsData.formSections;

export const reportFormPreview = reportsData.reportFormPreview;

export const reportOutcomeCards = reportsData.reportOutcomeCards;

export const approvalItems = approvalsData.approvalItems;

export const storageLocations = inventoryStoresData.storageLocations;

export const inventoryItems = inventoryStoresData.inventoryItems;

export const toolAssets = inventoryStoresData.toolAssets;

export const materialLifecycle = inventoryStoresData.materialLifecycle;

export const inventoryMovementFlow = inventoryStoresData.inventoryMovementFlow;

export const materialTransactions = inventoryStoresData.materialTransactions;

export const lowStockByLocation = inventoryStoresData.lowStockByLocation;

export const suppliers = inventoryStoresData.suppliers;

export const documents = documentsData.documents;

export const documentControlStates = documentsData.documentControlStates;

export const photoCards = photosData.photoCards;

export const invoices = accountsData.invoices;

export const financeCards = accountsData.financeCards.map((item) => ({
  ...item,
  icon: iconMap[item.icon],
}));

export const financeWorkflow = accountsData.financeWorkflow;

export const notifications = notificationsData.notifications;

export const users = adminData.users;

export const auditRows = adminData.auditRows;

export const adminSecurityControls = adminData.adminSecurityControls;

export const mobileFeatures = mobileData.mobileFeatures;

export const mobileFieldStates = mobileData.mobileFieldStates;

export const securityItems = securityData.securityItems;

export const deliveryItems = rolloutPlanData.deliveryItems.map((item) => ({
  ...item,
  icon: iconMap[item.icon],
}));

export const apiEndpoints = rolloutPlanData.apiEndpoints;

export const remainingInputs = rolloutPlanData.remainingInputs;

export const walkthroughSteps = tourData.walkthroughSteps;

export const sampleAttachments = sampleAttachmentsData;
