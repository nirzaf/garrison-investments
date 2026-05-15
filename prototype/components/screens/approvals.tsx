import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function ApprovalsScreen() {
  const approvalStatusMap: Record<string, string> = {
    "PM pending": "Pending",
    "OM required": "Pending",
    "Accounts checked": "Approved",
  };

  return (
    <div className="screenStack">
      <section className="contentGrid two" data-tour-target="approval-cards">
        {approvalItems.map((item) => (
          <article className="approvalCard" key={item.title}>
            <span>{item.type}</span>
            <h3>{item.title}</h3>
            <p>{item.route}</p>
            <div>
              <strong>{item.sla}</strong>
              <StatusPill status={approvalStatusMap[item.status] ?? item.status} />
            </div>
            <div className="buttonRow">
              <button type="button">Approve</button>
              <button className="dangerButton" type="button">Reject with reason</button>
            </div>
          </article>
        ))}
      </section>
      <Panel title="Approval rules" icon={<ShieldCheck size={18} />}>
        <Checklist
          items={[
            "Approver is selected automatically by project/role",
            "Rejection reason is mandatory",
            "24-hour reminder and 48-hour escalation",
            "Admin override and delegation require audit reason",
            "Approval comments visible only to managers",
          ]}
        />
      </Panel>
    </div>
  );
}
