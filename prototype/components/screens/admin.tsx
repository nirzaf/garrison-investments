import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function AdminScreen() {
  return (
    <div className="screenStack">
      <section className="dualGrid" data-tour-target="admin-grid">
        <Panel title="User management" icon={<Plus size={18} />}>
          <DataTable
            columns={["Name", "Role", "Status", "Last login"]}
            rows={users.map((user) => [user.name, user.role, user.status, user.last])}
          />
        </Panel>
        <Panel title="Audit log" icon={<FileText size={18} />}>
          <DataTable
            columns={["Event", "Actor", "Target"]}
            rows={auditRows.map((row) => [row.event, row.actor, row.target])}
          />
        </Panel>
      </section>
      <Panel title="Admin rules" icon={<ShieldCheck size={18} />}>
        <Checklist
          items={[
            "Deactivate old users; never overwrite historical identity",
            "Customizable permissions later, fixed role matrix in MVP",
            "Approved reports cannot be edited by Admin",
            "Admin overrides require reason and audit trail",
            "Deleted records recoverable for 30 days",
          ]}
        />
      </Panel>
      <Panel title="Enterprise governance controls" icon={<ShieldCheck size={18} />}>
        <MiniFactGrid rows={adminSecurityControls} target="admin-security-controls" />
      </Panel>
    </div>
  );
}
