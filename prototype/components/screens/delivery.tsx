import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function DeliveryScreen() {
  return (
    <div className="screenStack">
      <section className="contentGrid three" data-tour-target="delivery-plan">
        {deliveryItems.map((item) => (
          <article className="featureCard" key={item.label}>
            <item.icon size={22} />
            <span>Recommended</span>
            <h3>{item.label}</h3>
            <p>{item.detail}</p>
          </article>
        ))}
      </section>
      <Panel title="Launch acceptance scenarios" icon={<CheckCircle2 size={18} />}>
        <Checklist
          items={[
            "Login and 2FA",
            "User creation",
            "Project creation",
            "Supervisor update",
            "Engineer report",
            "Approval and rejection",
            "Photo upload",
            "Document version upload",
            "Notification and export",
          ]}
        />
      </Panel>
      <Panel title="Sample import and launch attachments" icon={<Upload size={18} />}>
        <AttachmentList filter={["BOQ Import", "Supplier Compliance"]} />
      </Panel>
    </div>
  );
}
