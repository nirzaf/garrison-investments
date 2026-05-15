import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function ReportsScreen() {
  const statusLabels: Record<string, string> = {
    Submitted: "active",
    "In review": "pending",
    Pending: "pending",
    Automatic: "draft",
  };

  return (
    <div className="screenStack">
      <section className="flowGrid" data-tour-target="report-flow">
        {reportFlow.map((step, index) => (
          <article className="flowCard" key={step.title}>
            <span>{index + 1}</span>
            <small>
              <StatusPill status={statusLabels[step.status] ?? step.status} />
            </small>
            <h3>{step.title}</h3>
            <strong>{step.owner}</strong>
            <p>{step.detail}</p>
          </article>
        ))}
      </section>
      <section className="dualGrid wideLeft">
        <Panel title="Daily report list" icon={<Filter size={18} />}>
          <DataTable
            columns={["Report no.", "Project", "Status", "Progress", "Photos", "Due"]}
            rows={reportRows.map((row) => [
              row.no,
              row.project,
              row.status,
              row.progress,
              `${row.photos}/5`,
              row.due,
            ])}
          />
        </Panel>
        <div data-tour-target="report-form-preview">
          <Panel title="Live report form preview" icon={<Plus size={18} />}>
            <MiniFactGrid rows={reportFormPreview} />
          </Panel>
        </div>
      </section>
      <section className="dualGrid">
        <Panel title="Required form sections" icon={<ListChecks size={18} />}>
          <Checklist items={formSections} />
        </Panel>
        <Panel title="What happens after submit" icon={<FileCheck2 size={18} />}>
          <MiniFactGrid rows={reportOutcomeCards} target="report-outcomes" />
        </Panel>
      </section>
      <Panel title="Sample report attachments" icon={<Upload size={18} />}>
        <AttachmentList filter={["Daily Report PDF", "Watermarked Photo", "WIR Document"]} />
      </Panel>
    </div>
  );
}
