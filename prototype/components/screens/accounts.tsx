import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function AccountsScreen() {
  return (
    <div className="screenStack">
      <div className="kpiGrid compact" data-tour-target="finance-kpis">
        {financeCards.map((card) => (
          <article className="metricCard" key={card.label}>
            <card.icon size={20} />
            <span>{card.label}</span>
            <strong>{card.value}</strong>
          </article>
        ))}
      </div>
      <DataTable
        columns={["Invoice", "Supplier", "Amount", "Status"]}
        rows={invoices.map((invoice) => [
          invoice.no,
          invoice.supplier,
          invoice.amount,
          invoice.status,
        ])}
      />
      <Panel title="Invoice to project P&L workflow" icon={<FileCheck2 size={18} />}>
        <MiniFactGrid rows={financeWorkflow} target="finance-workflow" />
      </Panel>
      <Panel title="Finance requirements" icon={<CheckCircle2 size={18} />}>
        <Checklist
          items={[
            "Structured invoice fields, not only document upload",
            "Accounts create/check, Operation Manager approves",
            "Project budget vs actual cost",
            "Manpower cost and salary sheets",
            "Bookkeeping and project-wise profit/loss",
            "OCR is future enhancement, not MVP",
          ]}
        />
      </Panel>
      <Panel title="Sample finance attachment" icon={<Upload size={18} />}>
        <AttachmentList filter={["Invoice"]} />
      </Panel>
    </div>
  );
}
