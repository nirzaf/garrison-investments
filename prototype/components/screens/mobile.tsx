import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function MobileScreen() {
  return (
    <div className="dualGrid wideLeft">
      <div data-tour-target="phone-preview">
        <Panel title="Mobile field app preview" icon={<SmartphoneIcon />}>
          <div className="phoneMock">
            <div className="phoneTop">
              <HardHat size={16} />
              Al Rayyan Villa Compound
            </div>
            <div className="phoneStep active">
              <span className="phoneStepDot success" />
              Supervisor update saved
            </div>
            <div className="phoneStep">
              <span className="phoneStepDot pending" />
              Engineer verification pending
            </div>
            <div className="phoneStep">
              <span className="phoneStepDot queue" />
              <span>5 photos queued for upload</span>
            </div>
            <div className="phoneProgressBar">
              <span style={{ width: "65%" }} />
            </div>
            <div className="phoneSyncStatus">
              <WifiOff size={14} />
              <span>2 items waiting for network</span>
            </div>
            <button type="button">Sync when online</button>
          </div>
        </Panel>
      </div>
      <Panel title="Mobile/PWA scope" icon={<CheckCircle2 size={18} />}>
        <Checklist items={mobileFeatures} />
        <div className="noteBox">
          Offline draft saving can wait until Phase 3. Photo upload queue is represented here so the final UX is clear.
        </div>
        <MiniFactGrid rows={mobileFieldStates} target="mobile-field-states" />
      </Panel>
    </div>
  );
}
