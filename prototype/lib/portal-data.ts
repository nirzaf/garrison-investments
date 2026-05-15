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
import materialsData from "@/lib/data/materials.json";
import documentsData from "@/lib/data/documents.json";
import photosData from "@/lib/data/photos.json";
import accountsData from "@/lib/data/accounts.json";
import notificationsData from "@/lib/data/notifications.json";
import adminData from "@/lib/data/admin.json";
import mobileData from "@/lib/data/mobile.json";
import securityData from "@/lib/data/security.json";
import deliveryData from "@/lib/data/delivery.json";
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

export const navItems: PortalNavItem[] = navigationData.map((item) => ({
  ...item,
  icon: iconMap[item.icon],
})) as PortalNavItem[];

export const kpis = overviewData.kpis;

export const launchModules = overviewData.launchModules.map((item) => ({
  ...item,
  icon: iconMap[item.icon],
}));

export const investorHighlights = overviewData.investorHighlights;

export const painPointComparisons = overviewData.painPointComparisons;

export const requirementCoverage: RequirementCoverage[] = requirementCoverageData as RequirementCoverage[];

export const dashboardPanels = dashboardData.dashboardPanels;

export const businessFlow = overviewData.businessFlow;

export const guidedTourSteps: GuidedTourStep[] = tourData.guidedTourSteps as GuidedTourStep[];

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

export const storageLocations = materialsData.storageLocations;

export const inventoryItems = materialsData.inventoryItems;

export const toolAssets = materialsData.toolAssets;

export const materialLifecycle = materialsData.materialLifecycle;

export const inventoryMovementFlow = materialsData.inventoryMovementFlow;

export const materialTransactions = materialsData.materialTransactions;

export const lowStockByLocation = materialsData.lowStockByLocation;

export const suppliers = materialsData.suppliers;

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

export const deliveryItems = deliveryData.deliveryItems.map((item) => ({
  ...item,
  icon: iconMap[item.icon],
}));

export const apiEndpoints = deliveryData.apiEndpoints;

export const remainingInputs = deliveryData.remainingInputs;

export const walkthroughSteps = tourData.walkthroughSteps;

export const sampleAttachments = sampleAttachmentsData;
