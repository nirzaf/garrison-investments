import { AlertCircle, Bell, BriefcaseBusiness, Camera, CheckCircle2, CircleDashed, FileCheck2, FileText, Filter, HardHat, ListChecks, Map, Plus, Search, ShieldCheck, Upload, WifiOff } from "lucide-react";

import { adminSecurityControls, approvalItems, auditRows, dashboardPanels, deliveryItems, documentControlStates, documents, financeCards, financeWorkflow, formSections, ganttTasks, inventoryItems, inventoryMovementFlow, invoices, kpis, lowStockByLocation, materialLifecycle, materialTransactions, mobileFeatures, mobileFieldStates, notifications, photoCards, projectSetupPreview, projects, reportFlow, reportFormPreview, reportOutcomeCards, reportRows, roleMatrix, securityItems, storageLocations, suppliers, toolAssets, users } from "@/lib/portal-data";
import { AttachmentList, BarList, CardList, Checklist, DataTable, Detail, MetricCard, MiniFactGrid, PackageIcon, Panel, ProcessStrip, RouteIcon, SmartphoneIcon, StatusPill } from "@/components/shared";

export function NotificationsScreen() {
  return (
    <div className="screenStack">
      <section className="contentGrid two" data-tour-target="notification-cards">
        {notifications.map((item) => (
          <article className="notificationCard" key={item.label}>
            <Bell size={18} />
            <h3>{item.label}</h3>
            <strong>{item.target}</strong>
            <p>{item.timing}</p>
          </article>
        ))}
      </section>
      <Panel title="Notification behavior" icon={<Bell size={18} />}>
        <Checklist
          items={[
            "In-app and email notifications",
            "Users can mute non-critical alerts",
            "90-day user-facing notification history",
            "Unread count in header",
            "Audit records retained separately",
          ]}
        />
      </Panel>
    </div>
  );
}
