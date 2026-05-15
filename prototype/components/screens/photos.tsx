import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function PhotosScreen() {
  return (
    <div className="screenStack">
      <section className="photoGrid" data-tour-target="photo-grid">
        {photoCards.map((photo) => (
          <article className={`photoCard tone-${photo.tone}`} key={photo.label}>
            <div />
            <span>{photo.project}</span>
            <h3>{photo.label}</h3>
            <p>{photo.meta}</p>
          </article>
        ))}
      </section>
      <Panel title="Media handling rules" icon={<Camera size={18} />}>
        <Checklist
          items={[
            "Maximum 5 photos per report",
            "10 MB per file",
            "Store original, compressed display image, and thumbnail",
            "Recommended compression: 1920px longest side, quality 75-85",
            "Watermark with company name",
            "Deleted photos recoverable by Admin",
          ]}
        />
      </Panel>
      <Panel title="Sample media attachment" icon={<Upload size={18} />}>
        <AttachmentList filter={["Watermarked Photo"]} />
      </Panel>
    </div>
  );
}
