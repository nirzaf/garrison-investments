import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function SecurityScreen() {
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
      <Panel title="Compliance posture" icon={<ShieldCheck size={18} />}>
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
