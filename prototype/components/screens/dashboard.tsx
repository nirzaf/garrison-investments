import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function DashboardScreen() {
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
