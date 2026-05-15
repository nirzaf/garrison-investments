import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function DocumentsScreen() {
  return (
    <div className="screenStack">
      <section className="toolbarMock">
        <button type="button"><Upload size={15} /> Upload document</button>
        <button type="button"><Search size={15} /> Search contents</button>
        <button type="button"><Filter size={15} /> Type/project filters</button>
      </section>
      <div data-tour-target="documents-table">
        <DataTable
          columns={["Document no.", "Type", "Project", "Version", "Status", "Size"]}
          rows={documents.map((doc) => [
            doc.number,
            doc.type,
            doc.project,
            doc.version,
            doc.status,
            doc.size,
          ])}
        />
      </div>
      <section className="dualGrid">
        <Panel title="Version control preview" icon={<FileText size={18} />}>
          <div className="versionStack">
            <div>
              <strong>Rev C</strong>
              <StatusPill status="pending" />
            </div>
            <div>
              <strong>Rev B</strong>
              <StatusPill status="active" />
            </div>
            <div>
              <strong>Rev A</strong>
              <StatusPill status="superseded" />
            </div>
          </div>
        </Panel>
        <Panel title="Document decisions" icon={<CheckCircle2 size={18} />}>
          <Checklist
            items={[
              "First release: MAR, MIR, WIR, delivery notes",
              "PDF preview in browser",
              "CAD/DWG stored and downloadable; preview later",
              "60 MB max file size",
              "Expiry dates and renewal reminders",
            ]}
          />
        </Panel>
      </section>
      <Panel title="Document governance flow" icon={<ShieldCheck size={18} />}>
        <ProcessStrip rows={documentControlStates} target="document-flow" />
      </Panel>
      <Panel title="Sample controlled documents" icon={<Upload size={18} />}>
        <AttachmentList filter={["WIR Document", "BOQ Import", "Daily Report PDF"]} />
      </Panel>
    </div>
  );
}
